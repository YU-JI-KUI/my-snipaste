"""
截图编辑窗口（独立模式，供直接调用）
标注逻辑全部来自 AnnotationMixin
"""

import tkinter as tk
from PIL import Image

from .editor_mixin import AnnotationMixin


class EditorWindow(AnnotationMixin):
    def __init__(self, root, image: Image.Image, screen_rect=None):
        self.root         = root
        self._image       = image.copy()
        self._screen_rect = screen_rect

        screen_w = root.winfo_screenwidth()
        screen_h = root.winfo_screenheight()
        img_w, img_h = image.size
        max_w = int(screen_w * 0.88)
        max_h = int(screen_h * 0.72)

        if img_w > max_w or img_h > max_h:
            scale = min(max_w / img_w, max_h / img_h)
            self._display_scale = scale
            self._display_w = int(img_w * scale)
            self._display_h = int(img_h * scale)
        else:
            self._display_scale = 1.0
            self._display_w = img_w
            self._display_h = img_h

        self._init_annotation_state()
        self._build_window()

    def _build_window(self):
        dw, dh = self._display_w, self._display_h

        win = tk.Toplevel(self.root)
        self._win = win
        win.overrideredirect(True)
        win.attributes('-topmost', True)
        win.configure(bg='#3C3C3C')

        canvas = tk.Canvas(win, width=dw, height=dh,
                           highlightthickness=2, highlightbackground='#555555',
                           bd=0, bg='#3C3C3C')
        canvas.pack()
        self._canvas = canvas

        self._refresh_canvas_image()

        canvas.bind('<ButtonPress-1>',   self._on_press)
        canvas.bind('<B1-Motion>',       self._on_drag)
        canvas.bind('<ButtonRelease-1>', self._on_release)
        canvas.bind('<Double-Button-1>', lambda e: self._on_close())

        win.bind('<Control-s>', lambda e: self._save())
        win.bind('<Control-c>', lambda e: self._copy_to_clipboard())
        win.bind('<Control-z>', lambda e: self._undo())
        win.bind('<Escape>',    lambda e: self._on_escape())

        # 定位：有选区坐标则贴到选区位置，否则居中
        if self._screen_rect:
            x, y = self._screen_rect[0], self._screen_rect[1]
        else:
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            x  = (sw - dw) // 2
            y  = max(10, (sh - dh) // 2 - 30)
        win.geometry(f'{dw}x{dh}+{x}+{y}')

        self._build_floating_toolbar()

        win.lift()
        win.focus_force()
