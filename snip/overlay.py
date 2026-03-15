"""
全屏遮罩 + 选区 + 原地编辑

流程：
  1. 拖拽绘制选区
  2. 松手 → 直接进入编辑模式：
     - 选区外继续显示暗色遮罩
     - 工具栏浮动窗口贴在选区正下方
     - 标注直接画在 overlay canvas 上
     - 选区边框变蓝，8个控制点可调整
     - 拖动选区/控制点时工具栏隐藏
  3. 点击选区外 → 重新绘制
  4. 复制/保存/关闭 → overlay 消失
  5. 贴图 → 把选区内容截出来，弹独立浮动窗口，overlay 消失
"""

import ctypes
import io
import os
import math
import logging
import datetime
import tkinter as tk
from tkinter import filedialog, messagebox
from PIL import Image, ImageTk, ImageGrab, ImageEnhance, ImageDraw, ImageFont

try:
    import winreg
    _WINREG_OK = True
except ImportError:
    _WINREG_OK = False

try:
    import win32clipboard
    import win32con
    _WIN32_OK = True
except ImportError:
    _WIN32_OK = False


# ── 常量 ──────────────────────────────────────────

HANDLES     = ['nw', 'n', 'ne', 'e', 'se', 's', 'sw', 'w']
HANDLE_SIZE = 6
MIN_SIZE    = 5
DIM_FACTOR  = 0.45
TOOLBAR_GAP = 8
PRESET_COLORS = [
    '#FF3B30', '#FF9500', '#FFCC00', '#34C759',
    '#007AFF', '#AF52DE', '#FFFFFF', '#000000',
]

WINDOWS_FONTS = [
    'C:/Windows/Fonts/msyh.ttc',
    'C:/Windows/Fonts/msyhbd.ttc',
    'C:/Windows/Fonts/simhei.ttf',
    'C:/Windows/Fonts/arial.ttf',
]


def _get_virtual_screen():
    try:
        u = ctypes.windll.user32
        x, y = u.GetSystemMetrics(76), u.GetSystemMetrics(77)
        w, h = u.GetSystemMetrics(78), u.GetSystemMetrics(79)
        if w > 0 and h > 0:
            return x, y, w, h
    except Exception:
        pass
    try:
        u = ctypes.windll.user32
        w, h = u.GetSystemMetrics(0), u.GetSystemMetrics(1)
        if w > 0 and h > 0:
            return 0, 0, w, h
    except Exception:
        pass
    return 0, 0, 1920, 1080


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
    l, r = rot(ux, uy, -angle), rot(ux, uy, angle)
    draw.polygon([
        (x2, y2),
        (x2 + l[0]*length, y2 + l[1]*length),
        (x2 + r[0]*length, y2 + r[1]*length),
    ], fill=color)


# ── Tooltip ───────────────────────────────────────

class _Tooltip:
    def __init__(self, widget, text):
        self._widget, self._text = widget, text
        self._tip = self._after_id = None
        widget.bind('<Enter>', lambda e: self._schedule())
        widget.bind('<Leave>', lambda e: self._cancel())

    def _schedule(self):
        self._after_id = self._widget.after(500, self._show)

    def _cancel(self):
        if self._after_id:
            self._widget.after_cancel(self._after_id)
            self._after_id = None
        if self._tip:
            try: self._tip.destroy()
            except Exception: pass
            self._tip = None

    def _show(self):
        x = self._widget.winfo_rootx() + self._widget.winfo_width() // 2
        y = self._widget.winfo_rooty() + self._widget.winfo_height() + 4
        self._tip = tk.Toplevel(self._widget)
        self._tip.overrideredirect(True)
        self._tip.attributes('-topmost', True)
        tk.Label(self._tip, text=self._text, bg='#333333', fg='#EEEEEE',
                 font=('微软雅黑', 9), padx=6, pady=3).pack()
        self._tip.geometry(f'+{x}+{y}')


# ── 贴图独立窗口 ───────────────────────────────────

class _PinWindow:
    """把截图贴到屏幕，独立浮动，橙色边框，双击/右键关闭"""
    def __init__(self, root, image: Image.Image, screen_x, screen_y):
        self._image = image
        self._root  = root
        win = tk.Toplevel(root)
        self._win = win
        win.overrideredirect(True)
        win.attributes('-topmost', True)
        win.configure(bg='#1A0A00')
        iw, ih = image.size

        BORDER = 3
        canvas = tk.Canvas(win, width=iw, height=ih,
                           highlightthickness=BORDER, highlightbackground='#FF8C00',
                           bd=0)
        canvas.pack()
        # 窗口尺寸要加上两侧边框，否则图片会被裁剪
        win.geometry(f'{iw + BORDER*2}x{ih + BORDER*2}+{screen_x}+{screen_y}')
        self._tk_img = ImageTk.PhotoImage(image)
        canvas.create_image(0, 0, anchor='nw', image=self._tk_img)

        self._drag_x = self._drag_y = 0
        self._win_x  = self._win_y  = 0

        canvas.bind('<ButtonPress-1>',   self._on_press)
        canvas.bind('<B1-Motion>',       self._on_drag)
        canvas.bind('<Double-Button-1>', lambda e: self._close())
        canvas.bind('<Button-3>',        lambda e: self._close())

        win.lift()

    def _close(self):
        try: self._win.destroy()
        except Exception: pass
        # 从 root._pin_windows 移除自身，让 GC 正常回收
        if hasattr(self._root, '_pin_windows'):
            try: self._root._pin_windows.remove(self)
            except ValueError: pass

    def _on_press(self, event):
        self._drag_x = event.x_root
        self._drag_y = event.y_root
        self._win_x  = event.widget.winfo_toplevel().winfo_x()
        self._win_y  = event.widget.winfo_toplevel().winfo_y()

    def _on_drag(self, event):
        dx = event.x_root - self._drag_x
        dy = event.y_root - self._drag_y
        w  = event.widget.winfo_toplevel()
        w.geometry(f'+{self._win_x + dx}+{self._win_y + dy}')


