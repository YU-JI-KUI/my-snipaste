"""
标注工具公共逻辑：_Tooltip、工具函数、AnnotationMixin
供 EditorWindow 和 EditCanvas 共用
"""

import os
import io
import math
import logging
import datetime
import tkinter as tk
from tkinter import filedialog, messagebox
from PIL import Image, ImageDraw, ImageFont, ImageTk

WINDOWS_FONTS = [
    'C:/Windows/Fonts/msyh.ttc',
    'C:/Windows/Fonts/msyhbd.ttc',
    'C:/Windows/Fonts/simhei.ttf',
    'C:/Windows/Fonts/arial.ttf',
]

PRESET_COLORS = [
    '#FF3B30', '#FF9500', '#FFCC00', '#34C759',
    '#007AFF', '#AF52DE', '#FFFFFF', '#000000',
]

DRAG_THR    = 4
TOOLBAR_GAP = 8


def _find_font(size):
    for path in WINDOWS_FONTS:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _draw_arrowhead(draw, x1, y1, x2, y2, color, lw):
    length = max(12, lw * 5)
    angle  = 0.45
    dx, dy = x2 - x1, y2 - y1
    dist = math.hypot(dx, dy)
    if dist < 1:
        return
    ux, uy = -dx / dist, -dy / dist

    def rot(vx, vy, a):
        c, s = math.cos(a), math.sin(a)
        return vx*c - vy*s, vx*s + vy*c

    l = rot(ux, uy, -angle)
    r = rot(ux, uy,  angle)
    draw.polygon([
        (x2, y2),
        (x2 + l[0]*length, y2 + l[1]*length),
        (x2 + r[0]*length, y2 + r[1]*length),
    ], fill=color)


class _Tooltip:
    def __init__(self, widget, text):
        self._widget   = widget
        self._text     = text
        self._tip      = None
        self._after_id = None
        widget.bind('<Enter>', self._on_enter)
        widget.bind('<Leave>', self._on_leave)

    def _on_enter(self, event):
        self._after_id = self._widget.after(500, self._show)

    def _on_leave(self, event):
        if self._after_id:
            self._widget.after_cancel(self._after_id)
            self._after_id = None
        self._hide()

    def _show(self):
        x = self._widget.winfo_rootx() + self._widget.winfo_width() // 2
        y = self._widget.winfo_rooty() + self._widget.winfo_height() + 4
        self._tip = tk.Toplevel(self._widget)
        self._tip.overrideredirect(True)
        self._tip.attributes('-topmost', True)
        tk.Label(self._tip, text=self._text,
                 bg='#333333', fg='#EEEEEE',
                 font=('微软雅黑', 9),
                 padx=6, pady=3, relief=tk.FLAT).pack()
        self._tip.geometry(f'+{x}+{y}')

    def _hide(self):
        if self._tip:
            try:
                self._tip.destroy()
            except Exception:
                pass
            self._tip = None


