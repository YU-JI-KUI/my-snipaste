"""
全屏遮罩与区域选择模块

流程：
  1. 先用 Pillow 截取全屏（遮罩显示之前！）
  2. 创建全屏半透明 Toplevel 窗口
  3. 把截图贴到 Canvas 上作为背景
  4. 用户拖拽鼠标选区
  5. 释放鼠标后从截图 crop 出选区，回调给 editor

多显示器注意：
  - 副屏在左侧时虚拟屏幕起点坐标可能是负数
  - Canvas 坐标是相对窗口的，需要加上虚拟屏幕偏移才是真实屏幕坐标
"""

import ctypes
import logging
import tkinter as tk
from tkinter import messagebox
from PIL import Image, ImageTk, ImageGrab


def _get_virtual_screen_info():
    """
    获取 Windows 虚拟屏幕信息（所有显示器组成的大矩形）
    SM_XVIRTUALSCREEN=76, SM_YVIRTUALSCREEN=77, SM_CXVIRTUALSCREEN=78, SM_CYVIRTUALSCREEN=79
    """
    try:
        user32 = ctypes.windll.user32
        x = user32.GetSystemMetrics(76)
        y = user32.GetSystemMetrics(77)
        w = user32.GetSystemMetrics(78)
        h = user32.GetSystemMetrics(79)
        if w > 0 and h > 0:
            return x, y, w, h
    except Exception as e:
        logging.warning(f'获取虚拟屏幕信息失败: {e}')

    # fallback：获取主显示器尺寸
    try:
        user32 = ctypes.windll.user32
        w = user32.GetSystemMetrics(0)   # SM_CXSCREEN
        h = user32.GetSystemMetrics(1)   # SM_CYSCREEN
        if w > 0 and h > 0:
            return 0, 0, w, h
    except Exception:
        pass

    return 0, 0, 1920, 1080