# ── 主类 ──────────────────────────────────────────

class OverlayWindow:
    RECT_COLOR = '#1890FF'
    RECT_WIDTH = 2

    def __init__(self, root, on_done):
        self.root     = root
        self._on_done = on_done   # 完成或取消都调用，重置 _snipping

        # 截图数据
        self._full_img = None   # 原始截图（全虚拟屏幕）
        self._dim_img  = None   # 变暗版
        self._vx = self._vy = self._vw = self._vh = 0

        # 选区坐标（overlay canvas 坐标系）
        self._rx1 = self._ry1 = self._rx2 = self._ry2 = 0

        # 阶段标志
        self._phase = 'draw'   # 'draw' | 'edit'

        # 拖拽绘制
        self._draw_start_x = self._draw_start_y = 0
        self._drawing = False

        # 选区调整
        self._adj_mode      = None
        self._adj_start_x   = self._adj_start_y = 0
        self._adj_orig_rect = None

        # 标注
        self._annotations      = []
        self._active_entry     = None
        self._active_entry_win = None
        self._active_entry_pos = None
        self._shape_start      = None
        self._shape_preview_id = None

        # 工具状态
        self._tool      = 'move'
        self._color     = '#FF3B30'
        self._font_size = 18

        # 工具栏
        self._toolbar_win = None
        self._style_row   = None
        self._tool_btns   = {}
        self._color_btns  = {}
        self._size_var    = None
        self._color_dot   = None

        # canvas items
        self._id_bright = None
        self._id_dim_top = self._id_dim_bottom = None
        self._id_dim_left = self._id_dim_right = None
        self._tk_bright = None
        self._tk_dim_top = self._tk_dim_bottom = None
        self._tk_dim_left = self._tk_dim_right = None
        self._id_rect    = None
        self._id_info    = None
        self._handle_ids = {}

        self._window = self._canvas = None

    # ── 启动 ──────────────────────────────────────

    def show(self):
        try:
            try:
                raw = ImageGrab.grab(all_screens=True)
            except TypeError:
                raw = ImageGrab.grab()
        except Exception as e:
            logging.error(f'截图失败: {e}')
            messagebox.showerror('截图失败', f'无法截取屏幕，请重试。\n{e}')
            if self._on_done:
                self._on_done()
            return

        vx, vy, vw, vh = _get_virtual_screen()
        self._vx, self._vy, self._vw, self._vh = vx, vy, vw, vh
        self._full_img = raw.resize((vw, vh), Image.LANCZOS)
        self._dim_img  = ImageEnhance.Brightness(self._full_img).enhance(DIM_FACTOR)
        self._build_window()

    def _build_window(self):
        vw, vh = self._vw, self._vh

        win = tk.Toplevel(self.root)
        self._window = win
        win.overrideredirect(True)
        win.attributes('-topmost', True)
        win.geometry(f'{vw}x{vh}+{self._vx}+{self._vy}')

        canvas = tk.Canvas(win, width=vw, height=vh,
                           cursor='crosshair', highlightthickness=0, bd=0)
        canvas.pack(fill=tk.BOTH, expand=True)
        self._canvas = canvas

        # 亮图（底层）
        self._tk_bright = ImageTk.PhotoImage(self._full_img)
        self._id_bright = canvas.create_image(0, 0, anchor='nw', image=self._tk_bright)

        # 四块暗图
        self._tk_dim_top    = ImageTk.PhotoImage(self._dim_img)
        self._tk_dim_bottom = ImageTk.PhotoImage(Image.new('RGB', (1, 1)))
        self._tk_dim_left   = ImageTk.PhotoImage(Image.new('RGB', (1, 1)))
        self._tk_dim_right  = ImageTk.PhotoImage(Image.new('RGB', (1, 1)))
        self._id_dim_top    = canvas.create_image(0, 0, anchor='nw', image=self._tk_dim_top)
        self._id_dim_bottom = canvas.create_image(0, 0, anchor='nw', image=self._tk_dim_bottom)
        self._id_dim_left   = canvas.create_image(0, 0, anchor='nw', image=self._tk_dim_left)
        self._id_dim_right  = canvas.create_image(0, 0, anchor='nw', image=self._tk_dim_right)

        # 提示文字
        canvas.create_text(vw // 2, 28,
                           text='拖拽选择区域    ESC 取消',
                           fill='white', font=('微软雅黑', 11), tags='hint')

        # 选框
        self._id_rect = canvas.create_rectangle(
            0, 0, 0, 0, outline='#000000', width=self.RECT_WIDTH, fill='')
        self._id_info = canvas.create_text(
            0, 0, text='', fill='white', font=('微软雅黑', 9), anchor='sw')

        # 控制点
        for h in HANDLES:
            self._handle_ids[h] = canvas.create_rectangle(
                0, 0, 0, 0, fill='white', outline=self.RECT_COLOR,
                width=1, state='hidden', tags='handle')

        # 绑定阶段一事件
        self._bind_draw_events()
        win.bind('<Escape>', lambda e: self._cancel())
        canvas.bind('<Button-3>', lambda e: self._cancel())
        win.focus_force()

    # ── 遮罩更新 ──────────────────────────────────

    def _update_masks(self, x1, y1, x2, y2):
        vw, vh, dim, c = self._vw, self._vh, self._dim_img, self._canvas

        def upd(iid, attr, rx1, ry1, rx2, ry2, px, py):
            img = ImageTk.PhotoImage(
                dim.crop((rx1, ry1, rx1 + max(1, rx2-rx1), ry1 + max(1, ry2-ry1))))
            setattr(self, attr, img)
            c.itemconfig(iid, image=img)
            c.coords(iid, px, py)

        if y1 > 0:   upd(self._id_dim_top,    '_tk_dim_top',    0,  0,  vw, y1, 0,  0)
        else:        c.itemconfig(self._id_dim_top,    image='')
        if y2 < vh:  upd(self._id_dim_bottom, '_tk_dim_bottom', 0,  y2, vw, vh, 0,  y2)
        else:        c.itemconfig(self._id_dim_bottom, image='')
        if x1 > 0 and y2 > y1:
                     upd(self._id_dim_left,   '_tk_dim_left',   0,  y1, x1, y2, 0,  y1)
        else:        c.itemconfig(self._id_dim_left,   image='')
        if x2 < vw and y2 > y1:
                     upd(self._id_dim_right,  '_tk_dim_right',  x2, y1, vw, y2, x2, y1)
        else:        c.itemconfig(self._id_dim_right,  image='')

        c.coords(self._id_rect, x1, y1, x2, y2)
        ty = max(y1 - 4, 14)
        c.coords(self._id_info, x1, ty)
        c.itemconfig(self._id_info, text=f' {x2-x1} × {y2-y1} ')

    def _update_handles(self, x1, y1, x2, y2):
        mx, my = (x1+x2)//2, (y1+y2)//2
        s = HANDLE_SIZE
        pos = {'nw':(x1,y1),'n':(mx,y1),'ne':(x2,y1),'e':(x2,my),
               'se':(x2,y2),'s':(mx,y2),'sw':(x1,y2),'w':(x1,my)}
        for h, (cx, cy) in pos.items():
            self._canvas.coords(self._handle_ids[h], cx-s, cy-s, cx+s, cy+s)
            self._canvas.itemconfig(self._handle_ids[h], state='normal')

    def _hide_handles(self):
        for item in self._handle_ids.values():
            self._canvas.itemconfig(item, state='hidden')

    # ── 阶段一：拖拽绘制 ──────────────────────────

    def _bind_draw_events(self):
        c = self._canvas
        c.bind('<ButtonPress-1>',   self._draw_press)
        c.bind('<B1-Motion>',       self._draw_drag)
        c.bind('<ButtonRelease-1>', self._draw_release)

    def _draw_press(self, event):
        self._draw_start_x = event.x
        self._draw_start_y = event.y
        self._drawing = True
        self._canvas.itemconfig('hint', state='hidden')

    def _draw_drag(self, event):
        if not self._drawing:
            return
        x1, y1 = min(self._draw_start_x, event.x), min(self._draw_start_y, event.y)
        x2, y2 = max(self._draw_start_x, event.x), max(self._draw_start_y, event.y)
        self._update_masks(x1, y1, x2, y2)

    def _draw_release(self, event):
        if not self._drawing:
            return
        self._drawing = False
        x1, y1 = min(self._draw_start_x, event.x), min(self._draw_start_y, event.y)
        x2, y2 = max(self._draw_start_x, event.x), max(self._draw_start_y, event.y)
        if (x2-x1) < MIN_SIZE or (y2-y1) < MIN_SIZE:
            self._cancel()
            return
        self._rx1, self._ry1, self._rx2, self._ry2 = x1, y1, x2, y2
        self._enter_edit_phase()

    # ── 进入编辑阶段 ──────────────────────────────

    def _enter_edit_phase(self):
        self._phase = 'edit'
        self._annotations = []

        # 选框变蓝，控制点显示
        self._canvas.itemconfig(self._id_rect, outline=self.RECT_COLOR)
        self._update_handles(self._rx1, self._ry1, self._rx2, self._ry2)

        # 绑定编辑阶段鼠标事件
        c = self._canvas
        c.unbind('<ButtonPress-1>')
        c.unbind('<B1-Motion>')
        c.unbind('<ButtonRelease-1>')
        c.bind('<ButtonPress-1>',   self._edit_press)
        c.bind('<B1-Motion>',       self._edit_drag)
        c.bind('<ButtonRelease-1>', self._edit_release)

        # 快捷键
        self._window.bind('<Control-s>', lambda e: self._save())
        self._window.bind('<Control-c>', lambda e: self._copy_to_clipboard())
        self._window.bind('<Control-z>', lambda e: self._undo())

        # 显示工具栏
        self._build_floating_toolbar()

    # ── 编辑阶段鼠标路由 ──────────────────────────

    def _edit_press(self, event):
        x, y = event.x, event.y

        # 只有在移动模式下，控制柄和选区拖动才生效
        # 其他工具（文字/箭头/矩形/马赛克）点击选区内一律走标注流程
        if self._tool == 'move':
            h = self._hit_handle(x, y)
            if h:
                self._start_adjust(h, event)
                return
            if self._hit_inside(x, y):
                self._start_adjust('move', event)
                return
            # 点击选区外：重新绘制
            self._reset_to_draw(event)
        else:
            if self._hit_inside(x, y):
                self._annotation_press(event)
            else:
                # 标注工具点击选区外：回到重新绘制
                self._reset_to_draw(event)

    def _edit_drag(self, event):
        if self._adj_mode is not None:
            self._do_adjust_drag(event)
        else:
            self._annotation_drag(event)

    def _edit_release(self, event):
        if self._adj_mode is not None:
            self._do_adjust_release(event)
        else:
            self._annotation_release(event)

    # ── 选区调整 ──────────────────────────────────

    def _start_adjust(self, mode, event):
        self._adj_mode      = mode
        self._adj_start_x   = event.x
        self._adj_start_y   = event.y
        self._adj_orig_rect = (self._rx1, self._ry1, self._rx2, self._ry2)
        # 拖动选区/控制柄时隐藏工具栏
        if self._toolbar_win:
            self._toolbar_win.withdraw()
        self._update_adj_cursor()

    def _do_adjust_drag(self, event):
        dx = event.x - self._adj_start_x
        dy = event.y - self._adj_start_y
        ox1, oy1, ox2, oy2 = self._adj_orig_rect
        vw, vh = self._vw, self._vh
        x1, y1, x2, y2 = ox1, oy1, ox2, oy2

        if self._adj_mode == 'move':
            w, h = ox2-ox1, oy2-oy1
            x1 = max(0, min(ox1+dx, vw-w))
            y1 = max(0, min(oy1+dy, vh-h))
            x2, y2 = x1+w, y1+h
        else:
            m = self._adj_mode
            if 'n' in m: y1 = max(0,  min(oy1+dy, oy2-MIN_SIZE))
            if 's' in m: y2 = min(vh, max(oy2+dy, oy1+MIN_SIZE))
            if 'w' in m: x1 = max(0,  min(ox1+dx, ox2-MIN_SIZE))
            if 'e' in m: x2 = min(vw, max(ox2+dx, ox1+MIN_SIZE))

        self._rx1, self._ry1, self._rx2, self._ry2 = x1, y1, x2, y2
        self._update_masks(x1, y1, x2, y2)
        self._update_handles(x1, y1, x2, y2)

    def _do_adjust_release(self, event):
        self._adj_mode = None
        self._canvas.config(cursor='crosshair')
        # 重置标注（选区变了，旧标注无效）
        self._annotations = []
        # 恢复工具栏
        if self._toolbar_win:
            self._reposition_toolbar()
            self._toolbar_win.deiconify()

    def _update_adj_cursor(self):
        cursors = {
            'move':'fleur',
            'nw':'size_nw_se','se':'size_nw_se',
            'ne':'size_ne_sw','sw':'size_ne_sw',
            'n':'size_ns','s':'size_ns',
            'e':'size_we','w':'size_we',
        }
        self._canvas.config(cursor=cursors.get(self._adj_mode, 'crosshair'))

    def _hit_handle(self, x, y):
        x1,y1,x2,y2 = self._rx1,self._ry1,self._rx2,self._ry2
        mx,my = (x1+x2)//2,(y1+y2)//2
        s = HANDLE_SIZE + 4
        pos = {'nw':(x1,y1),'n':(mx,y1),'ne':(x2,y1),'e':(x2,my),
               'se':(x2,y2),'s':(mx,y2),'sw':(x1,y2),'w':(x1,my)}
        for h,(cx,cy) in pos.items():
            if abs(x-cx)<=s and abs(y-cy)<=s:
                return h
        return None

    def _hit_inside(self, x, y):
        return self._rx1 < x < self._rx2 and self._ry1 < y < self._ry2

    def _reset_to_draw(self, event):
        """点击选区外，回到阶段一重新绘制"""
        self._phase = 'draw'
        self._annotations = []
        self._hide_handles()
        self._canvas.itemconfig(self._id_rect, outline='#000000')
        if self._toolbar_win:
            try: self._toolbar_win.destroy()
            except Exception: pass
            self._toolbar_win = None
        self._window.unbind('<Control-s>')
        self._window.unbind('<Control-c>')
        self._window.unbind('<Control-z>')
        self._bind_draw_events()
        self._draw_press(event)

    # ── 标注工具鼠标事件 ──────────────────────────

    def _annotation_press(self, event):
        cx = self._canvas.canvasx(event.x)
        cy = self._canvas.canvasy(event.y)
        if self._tool in ('arrow', 'rect', 'mosaic'):
            if self._active_entry:
                self._commit_entry()
            self._shape_start = (cx, cy)
        elif self._tool == 'text':
            pass  # 在 release 处理

    def _annotation_drag(self, event):
        if not self._shape_start:
            return
        cx = self._canvas.canvasx(event.x)
        cy = self._canvas.canvasy(event.y)

        if self._shape_preview_id:
            self._canvas.delete(self._shape_preview_id)

        if self._tool == 'arrow':
            lw = max(2, self._font_size // 8)
            self._shape_preview_id = self._canvas.create_line(
                self._shape_start[0], self._shape_start[1], cx, cy,
                fill=self._color, width=lw, arrow=tk.LAST, arrowshape=(12,15,5))
        elif self._tool == 'rect':
            lw = max(2, self._font_size // 8)
            self._shape_preview_id = self._canvas.create_rectangle(
                self._shape_start[0], self._shape_start[1], cx, cy,
                outline=self._color, width=lw, fill='')
        elif self._tool == 'mosaic':
            self._shape_preview_id = self._canvas.create_rectangle(
                self._shape_start[0], self._shape_start[1], cx, cy,
                outline='#FFFFFF', width=1, fill='', dash=(4,4))

    def _annotation_release(self, event):
        cx = self._canvas.canvasx(event.x)
        cy = self._canvas.canvasy(event.y)

        if self._tool == 'text':
            if self._active_entry:
                self._commit_entry()
            else:
                self._show_entry(cx, cy)
            self._ensure_toolbar_visible()
            return

        if not self._shape_start:
            return
        sx, sy = self._shape_start
        self._shape_start = None
        if self._shape_preview_id:
            self._canvas.delete(self._shape_preview_id)
            self._shape_preview_id = None
        if abs(cx-sx) < 5 and abs(cy-sy) < 5:
            self._ensure_toolbar_visible()
            return

        if self._tool == 'arrow':
            ann = {
                'type': 'arrow',
                'x1': sx, 'y1': sy, 'x2': cx, 'y2': cy,
                'color': self._color, 'size': self._font_size,
            }
            self._annotations.append(ann)
            ann['canvas_id'] = self._draw_annotation(ann)

        elif self._tool == 'rect':
            ann = {
                'type': 'rect',
                'x1': min(sx,cx), 'y1': min(sy,cy),
                'x2': max(sx,cx), 'y2': max(sy,cy),
                'color': self._color, 'size': self._font_size,
            }
            self._annotations.append(ann)
            ann['canvas_id'] = self._draw_annotation(ann)

        elif self._tool == 'mosaic':
            ann = {
                'type': 'mosaic',
                'x1': min(sx,cx), 'y1': min(sy,cy),
                'x2': max(sx,cx), 'y2': max(sy,cy),
                'snapshot': self._full_img.copy(),
            }
            self._annotations.append(ann)
            self._apply_mosaic_canvas(
                min(sx,cx), min(sy,cy), max(sx,cx), max(sy,cy))

        self._ensure_toolbar_visible()

    # ── 标注绘制（直接画在 canvas 上）────────────

    def _draw_annotation(self, ann):
        """绘制标注，返回 canvas item id"""
        t = ann['type']
        lw = max(2, ann['size'] // 8)
        if t == 'arrow':
            return self._canvas.create_line(
                ann['x1'], ann['y1'], ann['x2'], ann['y2'],
                fill=ann['color'], width=lw,
                arrow=tk.LAST, arrowshape=(12,15,5),
                tags='annotation')
        elif t == 'rect':
            return self._canvas.create_rectangle(
                ann['x1'], ann['y1'], ann['x2'], ann['y2'],
                outline=ann['color'], width=lw, fill='',
                tags='annotation')
        elif t == 'text':
            iid = self._canvas.create_text(
                ann['x'], ann['y'], text=ann['text'],
                fill=ann['color'],
                font=('微软雅黑', ann['size']),
                anchor='nw', tags='annotation')
            # 绑定拖动，让文字可以移动
            self._bind_text_drag(iid, ann)
            return iid
        return None

    def _apply_mosaic_canvas(self, x1, y1, x2, y2):
        """把选区在 full_img 上打码，然后刷新选区内的亮图"""
        rx1,ry1,rx2,ry2 = self._rx1,self._ry1,self._rx2,self._ry2
        # 坐标裁剪到选区内
        ax1 = max(int(x1), rx1)
        ay1 = max(int(y1), ry1)
        ax2 = min(int(x2), rx2)
        ay2 = min(int(y2), ry2)
        if ax2 <= ax1 or ay2 <= ay1:
            return
        region = self._full_img.crop((ax1, ay1, ax2, ay2))
        w, h = region.size
        mosaic = region.resize((max(1,w//10), max(1,h//10)), Image.NEAREST
                               ).resize((w, h), Image.NEAREST)
        self._full_img.paste(mosaic, (ax1, ay1))
        # 重新渲染选区内亮图
        self._refresh_bright_region()

    def _bind_text_drag(self, iid, ann):
        """给文字 canvas item 绑定拖动，输入完成后可移动文字位置"""
        drag = {'x': 0, 'y': 0}

        def on_press(e, item=iid):
            drag['x'] = e.x
            drag['y'] = e.y

        def on_drag(e, item=iid, a=ann):
            dx = e.x - drag['x']
            dy = e.y - drag['y']
            self._canvas.move(item, dx, dy)
            drag['x'] = e.x
            drag['y'] = e.y
            # 同步更新 annotation 坐标（供 _compose 使用）
            a['x'] += dx
            a['y'] += dy

        self._canvas.tag_bind(iid, '<ButtonPress-1>',   on_press)
        self._canvas.tag_bind(iid, '<B1-Motion>',       on_drag)

    def _refresh_bright_region(self):
        """重新生成选区内的亮图 canvas item"""
        x1,y1,x2,y2 = self._rx1,self._ry1,self._rx2,self._ry2
        region = self._full_img.crop((x1, y1, x2, y2))
        new_tk = ImageTk.PhotoImage(region)
        # 用一个专属 tag 的 canvas item 覆盖选区内
        self._canvas.delete('bright_region')
        self._canvas.create_image(x1, y1, anchor='nw', image=new_tk,
                                  tags='bright_region')
        self._tk_bright_region = new_tk  # 防 GC
        # 确保层级：暗图 < 亮图区域 < 标注 < 选框 < 控制点
        self._canvas.tag_lower('bright_region')
        self._canvas.tag_raise('bright_region', self._id_dim_right)

    # ── 撤销 ──────────────────────────────────────

    def _undo(self):
        if self._active_entry:
            self._cancel_entry()
            return
        if not self._annotations:
            return
        last = self._annotations.pop()
        if last['type'] == 'mosaic':
            # 恢复 full_img 快照，同时删除 bright_region 重绘
            self._full_img = last['snapshot']
            self._dim_img  = ImageEnhance.Brightness(self._full_img).enhance(DIM_FACTOR)
            self._canvas.delete('bright_region')
            self._update_masks(self._rx1, self._ry1, self._rx2, self._ry2)
        else:
            # 用存储的 canvas_id 精确删除
            cid = last.get('canvas_id')
            if cid:
                self._canvas.delete(cid)

    # ── 文字输入 ──────────────────────────────────

    def _show_entry(self, canvas_x, canvas_y):
        font_size = self._font_size
        try:
            px = max(0, min(int(canvas_x), self._full_img.width  - 1))
            py = max(0, min(int(canvas_y), self._full_img.height - 1))
            r, g, b = self._full_img.convert('RGB').getpixel((px, py))
            bg_color = f'#{r:02x}{g:02x}{b:02x}'
        except Exception:
            r, g, b = 255, 255, 255
            bg_color = '#ffffff'
        lum = 0.299*r + 0.587*g + 0.114*b
        cursor_color = '#000000' if lum > 128 else '#ffffff'

        entry = tk.Entry(self._canvas,
                         font=('微软雅黑', font_size),
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
        self._active_entry_pos = (canvas_x, canvas_y)

    def _commit_if_active(self):
        if self._active_entry:
            self._commit_entry()

    def _cancel_entry(self):
        if not self._active_entry:
            return
        self._canvas.delete('entry_window')
        try: self._active_entry.destroy()
        except Exception: pass
        self._active_entry = None

    def _commit_entry(self):
        if not self._active_entry:
            return
        text = self._active_entry.get().strip()
        x, y = self._active_entry_pos
        self._canvas.delete('entry_window')
        try: self._active_entry.destroy()
        except Exception: pass
        self._active_entry = None
        if not text:
            return
        ann = {'type':'text','x':x,'y':y,'text':text,
               'color':self._color,'size':self._font_size}
        self._annotations.append(ann)
        ann['canvas_id'] = self._draw_annotation(ann)

    # ── 工具栏 ────────────────────────────────────

    def _build_floating_toolbar(self):
        tb = tk.Toplevel(self.root)
        self._toolbar_win = tb
        tb.overrideredirect(True)
        tb.attributes('-topmost', True)
        tb.configure(bg='#4A4A4A')
        self._build_toolbar(tb)
        tb.update_idletasks()
        self._reposition_toolbar()

    def _ensure_toolbar_visible(self):
        """确保工具栏处于可见状态并置顶，标注操作完成后调用"""
        if not self._toolbar_win:
            return
        self._toolbar_win.deiconify()
        self._toolbar_win.lift()

    def _reposition_toolbar(self):
        if not self._toolbar_win:
            return
        try:
            tb_w = self._toolbar_win.winfo_reqwidth()
            tb_h = self._toolbar_win.winfo_reqheight()
            if tb_w < 10: tb_w = 400
            if tb_h < 10: tb_h = 40
            # 选区在屏幕上的绝对坐标
            sx = self._vx + self._rx1
            sy = self._vy + self._ry2 + TOOLBAR_GAP
            # 居中对齐选区
            sel_w = self._rx2 - self._rx1
            tb_x = sx + (sel_w - tb_w) // 2
            tb_x = max(0, tb_x)
            self._toolbar_win.geometry(f'{tb_w}x{tb_h}+{tb_x}+{sy}')
        except Exception:
            pass

    def _build_toolbar(self, parent):
        row1 = tk.Frame(parent, bg='#4A4A4A')
        row1.pack(side=tk.TOP)

        # 工具栏字体和内边距缩小到约 2/3
        BTN_FONT  = ('Segoe UI Emoji', 9)
        BTN_PADX  = 5
        BTN_PADY  = 2

        def ibtn(p, icon, tip, cmd, fg='white', bg='#5A5A5A',
                 abg='#707070', afg='white'):
            b = tk.Button(p, text=icon, bg=bg, fg=fg,
                          activebackground=abg, activeforeground=afg,
                          font=BTN_FONT,
                          relief=tk.FLAT, bd=0, padx=BTN_PADX, pady=BTN_PADY,
                          cursor='hand2', command=cmd)
            _Tooltip(b, tip)
            return b

        tools = [('move','✥','移动'), ('text','T','文字'),
                 ('arrow','→','箭头'), ('rect','□','矩形'), ('mosaic','▦','马赛克')]
        for name, icon, tip in tools:
            btn = ibtn(row1, icon, tip, lambda n=name: self._set_tool(n))
            btn.pack(side=tk.LEFT, padx=1, pady=2)
            self._tool_btns[name] = btn

        tk.Frame(row1, bg='#666666', width=1).pack(side=tk.LEFT, fill=tk.Y, padx=4, pady=3)
        ibtn(row1, '↩', '撤销 (Ctrl+Z)', self._undo,
             fg='#CCCCCC').pack(side=tk.LEFT, padx=1, pady=2)

        ibtn(row1, '✕', '关闭', self._cancel,
             fg='#CCCCCC', bg='#4A4A4A',
             abg='#C0392B', afg='white').pack(side=tk.RIGHT, padx=(1,4), pady=2)
        # 保存和复制统一：绿底黑字
        ibtn(row1, '✓', '复制并关闭 (Ctrl+C)', self._copy_to_clipboard,
             fg='black', bg='#30D158',
             abg='#25A244', afg='black').pack(side=tk.RIGHT, padx=1, pady=2)
        ibtn(row1, '💾', '保存 (Ctrl+S)', self._save,
             fg='black', bg='#30D158',
             abg='#25A244', afg='black').pack(side=tk.RIGHT, padx=1, pady=2)
        ibtn(row1, '📌', '贴到屏幕', self._pin,
             ).pack(side=tk.RIGHT, padx=(1,3), pady=2)

        # 颜色/字号行（默认隐藏）
        self._style_row = tk.Frame(parent, bg='#404040')
        tk.Frame(self._style_row, bg='#606060', height=1).pack(fill=tk.X)
        row2 = tk.Frame(self._style_row, bg='#404040')
        row2.pack()
        for hc in PRESET_COLORS:
            btn = tk.Button(row2, bg=hc, activebackground=hc,
                            width=1, height=1, relief=tk.FLAT, cursor='hand2', bd=0,
                            command=lambda c=hc: self._set_color(c))
            btn.pack(side=tk.LEFT, padx=1, pady=3)
            self._color_btns[hc] = btn
        self._color_dot = tk.Label(row2, bg=self._color, width=2, bd=1, relief=tk.SUNKEN)
        self._color_dot.pack(side=tk.LEFT, padx=(4,1), pady=4)
        tk.Frame(row2, bg='#606060', width=1).pack(side=tk.LEFT, padx=5, fill=tk.Y, pady=3)
        tk.Label(row2, text='字号', bg='#404040', fg='#BBBBBB',
                 font=('微软雅黑', 7)).pack(side=tk.LEFT, padx=(0,1))
        self._size_var = tk.StringVar(value=str(self._font_size))
        spin = tk.Spinbox(row2, from_=8, to=72, textvariable=self._size_var,
                          width=3, font=('微软雅黑', 8),
                          bg='#5A5A5A', fg='white', buttonbackground='#5A5A5A',
                          relief=tk.FLAT, bd=1, command=self._on_size_change)
        spin.pack(side=tk.LEFT, padx=(0,3), pady=3)
        spin.bind('<Return>', lambda e: self._on_size_change())

        self._update_tool_highlight()
        self._update_color_highlight()

    def _set_tool(self, tool):
        if self._active_entry:
            self._commit_entry()
        self._tool = tool
        self._update_tool_highlight()
        cursors = {'move':'fleur','text':'xterm',
                   'arrow':'crosshair','rect':'crosshair','mosaic':'crosshair'}
        self._canvas.config(cursor=cursors.get(tool, 'arrow'))
        if tool in ('text', 'arrow', 'rect'):
            self._style_row.pack(side=tk.TOP)
        else:
            self._style_row.pack_forget()
        if self._toolbar_win:
            self._toolbar_win.update_idletasks()
            self._reposition_toolbar()
            self._toolbar_win.lift()
        self._window.focus_force()

    def _update_tool_highlight(self):
        for name, btn in self._tool_btns.items():
            btn.config(bg='#0A84FF' if name == self._tool else '#5A5A5A')

    def _set_color(self, color):
        self._color = color
        if self._color_dot:
            self._color_dot.config(bg=color)
        self._update_color_highlight()
        self._window.focus_force()

    def _update_color_highlight(self):
        for hc, btn in self._color_btns.items():
            btn.config(relief=tk.SUNKEN if hc == self._color else tk.FLAT,
                       bd=2 if hc == self._color else 0)

    def _on_size_change(self):
        try:
            self._font_size = max(8, min(72, int(self._size_var.get())))
        except ValueError:
            pass

    # ── 合成最终图片 ───────────────────────────────

    def _compose(self):
        """从 full_img 裁出选区，PIL 里叠加文字/箭头/矩形标注"""
        x1,y1,x2,y2 = self._rx1,self._ry1,self._rx2,self._ry2
        img  = self._full_img.crop((x1, y1, x2, y2)).convert('RGBA')
        draw = ImageDraw.Draw(img)
        for ann in self._annotations:
            t = ann['type']
            # 标注坐标是 overlay canvas 坐标，需减去选区偏移
            if t == 'text':
                draw.text((ann['x']-x1, ann['y']-y1), ann['text'],
                          fill=ann['color'], font=_find_font(ann['size']))
            elif t == 'arrow':
                lw = max(2, ann['size']//8)
                draw.line([(ann['x1']-x1, ann['y1']-y1),
                           (ann['x2']-x1, ann['y2']-y1)],
                          fill=ann['color'], width=lw)
                _draw_arrowhead(draw,
                                ann['x1']-x1, ann['y1']-y1,
                                ann['x2']-x1, ann['y2']-y1,
                                ann['color'], lw)
            elif t == 'rect':
                lw = max(2, ann['size']//8)
                draw.rectangle([(ann['x1']-x1, ann['y1']-y1),
                                 (ann['x2']-x1, ann['y2']-y1)],
                                outline=ann['color'], width=lw)
            # mosaic 已直接改了 full_img，不需要额外处理
        return img.convert('RGB')

    # ── 保存 / 复制 / 贴图 ────────────────────────

    def _save(self):
        if self._active_entry:
            self._commit_entry()
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        desktop = os.path.expanduser('~')
        if _WINREG_OK:
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                        r'Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders') as k:
                    d = winreg.QueryValueEx(k, 'Desktop')[0]
                    if os.path.isdir(d):
                        desktop = d
            except Exception:
                pass
        if desktop == os.path.expanduser('~'):
            c = os.path.join(os.path.expanduser('~'), 'Desktop')
            if os.path.isdir(c):
                desktop = c
        path = filedialog.asksaveasfilename(
            parent=self._window, initialdir=desktop,
            initialfile=f'screenshot_{timestamp}.png',
            defaultextension='.png',
            filetypes=[('PNG 图片', '*.png'), ('所有文件', '*.*')])
        if not path:
            return
        try:
            self._compose().save(path, 'PNG')
            messagebox.showinfo('保存成功', f'已保存到：\n{path}', parent=self._window)
        except Exception as e:
            logging.error(f'保存失败: {e}')
            messagebox.showerror('保存失败', str(e), parent=self._window)

    def _copy_to_clipboard(self):
        if self._active_entry:
            self._commit_entry()
        if not _WIN32_OK:
            messagebox.showerror('复制失败', '缺少 pywin32 依赖，请重新运行 start.bat 安装。',
                                 parent=self._window)
            return
        try:
            buf = io.BytesIO()
            self._compose().convert('RGB').save(buf, format='BMP')
            win32clipboard.OpenClipboard()
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32con.CF_DIB, buf.getvalue()[14:])
            win32clipboard.CloseClipboard()
            self._finish()
        except Exception as e:
            logging.error(f'复制失败: {e}')
            messagebox.showerror('复制失败', f'复制失败，请使用保存功能。\n{e}',
                                 parent=self._window)

    def _pin(self):
        """贴图：把选区内容截出来，弹独立浮动窗口，overlay 关闭"""
        if self._active_entry:
            self._commit_entry()
        img = self._compose()
        sx  = self._vx + self._rx1
        sy  = self._vy + self._ry1
        # 必须把实例存到 root 上，防止 GC 回收导致图片消失
        if not hasattr(self.root, '_pin_windows'):
            self.root._pin_windows = []
        pin_win = _PinWindow(self.root, img, sx, sy)
        self.root._pin_windows.append(pin_win)
        self._finish()

    # ── 结束 ──────────────────────────────────────

    def _finish(self):
        self._close()
        if self._on_done:
            self._on_done()

    def _cancel(self):
        self._close()
        if self._on_done:
            self._on_done()

    def _close(self):
        if self._toolbar_win:
            try: self._toolbar_win.destroy()
            except Exception: pass
            self._toolbar_win = None
        if self._window:
            try: self._window.destroy()
            except Exception: pass
            self._window = None
        self._full_img = self._dim_img = None
        self._tk_bright = None
        self._tk_dim_top = self._tk_dim_bottom = None
        self._tk_dim_left = self._tk_dim_right = None