class AnnotationMixin:
    """
    标注工具逻辑 Mixin。
    使用方需提供：
      self.root, self._win, self._canvas
      self._image (PIL Image，局部截图)
      self._display_scale, self._display_w, self._display_h
    """

    def _init_annotation_state(self):
        self._annotations      = []
        self._active_entry     = None
        self._active_entry_pos = None
        self._shape_start      = None
        self._shape_preview_id = None
        self._tool      = 'move'
        self._color     = '#FF3B30'
        self._font_size = 18
        self._tk_image  = None
        self._tool_btns  = {}
        self._color_btns = {}
        self._size_var   = None
        self._color_dot  = None
        self._toolbar_win  = None
        self._style_row    = None
        self._pinned       = False
        # 拖动状态
        self._drag_start_x = 0
        self._drag_start_y = 0
        self._drag_win_x   = 0
        self._drag_win_y   = 0
        self._is_dragging  = False
        self._press_moved  = False

    # ── 浮动工具栏 ──

    def _build_floating_toolbar(self):
        tb = tk.Toplevel(self.root)
        self._toolbar_win = tb
        tb.overrideredirect(True)
        tb.attributes('-topmost', True)
        tb.configure(bg='#4A4A4A')
        tb.wm_transient(self._win)
        self._build_toolbar(tb)
        tb.update_idletasks()
        self._reposition_toolbar()

    def _reposition_toolbar(self):
        if not self._toolbar_win:
            return
        try:
            win_x = self._win.winfo_x()
            win_y = self._win.winfo_y()
            tb_w  = self._toolbar_win.winfo_reqwidth()
            tb_h  = self._toolbar_win.winfo_reqheight()
            if tb_w < 10:
                tb_w = 400
            if tb_h < 10:
                tb_h = 40
            tb_x = win_x + (self._display_w - tb_w) // 2
            tb_y = win_y + self._display_h + TOOLBAR_GAP
            tb_x = max(0, tb_x)
            self._toolbar_win.geometry(f'{tb_w}x{tb_h}+{tb_x}+{tb_y}')
        except Exception:
            pass

    def _build_toolbar(self, parent):
        row1 = tk.Frame(parent, bg='#4A4A4A')
        row1.pack(side=tk.TOP)

        def icon_btn(p, icon, tooltip, cmd, fg='white', bg='#5A5A5A',
                     active_bg='#707070', active_fg='white'):
            b = tk.Button(p, text=icon, bg=bg, fg=fg,
                          activebackground=active_bg, activeforeground=active_fg,
                          font=('Segoe UI Emoji', 13),
                          relief=tk.FLAT, bd=0, padx=8, pady=4,
                          cursor='hand2', command=cmd)
            _Tooltip(b, tooltip)
            return b

        tools = [
            ('move',   '✥', '移动'),
            ('text',   'T',  '文字'),
            ('arrow',  '→', '箭头'),
            ('rect',   '□', '矩形'),
            ('mosaic', '▦', '马赛克'),
        ]
        for name, icon, tip in tools:
            btn = icon_btn(row1, icon, tip, lambda n=name: self._set_tool(n))
            btn.pack(side=tk.LEFT, padx=2, pady=3)
            self._tool_btns[name] = btn

        tk.Frame(row1, bg='#666666', width=1).pack(side=tk.LEFT, fill=tk.Y, padx=6, pady=4)

        btn_undo = icon_btn(row1, '↩', '撤销 (Ctrl+Z)', self._undo, fg='#CCCCCC')
        btn_undo.pack(side=tk.LEFT, padx=2, pady=3)

        # 右侧按钮
        btn_close = icon_btn(row1, '✕', '关闭', self._on_close,
                             fg='#CCCCCC', bg='#4A4A4A',
                             active_bg='#C0392B', active_fg='white')
        btn_close.pack(side=tk.RIGHT, padx=(2, 6), pady=3)

        btn_copy = icon_btn(row1, '✓', '复制并关闭 (Ctrl+C)',
                            self._copy_to_clipboard,
                            fg='#30D158', bg='#5A5A5A',
                            active_bg='#444444', active_fg='#30D158')
        btn_copy.pack(side=tk.RIGHT, padx=2, pady=3)

        btn_save = icon_btn(row1, '💾', '保存 (Ctrl+S)',
                            self._save,
                            fg='black', bg='#30D158',
                            active_bg='#25A244', active_fg='black')
        btn_save.pack(side=tk.RIGHT, padx=2, pady=3)

        btn_pin = icon_btn(row1, '📌', '贴到屏幕',
                           self._enter_pin_mode)
        btn_pin.pack(side=tk.RIGHT, padx=(2, 4), pady=3)

        # 颜色/字号行（默认隐藏）
        self._style_row = tk.Frame(parent, bg='#404040')

        tk.Frame(self._style_row, bg='#606060', height=1).pack(fill=tk.X)
        row2 = tk.Frame(self._style_row, bg='#404040')
        row2.pack(side=tk.TOP)

        for hc in PRESET_COLORS:
            btn = tk.Button(row2, bg=hc, activebackground=hc,
                            width=2, height=1, relief=tk.FLAT, cursor='hand2', bd=0,
                            command=lambda c=hc: self._set_color(c))
            btn.pack(side=tk.LEFT, padx=2, pady=4)
            self._color_btns[hc] = btn

        self._color_dot = tk.Label(row2, bg=self._color, width=3, bd=1, relief=tk.SUNKEN)
        self._color_dot.pack(side=tk.LEFT, padx=(6, 2), pady=6)

        tk.Frame(row2, bg='#606060', width=1).pack(side=tk.LEFT, padx=8, fill=tk.Y, pady=4)
        tk.Label(row2, text='字号', bg='#404040', fg='#BBBBBB',
                 font=('微软雅黑', 8)).pack(side=tk.LEFT, padx=(0, 2))
        self._size_var = tk.StringVar(value=str(self._font_size))
        spin = tk.Spinbox(row2, from_=8, to=72, textvariable=self._size_var,
                          width=3, font=('微软雅黑', 10),
                          bg='#5A5A5A', fg='white', buttonbackground='#5A5A5A',
                          relief=tk.FLAT, bd=1, command=self._on_size_change)
        spin.pack(side=tk.LEFT, padx=(0, 4), pady=4)
        spin.bind('<Return>', lambda e: self._on_size_change())

        self._update_tool_highlight()
        self._update_color_highlight()

    # ── 工具 & 颜色 ──

    def _set_tool(self, tool):
        if self._active_entry:
            self._commit_entry()
        self._tool = tool
        self._update_tool_highlight()
        cursors = {'move': 'fleur', 'text': 'xterm',
                   'arrow': 'crosshair', 'rect': 'crosshair', 'mosaic': 'crosshair'}
        self._canvas.config(cursor=cursors.get(tool, 'arrow'))
        if tool in ('text', 'arrow', 'rect'):
            self._style_row.pack(side=tk.TOP)
        else:
            self._style_row.pack_forget()
        if self._toolbar_win:
            self._toolbar_win.update_idletasks()
            self._reposition_toolbar()
        self._win.focus_force()

    def _update_tool_highlight(self):
        for name, btn in self._tool_btns.items():
            btn.config(bg='#0A84FF' if name == self._tool else '#5A5A5A')

    def _set_color(self, color):
        self._color = color
        if self._color_dot:
            self._color_dot.config(bg=color)
        self._update_color_highlight()
        self._win.focus_force()

    def _update_color_highlight(self):
        for hc, btn in self._color_btns.items():
            btn.config(relief=tk.SUNKEN if hc == self._color else tk.FLAT,
                       bd=2 if hc == self._color else 0)

    def _on_size_change(self):
        try:
            self._font_size = max(8, min(72, int(self._size_var.get())))
        except ValueError:
            pass

    # ── 撤销 ──

    def _undo(self):
        if self._active_entry:
            self._cancel_entry()
            return
        if not self._annotations:
            return
        last = self._annotations.pop()
        if last['type'] == 'mosaic_snapshot':
            self._image = last['image']
        self._refresh_canvas_image()

    # ── 鼠标事件 ──

    def _on_press(self, event):
        self._drag_start_x = event.x_root
        self._drag_start_y = event.y_root
        self._drag_win_x   = self._win.winfo_x()
        self._drag_win_y   = self._win.winfo_y()
        self._is_dragging  = False
        self._press_moved  = False

        if self._tool in ('arrow', 'rect', 'mosaic'):
            if self._active_entry:
                self._commit_entry()
            self._shape_start = (self._canvas.canvasx(event.x),
                                 self._canvas.canvasy(event.y))

    def _on_drag(self, event):
        dx = event.x_root - self._drag_start_x
        dy = event.y_root - self._drag_start_y

        if self._tool == 'move':
            if not self._is_dragging:
                if abs(dx) > DRAG_THR or abs(dy) > DRAG_THR:
                    self._is_dragging = True
                    if self._toolbar_win and not self._pinned:
                        self._toolbar_win.withdraw()
            if self._is_dragging:
                self._press_moved = True
                self._win.geometry(f'+{self._drag_win_x + dx}+{self._drag_win_y + dy}')

        elif self._tool == 'arrow' and self._shape_start:
            cx, cy = self._canvas.canvasx(event.x), self._canvas.canvasy(event.y)
            if self._shape_preview_id:
                self._canvas.delete(self._shape_preview_id)
            lw = max(2, int(self._font_size * self._display_scale / 10))
            self._shape_preview_id = self._canvas.create_line(
                self._shape_start[0], self._shape_start[1], cx, cy,
                fill=self._color, width=lw, arrow=tk.LAST, arrowshape=(12, 15, 5))

        elif self._tool == 'rect' and self._shape_start:
            cx, cy = self._canvas.canvasx(event.x), self._canvas.canvasy(event.y)
            if self._shape_preview_id:
                self._canvas.delete(self._shape_preview_id)
            lw = max(2, int(self._font_size * self._display_scale / 10))
            self._shape_preview_id = self._canvas.create_rectangle(
                self._shape_start[0], self._shape_start[1], cx, cy,
                outline=self._color, width=lw, fill='')

        elif self._tool == 'mosaic' and self._shape_start:
            cx, cy = self._canvas.canvasx(event.x), self._canvas.canvasy(event.y)
            if self._shape_preview_id:
                self._canvas.delete(self._shape_preview_id)
            self._shape_preview_id = self._canvas.create_rectangle(
                self._shape_start[0], self._shape_start[1], cx, cy,
                outline='#FFFFFF', width=1, fill='', dash=(4, 4))

    def _on_release(self, event):
        if self._tool == 'move':
            if self._is_dragging:
                if self._toolbar_win and not self._pinned:
                    self._reposition_toolbar()
                    self._toolbar_win.deiconify()
            elif not self._press_moved and self._active_entry:
                self._commit_entry()
            self._is_dragging = False

        elif self._tool == 'text':
            dx = abs(event.x_root - self._drag_start_x)
            dy = abs(event.y_root - self._drag_start_y)
            if dx < DRAG_THR and dy < DRAG_THR:
                if self._active_entry:
                    self._commit_entry()
                self._show_entry(self._canvas.canvasx(event.x),
                                 self._canvas.canvasy(event.y))

        elif self._tool == 'arrow' and self._shape_start:
            cx, cy = self._canvas.canvasx(event.x), self._canvas.canvasy(event.y)
            sx, sy = self._shape_start
            self._shape_start = None
            if self._shape_preview_id:
                self._canvas.delete(self._shape_preview_id)
                self._shape_preview_id = None
            if abs(cx - sx) < 5 and abs(cy - sy) < 5:
                return
            self._annotations.append({
                'type': 'arrow',
                'x1': sx / self._display_scale, 'y1': sy / self._display_scale,
                'x2': cx / self._display_scale, 'y2': cy / self._display_scale,
                'color': self._color, 'size': self._font_size,
            })
            self._refresh_canvas_image()

        elif self._tool == 'rect' and self._shape_start:
            cx, cy = self._canvas.canvasx(event.x), self._canvas.canvasy(event.y)
            sx, sy = self._shape_start
            self._shape_start = None
            if self._shape_preview_id:
                self._canvas.delete(self._shape_preview_id)
                self._shape_preview_id = None
            if abs(cx - sx) < 5 and abs(cy - sy) < 5:
                return
            self._annotations.append({
                'type': 'rect',
                'x1': min(sx, cx) / self._display_scale,
                'y1': min(sy, cy) / self._display_scale,
                'x2': max(sx, cx) / self._display_scale,
                'y2': max(sy, cy) / self._display_scale,
                'color': self._color, 'size': self._font_size,
            })
            self._refresh_canvas_image()

        elif self._tool == 'mosaic' and self._shape_start:
            cx, cy = self._canvas.canvasx(event.x), self._canvas.canvasy(event.y)
            sx, sy = self._shape_start
            self._shape_start = None
            if self._shape_preview_id:
                self._canvas.delete(self._shape_preview_id)
                self._shape_preview_id = None
            if abs(cx - sx) < 5 and abs(cy - sy) < 5:
                return
            self._annotations.append({
                'type': 'mosaic_snapshot',
                'image': self._image.copy(),
            })
            self._apply_mosaic(
                min(sx, cx) / self._display_scale,
                min(sy, cy) / self._display_scale,
                max(sx, cx) / self._display_scale,
                max(sy, cy) / self._display_scale,
            )
            self._refresh_canvas_image()

    # ── 马赛克 ──

    def _apply_mosaic(self, x1, y1, x2, y2):
        x1 = max(0, int(x1))
        y1 = max(0, int(y1))
        x2 = min(self._image.width,  int(x2))
        y2 = min(self._image.height, int(y2))
        if x2 <= x1 or y2 <= y1:
            return
        region = self._image.crop((x1, y1, x2, y2))
        w, h = region.size
        mosaic = region.resize((max(1, w // 10), max(1, h // 10)), Image.NEAREST
                               ).resize((w, h), Image.NEAREST)
        self._image.paste(mosaic, (x1, y1))

    # ── 文字输入 ──

    def _show_entry(self, canvas_x, canvas_y):
        font_size_display = max(8, int(self._font_size * self._display_scale))
        try:
            px = max(0, min(int(canvas_x / self._display_scale), self._image.width  - 1))
            py = max(0, min(int(canvas_y / self._display_scale), self._image.height - 1))
            r, g, b = self._image.convert('RGB').getpixel((px, py))
            bg_color = f'#{r:02x}{g:02x}{b:02x}'
        except Exception:
            r, g, b = 255, 255, 255
            bg_color = '#ffffff'

        luminance    = 0.299 * r + 0.587 * g + 0.114 * b
        cursor_color = '#000000' if luminance > 128 else '#ffffff'

        entry = tk.Entry(self._canvas,
                         font=('微软雅黑', font_size_display),
                         fg=self._color, bg=bg_color,
                         insertbackground=cursor_color,
                         selectbackground='#4466AA',
                         relief=tk.FLAT, bd=0, highlightthickness=0, width=20)
        entry_win = self._canvas.create_window(
            int(canvas_x), int(canvas_y), window=entry, anchor='nw', tags='entry_window')
        entry.focus_set()
        entry.bind('<Return>',   lambda e: self._commit_entry())
        entry.bind('<Tab>',      lambda e: self._commit_entry())
        entry.bind('<FocusOut>', lambda e: self.root.after(80, self._commit_if_active))
        entry.bind('<Escape>',   lambda e: self._cancel_entry())
        self._active_entry     = entry
        self._active_entry_win = entry_win
        self._active_entry_pos = (canvas_x / self._display_scale,
                                  canvas_y / self._display_scale)

    def _commit_if_active(self):
        if self._active_entry:
            self._commit_entry()

    def _cancel_entry(self):
        if not self._active_entry:
            return
        self._canvas.delete('entry_window')
        try:
            self._active_entry.destroy()
        except Exception:
            pass
        self._active_entry = None

    def _commit_entry(self):
        if not self._active_entry:
            return
        text = self._active_entry.get().strip()
        x, y = self._active_entry_pos
        self._canvas.delete('entry_window')
        try:
            self._active_entry.destroy()
        except Exception:
            pass
        self._active_entry = None
        if not text:
            return
        self._annotations.append({
            'type': 'text', 'x': x, 'y': y,
            'text': text, 'color': self._color, 'size': self._font_size,
        })
        self._refresh_canvas_image()

    # ── 渲染 ──

    def _refresh_canvas_image(self):
        composed    = self._compose()
        display_img = composed.resize((self._display_w, self._display_h), Image.LANCZOS)
        self._tk_image = ImageTk.PhotoImage(display_img)
        self._canvas.delete('bg_img')
        self._canvas.create_image(0, 0, anchor='nw',
                                  image=self._tk_image, tags='bg_img')
        self._canvas.tag_lower('bg_img')

    def _compose(self):
        img  = self._image.copy().convert('RGBA')
        draw = ImageDraw.Draw(img)
        for ann in self._annotations:
            t = ann['type']
            if t == 'text':
                draw.text((ann['x'], ann['y']), ann['text'],
                          fill=ann['color'], font=_find_font(ann['size']))
            elif t == 'arrow':
                lw = max(2, ann['size'] // 8)
                draw.line([(ann['x1'], ann['y1']), (ann['x2'], ann['y2'])],
                          fill=ann['color'], width=lw)
                _draw_arrowhead(draw, ann['x1'], ann['y1'],
                                ann['x2'], ann['y2'], ann['color'], lw)
            elif t == 'rect':
                lw = max(2, ann['size'] // 8)
                draw.rectangle([(ann['x1'], ann['y1']), (ann['x2'], ann['y2'])],
                                outline=ann['color'], width=lw)
        return img.convert('RGB')

    # ── ESC / 关闭 ──

    def _on_escape(self):
        if self._active_entry:
            self._cancel_entry()
        else:
            self._on_close()

    def _on_close(self):
        if self._active_entry:
            self._cancel_entry()
        try:
            if self._toolbar_win:
                self._toolbar_win.destroy()
                self._toolbar_win = None
        except Exception:
            pass
        try:
            self._win.destroy()
        except Exception:
            pass

    # ── 贴图模式 ──

    def _enter_pin_mode(self):
        self._pinned = True
        if self._toolbar_win:
            try:
                self._toolbar_win.destroy()
            except Exception:
                pass
            self._toolbar_win = None
        self._win.configure(bg='#1A0A00')
        self._canvas.config(highlightthickness=3, highlightbackground='#FF8C00')
        self._canvas.unbind('<ButtonPress-1>')
        self._canvas.unbind('<B1-Motion>')
        self._canvas.unbind('<ButtonRelease-1>')
        self._canvas.unbind('<Double-Button-1>')
        self._canvas.bind('<ButtonPress-1>',   self._pin_on_press)
        self._canvas.bind('<B1-Motion>',       self._pin_on_drag)
        self._canvas.bind('<ButtonRelease-1>', self._pin_on_release)
        self._canvas.bind('<Double-Button-1>', lambda e: self._on_close())
        self._canvas.bind('<Button-3>',        lambda e: self._on_close())

    def _pin_on_press(self, event):
        self._drag_start_x = event.x_root
        self._drag_start_y = event.y_root
        self._drag_win_x   = self._win.winfo_x()
        self._drag_win_y   = self._win.winfo_y()

    def _pin_on_drag(self, event):
        dx = event.x_root - self._drag_start_x
        dy = event.y_root - self._drag_start_y
        self._win.geometry(f'+{self._drag_win_x + dx}+{self._drag_win_y + dy}')

    def _pin_on_release(self, event):
        pass

    # ── 保存 & 复制 ──

    def _save(self):
        if self._active_entry:
            self._commit_entry()
        timestamp    = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        default_name = f'screenshot_{timestamp}.png'
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
            candidate = os.path.join(os.path.expanduser('~'), 'Desktop')
            if os.path.isdir(candidate):
                desktop = candidate
        path = filedialog.asksaveasfilename(
            parent=self._win, initialdir=desktop,
            initialfile=default_name, defaultextension='.png',
            filetypes=[('PNG 图片', '*.png'), ('所有文件', '*.*')])
        if not path:
            return
        try:
            self._compose().save(path, 'PNG')
            messagebox.showinfo('保存成功', f'已保存到：\n{path}', parent=self._win)
        except Exception as e:
            logging.error(f'保存失败: {e}')
            messagebox.showerror('保存失败', str(e), parent=self._win)

    def _copy_to_clipboard(self):
        if self._active_entry:
            self._commit_entry()
        try:
            import win32clipboard
            import win32con
            img = self._compose().convert('RGB')
            buf = io.BytesIO()
            img.save(buf, format='BMP')
            dib_data = buf.getvalue()[14:]
            win32clipboard.OpenClipboard()
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32con.CF_DIB, dib_data)
            win32clipboard.CloseClipboard()
            self._on_close()
        except Exception as e:
            logging.error(f'复制到剪贴板失败: {e}')
            messagebox.showerror('复制失败',
                                 f'复制失败，请使用保存功能。\n{e}', parent=self._win)