class OverlayWindow:
    """全屏遮罩窗口，负责截图和区域选择"""

    MASK_ALPHA = 0.4          # 遮罩透明度（0=完全透明，1=不透明）
    MASK_COLOR = '#000000'     # 遮罩底色
    RECT_BORDER = '#00D4FF'    # 选框边框颜色（亮青色）
    RECT_WIDTH = 2             # 选框线宽
    MIN_SIZE = 5               # 最小选区尺寸（像素），防止误点击

    def __init__(self, root, on_captured, on_cancelled=None):
        """
        root: tkinter 根窗口
        on_captured: 截图完成后的回调，参数为 PIL.Image 对象
        on_cancelled: 用户取消截图时的回调（可选）
        """
        self.root = root
        self.on_captured = on_captured
        self.on_cancelled = on_cancelled

        self._start_x = 0
        self._start_y = 0
        self._rect_id = None
        self._info_id = None       # 尺寸提示文字
        self._full_screenshot = None
        self._tk_bg = None         # 保持 PhotoImage 引用，防止被 GC
        self._window = None
        self._canvas = None

    def show(self):
        """启动截图流程"""
        # 第一步：先截图，再显示遮罩，避免截到遮罩本身
        try:
            try:
                self._full_screenshot = ImageGrab.grab(all_screens=True)
            except TypeError:
                # 旧版 Pillow 不支持 all_screens 参数
                logging.info('多屏幕截图不支持，使用单屏幕模式')
                self._full_screenshot = ImageGrab.grab()
        except Exception as e:
            logging.error(f'截图失败: {e}')
            messagebox.showerror('截图失败', f'无法截取屏幕，请重试。\n{e}')
            if self.on_cancelled:
                self.on_cancelled()
            return

        self._build_window()

    def _build_window(self):
        vx, vy, vw, vh = _get_virtual_screen_info()
        self._vx = vx
        self._vy = vy
        self._vw = vw
        self._vh = vh

        win = tk.Toplevel(self.root)
        self._window = win

        # 去掉标题栏和边框，否则无法全屏覆盖
        win.overrideredirect(True)
        # 置顶，覆盖所有窗口
        win.attributes('-topmost', True)
        # 半透明遮罩
        win.attributes('-alpha', self.MASK_ALPHA)
        # 设置背景色（和 alpha 结合实现半透明效果）
        win.configure(bg=self.MASK_COLOR)

        # 手动设置几何，覆盖整个虚拟屏幕（包括多显示器）
        win.geometry(f'{vw}x{vh}+{vx}+{vy}')

        # 创建 Canvas，尺寸等于虚拟屏幕
        canvas = tk.Canvas(
            win,
            width=vw,
            height=vh,
            cursor='crosshair',   # 十字光标，提示用户可以框选
            bg=self.MASK_COLOR,
            highlightthickness=0  # 去掉 Canvas 默认边框
        )
        canvas.pack(fill=tk.BOTH, expand=True)
        self._canvas = canvas

        # 把截图贴到 Canvas 背景（让用户看到屏幕内容，方便选区）
        # 注意：截图可能比虚拟屏幕尺寸不同（DPI 缩放），需要缩放匹配
        screenshot_resized = self._full_screenshot.resize((vw, vh), Image.LANCZOS)
        self._tk_bg = ImageTk.PhotoImage(screenshot_resized)
        canvas.create_image(0, 0, anchor='nw', image=self._tk_bg)

        # 绑定鼠标事件
        canvas.bind('<ButtonPress-1>', self._on_mouse_down)
        canvas.bind('<B1-Motion>', self._on_mouse_drag)
        canvas.bind('<ButtonRelease-1>', self._on_mouse_up)

        # ESC 取消截图
        win.bind('<Escape>', lambda e: self._cancel())
        # 右键也取消
        canvas.bind('<ButtonPress-3>', lambda e: self._cancel())

        # 提示文字
        canvas.create_text(
            vw // 2, 30,
            text='拖拽鼠标选择截图区域  |  ESC 或右键取消',
            fill='white',
            font=('微软雅黑', 12),
        )

        win.focus_force()

    def _on_mouse_down(self, event):
        self._start_x = event.x
        self._start_y = event.y

        # 创建选区矩形（初始尺寸为 0）
        self._rect_id = self._canvas.create_rectangle(
            event.x, event.y, event.x, event.y,
            outline=self.RECT_BORDER,
            width=self.RECT_WIDTH,
            fill=''
        )
        # 尺寸提示文字
        self._info_id = self._canvas.create_text(
            event.x, event.y - 18,
            text='',
            fill=self.RECT_BORDER,
            font=('微软雅黑', 10),
            anchor='sw'
        )

    def _on_mouse_drag(self, event):
        if self._rect_id is None:
            return

        # 更新矩形位置
        self._canvas.coords(
            self._rect_id,
            self._start_x, self._start_y,
            event.x, event.y
        )

        # 更新尺寸提示
        w = abs(event.x - self._start_x)
        h = abs(event.y - self._start_y)
        self._canvas.itemconfig(self._info_id, text=f'{w} × {h}')
        self._canvas.coords(
            self._info_id,
            min(self._start_x, event.x),
            min(self._start_y, event.y) - 5
        )

    def _on_mouse_up(self, event):
        end_x = event.x
        end_y = event.y

        # 归一化坐标（处理从右下向左上拖的情况）
        x1 = min(self._start_x, end_x)
        y1 = min(self._start_y, end_y)
        x2 = max(self._start_x, end_x)
        y2 = max(self._start_y, end_y)

        # 最小选区保护
        if (x2 - x1) < self.MIN_SIZE or (y2 - y1) < self.MIN_SIZE:
            self._cancel()
            return

        # 从全屏截图中 crop 出选区
        # Canvas 坐标是相对于虚拟屏幕左上角的，截图也是虚拟屏幕的
        # 但截图被 resize 过了，需要换算回原始像素坐标
        orig_w, orig_h = self._full_screenshot.size
        scale_x = orig_w / self._vw
        scale_y = orig_h / self._vh

        crop_x1 = int(x1 * scale_x)
        crop_y1 = int(y1 * scale_y)
        crop_x2 = int(x2 * scale_x)
        crop_y2 = int(y2 * scale_y)

        cropped = self._full_screenshot.crop((crop_x1, crop_y1, crop_x2, crop_y2))

        # 关闭遮罩，释放大对象内存
        self._close()

        # 延迟 50ms 再回调，确保遮罩窗口完全销毁后再打开编辑器
        self.root.after(50, lambda: self.on_captured(cropped))

    def _cancel(self):
        self._close()
        if self.on_cancelled:
            self.on_cancelled()

    def _close(self):
        if self._window:
            try:
                self._window.destroy()
            except Exception:
                pass
            self._window = None
        # 及时释放大对象，防止内存泄漏
        self._full_screenshot = None
        self._tk_bg = None
