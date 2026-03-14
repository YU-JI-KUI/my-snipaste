"""
截图编辑窗口

功能：
  - 显示截取的图片
  - 文字工具：点击位置弹出输入框，确认后固化到画布
  - 颜色选择（预设色板）
  - 字体大小调节
  - 保存为 PNG 文件
  - 复制到剪贴板（通过 PowerShell）

文字添加分两个阶段：
  编辑态：Canvas 上悬浮一个 Entry 控件，用户输入
  固化态：Entry 消失，用 canvas.create_text() 渲染，同时记录到 annotations 列表
  保存时：用 Pillow 重绘截图 + 所有 annotations，输出最终图片
"""

import os
import subprocess
import tempfile
import logging
import datetime
import tkinter as tk
from tkinter import filedialog, messagebox
from PIL import Image, ImageDraw, ImageFont, ImageTk


# Windows 内置字体路径（按优先级）
WINDOWS_FONTS = [
    'C:/Windows/Fonts/msyh.ttc',      # 微软雅黑（支持中文）
    'C:/Windows/Fonts/msyhbd.ttc',    # 微软雅黑粗体
    'C:/Windows/Fonts/simhei.ttf',    # 黑体
    'C:/Windows/Fonts/arial.ttf',     # Arial（英文）
]

# 预设颜色列表（文字颜色）
PRESET_COLORS = [
    ('#FF3B30', '红色'),
    ('#FF9500', '橙色'),
    ('#FFCC00', '黄色'),
    ('#34C759', '绿色'),
    ('#007AFF', '蓝色'),
    ('#AF52DE', '紫色'),
    ('#FFFFFF', '白色'),
    ('#000000', '黑色'),
]


def _find_font(size):
    """查找可用的字体文件，fallback 到默认字体"""
    for path in WINDOWS_FONTS:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


