"""
my-snipaste 截图工具入口
必须在所有 tkinter 代码之前声明 DPI 感知，否则在高分辨率屏幕上坐标会偏移
"""

import ctypes
import sys
import logging
import traceback

# DPI 感知声明 —— 必须放在 import tkinter 之前
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # 每个显示器独立 DPI
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()   # 旧版 Windows fallback
    except Exception:
        pass

import tkinter as tk
from tkinter import messagebox

# 全局异常捕获，写入 error.log，避免 pythonw 启动时无声崩溃
logging.basicConfig(
    filename='error.log',
    level=logging.ERROR,
    format='%(asctime)s %(levelname)s %(message)s'
)

def handle_exception(exc_type, exc_value, exc_tb):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return
    msg = ''.join(traceback.format_exception(exc_type, exc_value, exc_tb))
    logging.error(msg)
    try:
        messagebox.showerror('my-snipaste 出错', f'{exc_value}\n\n详情已写入 error.log')
    except Exception:
        pass

sys.excepthook = handle_exception

from snip.app import App


def main():
    root = tk.Tk()
    root.withdraw()  # 隐藏主窗口，只在托盘显示

    app = App(root)
    app.start()

    try:
        root.mainloop()
    finally:
        app.shutdown()


if __name__ == '__main__':
    main()