class EditorWindow:
    """截图编辑窗口"""

    def __init__(self, root, image: Image.Image):
        self.root = root
        self._image = image.copy()   # 保留原始截图，用于最终合成

        self._annotations = []        # 固化的标注列表
        self._active_entry = None     # 当前正在编辑的 Entry 控件
        self._active_entry_pos = None # 当前 Entry 的 (x, y) 位置

        self._tool = 'text'          # 当前工具
        self._color = '#FF3B30'       # 当前文字颜色（默认红色）
        self._font_size = 18          # 当前字体大小

        self._tk_image = None         # ImageTk，防止被 GC

        self._build_window()

    def _build_window(self):
        win = tk.Toplevel(self.root)
        self._win = win
        win.title('my-snipaste — 截图编辑')
        win.resizable(True, True)
        win.attributes('-topmost', True)

        # 关闭窗口时取消置顶并销毁
        win.protocol('WM_DELETE_WINDOW', self._on_close)

        img_w, img_h = self._image.size

        # 如果图片太大，缩小到不超过屏幕 90%
        screen_w = win.winfo_screenwidth()
        screen_h = win.winfo_screenheight()
        max_w = int(screen_w * 0.9)
        max_h = int(screen_h * 0.85)

        self._display_scale = 1.0
        if img_w > max_w or img_h > max_h:
            scale = min(max_w / img_w, max_h / img_h)
            self._display_scale = scale
            display_w = int(img_w * scale)
            display_h = int(img_h * scale)
        else:
            display_w = img_w
            display_h = img_h

        self._display_w = display_w
        self._display_h = display_h

        # ── 工具栏 ──
        toolbar = tk.Frame(win, bg='#2C2C2E', padx=6, pady=4)
        toolbar.pack(fill=tk.X)

        self._build_toolbar(toolbar)

        # ── 画布区域（带滚动条）──
        frame = tk.Frame(win)
        frame.pack(fill=tk.BOTH, expand=True)

        hbar = tk.Scrollbar(frame, orient=tk.HORIZONTAL)
        vbar = tk.Scrollbar(frame, orient=tk.VERTICAL)

        canvas = tk.Canvas(
            frame,
            cursor='crosshair',
            bg='#1C1C1E',
            xscrollcommand=hbar.set,
            yscrollcommand=vbar.set,
            scrollregion=(0, 0, display_w, display_h)
        )
        hbar.config(command=canvas.xview)
        vbar.config(command=canvas.yview)

        hbar.pack(side=tk.BOTTOM, fill=tk.X)
        vbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._canvas = canvas

        # 显示截图
        self._refresh_canvas_image()

        # 绑定鼠标点击（文字工具）
        canvas.bind('<ButtonPress-1>', self._on_canvas_click)

        # 快捷键
        win.bind('<Control-s>', lambda e: self._save())
        win.bind('<Control-c>', lambda e: self._copy_to_clipboard())
        win.bind('<Escape>', lambda e: self._on_close())

        # 居中显示
        win.update_idletasks()
        w = min(display_w + 20, screen_w - 40)
        h = min(display_h + 80, screen_h - 40)
        x = (screen_w - w) // 2
        y = (screen_h - h) // 2
        win.geometry(f'{w}x{h}+{x}+{y}')

        win.lift()
        win.focus_force()

    def _build_toolbar(self, toolbar):
        # 标题
        tk.Label(
            toolbar, text='my-snipaste',
            bg='#2C2C2E', fg='#8E8E93',
            font=('微软雅黑', 9)
        ).pack(side=tk.LEFT, padx=(4, 12))

        # 文字工具按钮
        self._tool_btn = tk.Button(
            toolbar, text='T 文字',
            bg='#0A84FF', fg='white',
            font=('微软雅黑', 10),
            relief=tk.FLAT, padx=8, pady=2,
            command=self._select_text_tool
        )
        self._tool_btn.pack(side=tk.LEFT, padx=2)

        tk.Label(toolbar, text='颜色:', bg='#2C2C2E', fg='#EBEBF5',
                 font=('微软雅黑', 9)).pack(side=tk.LEFT, padx=(10, 4))

        # 颜色预设
        for color_hex, color_name in PRESET_COLORS:
            btn = tk.Button(
                toolbar,
                bg=color_hex,
                width=2, height=1,
                relief=tk.FLAT,
                cursor='hand2',
                command=lambda c=color_hex: self._set_color(c)
            )
            btn.pack(side=tk.LEFT, padx=1)

        tk.Label(toolbar, text='字号:', bg='#2C2C2E', fg='#EBEBF5',
                 font=('微软雅黑', 9)).pack(side=tk.LEFT, padx=(10, 4))

        # 字体大小
        self._size_var = tk.StringVar(value=str(self._font_size))
        size_spin = tk.Spinbox(
            toolbar,
            from_=8, to=72,
            textvariable=self._size_var,
            width=4,
            font=('微软雅黑', 10),
            command=self._on_size_change
        )
        size_spin.pack(side=tk.LEFT, padx=2)
        size_spin.bind('<Return>', lambda e: self._on_size_change())

        # 分隔线
        tk.Label(toolbar, text='|', bg='#2C2C2E', fg='#48484A').pack(side=tk.LEFT, padx=8)

        # 保存按钮
        tk.Button(
            toolbar, text='保存  Ctrl+S',
            bg='#30D158', fg='black',
            font=('微软雅黑', 10),
            relief=tk.FLAT, padx=8, pady=2,
            cursor='hand2',
            command=self._save
        ).pack(side=tk.LEFT, padx=2)

        # 复制按钮
        tk.Button(
            toolbar, text='复制  Ctrl+C',
            bg='#636366', fg='white',
            font=('微软雅黑', 10),
            relief=tk.FLAT, padx=8, pady=2,
            cursor='hand2',
            command=self._copy_to_clipboard
        ).pack(side=tk.LEFT, padx=2)

        # 颜色指示（当前颜色）
        self._color_indicator = tk.Label(
            toolbar, bg=self._color, width=3,
            relief=tk.SUNKEN
        )
        self._color_indicator.pack(side=tk.RIGHT, padx=8)
        tk.Label(toolbar, text='当前:', bg='#2C2C2E', fg='#8E8E93',
                 font=('微软雅黑', 9)).pack(side=tk.RIGHT)

    def _refresh_canvas_image(self):
        """重新渲染 Canvas 上的图片（包含所有已固化标注）"""
        # 合成图片
        composed = self._compose()
        # 缩放到显示尺寸
        display_img = composed.resize(
            (self._display_w, self._display_h),
            Image.LANCZOS
        )
        self._tk_image = ImageTk.PhotoImage(display_img)
        self._canvas.delete('all')
        self._canvas.create_image(0, 0, anchor='nw', image=self._tk_image)

    def _compose(self) -> Image.Image:
        """把原始截图 + 所有标注合成为最终图片（原始像素尺寸）"""
        img = self._image.copy().convert('RGBA')
        draw = ImageDraw.Draw(img)

        for ann in self._annotations:
            if ann['type'] == 'text':
                font = _find_font(ann['size'])
                draw.text(
                    (ann['x'], ann['y']),
                    ann['text'],
                    fill=ann['color'],
                    font=font
                )

        return img.convert('RGB')

    # ── 工具控制 ──

    def _select_text_tool(self):
        self._tool = 'text'
        self._tool_btn.config(bg='#0A84FF')

    def _set_color(self, color):
        self._color = color
        self._color_indicator.config(bg=color)

    def _on_size_change(self):
        try:
            self._font_size = max(8, min(72, int(self._size_var.get())))
        except ValueError:
            pass

    # ── Canvas 点击处理 ──

    def _on_canvas_click(self, event):
        if self._tool != 'text':
            return

        # 如果当前有未提交的 Entry，先固化它，再在新位置开 Entry
        if self._active_entry:
            self._commit_entry()

        canvas_x = self._canvas.canvasx(event.x)
        canvas_y = self._canvas.canvasy(event.y)

        self._show_entry(canvas_x, canvas_y)

    def _show_entry(self, canvas_x, canvas_y):
        """在指定位置显示文字输入框"""
        # 估算 Entry 宽度
        entry_width = max(100, self._display_w - int(canvas_x))

        entry = tk.Entry(
            self._canvas,
            font=('微软雅黑', int(self._font_size * self._display_scale)),
            fg=self._color,
            bg='#1C1C1E',
            insertbackground=self._color,
            relief=tk.FLAT,
            bd=1,
            width=30
        )

        entry_win = self._canvas.create_window(
            int(canvas_x), int(canvas_y),
            window=entry,
            anchor='nw',
            tags='entry_window'
        )

        entry.focus_set()

        # 按 Enter 或 Tab 提交
        entry.bind('<Return>', lambda e: self._commit_entry())
        entry.bind('<Tab>', lambda e: self._commit_entry())
        # 失焦时也提交（比如用户切换到其他程序）
        entry.bind('<FocusOut>', lambda e: self.root.after(50, self._commit_if_active))
        # 点击其他位置提交
        self._canvas.bind('<ButtonPress-1>', self._on_canvas_click_with_entry)

        self._active_entry = entry
        self._active_entry_win = entry_win
        self._active_entry_pos = (
            canvas_x / self._display_scale,  # 转换回原始像素坐标
            canvas_y / self._display_scale
        )

    def _commit_if_active(self):
        """FocusOut 延迟回调：只在 Entry 仍然存在时提交（防止重复调用）"""
        if self._active_entry:
            self._commit_entry()

    def _on_canvas_click_with_entry(self, event):
        """有 Entry 时点击画布：先提交当前 Entry，再开新的"""
        self._commit_entry()
        # 恢复正常点击绑定
        self._canvas.bind('<ButtonPress-1>', self._on_canvas_click)
        # 重新触发点击，开新 Entry
        canvas_x = self._canvas.canvasx(event.x)
        canvas_y = self._canvas.canvasy(event.y)
        self._show_entry(canvas_x, canvas_y)

    def _commit_entry(self):
        """固化当前 Entry：读取文字，记录到 annotations，刷新画面"""
        if not self._active_entry:
            return

        text = self._active_entry.get().strip()
        x, y = self._active_entry_pos

        # 删除 Entry 控件
        self._canvas.delete('entry_window')
        self._active_entry.destroy()
        self._active_entry = None
        self._active_entry_win = None

        # 恢复正常点击绑定
        self._canvas.bind('<ButtonPress-1>', self._on_canvas_click)

        if not text:
            return

        # 记录标注
        self._annotations.append({
            'type': 'text',
            'x': x,
            'y': y,
            'text': text,
            'color': self._color,
            'size': self._font_size,
        })

        # 刷新画面
        self._refresh_canvas_image()

    # ── 保存 & 复制 ──

    def _save(self):
        """保存为 PNG 文件"""
        # 如果有未提交的 Entry，先提交
        if self._active_entry:
            self._commit_entry()

        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        default_name = f'screenshot_{timestamp}.png'

        # 默认保存到桌面（兼容 OneDrive 云桌面等非标准路径）
        desktop = os.path.expanduser('~')
        try:
            import winreg
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r'Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders'
            ) as key:
                d = winreg.QueryValueEx(key, 'Desktop')[0]
                if os.path.isdir(d):
                    desktop = d
        except Exception:
            # winreg 不可用或读取失败时，尝试标准路径
            candidate = os.path.join(os.path.expanduser('~'), 'Desktop')
            if os.path.isdir(candidate):
                desktop = candidate

        path = filedialog.asksaveasfilename(
            parent=self._win,
            initialdir=desktop,
            initialfile=default_name,
            defaultextension='.png',
            filetypes=[('PNG 图片', '*.png'), ('所有文件', '*.*')]
        )

        if not path:
            return  # 用户取消

        try:
            final = self._compose()
            final.save(path, 'PNG')
            messagebox.showinfo('保存成功', f'截图已保存到：\n{path}', parent=self._win)
        except Exception as e:
            logging.error(f'保存截图失败: {e}')
            messagebox.showerror('保存失败', str(e), parent=self._win)

    def _copy_to_clipboard(self):
        """复制图片到剪贴板（通过 PowerShell）"""
        if self._active_entry:
            self._commit_entry()

        tmp_path = None
        try:
            final = self._compose()

            # 写入临时文件
            fd, tmp_path = tempfile.mkstemp(suffix='.png')
            os.close(fd)
            final.save(tmp_path, 'PNG')

            # 用 PowerShell 写入剪贴板
            # 使用变量而非字符串拼接，避免路径中特殊字符导致的问题
            ps_script = (
                'Add-Type -AssemblyName System.Windows.Forms; '
                'Add-Type -AssemblyName System.Drawing; '
                '$p = $env:SNIP_TMP_PATH; '
                '$img = [System.Drawing.Image]::FromFile($p); '
                '[System.Windows.Forms.Clipboard]::SetImage($img); '
                '$img.Dispose()'
            )
            env = os.environ.copy()
            env['SNIP_TMP_PATH'] = tmp_path
            result = subprocess.run(
                ['powershell', '-NonInteractive', '-NoProfile', '-Command', ps_script],
                capture_output=True,
                timeout=15,
                env=env
            )

            if result.returncode != 0:
                raise RuntimeError(result.stderr.decode('utf-8', errors='ignore'))

            messagebox.showinfo('复制成功', '截图已复制到剪贴板', parent=self._win)

        except Exception as e:
            logging.error(f'复制到剪贴板失败: {e}')
            messagebox.showerror('复制失败', f'复制失败，请使用保存功能。\n{e}', parent=self._win)
        finally:
            # 3 秒后删除临时文件
            if tmp_path:
                path = tmp_path
                self.root.after(3000, lambda: _safe_delete(path))

    def _on_close(self):
        if self._active_entry:
            self._commit_entry()
        try:
            self._win.destroy()
        except Exception:
            pass


def _safe_delete(path):
    try:
        if os.path.exists(path):
            os.unlink(path)
    except Exception:
        pass
