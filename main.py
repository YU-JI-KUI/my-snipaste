"""
my-snipaste 截图工具入口
必须在所有 tkinter 代码之前声明 DPI 感知
"""

import sys
import os
import logging
import traceback

# 切换到 main.py 所在目录，确保相对路径正确
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# DPI 感知声明 —— 必须在 import tkinter 之前
try:
    import ctypes
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        import ctypes
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

import tkinter as tk
from tkinter import messagebox

logging.basicConfig(
    filename='error.log',
    level=logging.ERROR,
    format='%(asctime)s %(levelname)s %(message)s',
    encoding='utf-8'
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


def _check_single_instance():
    """
    单实例检测：用文件锁实现。
    Windows 上打开文件后不关闭，第二个进程尝试独占打开同一文件会失败。
    返回锁文件句柄（需保持引用，进程退出时自动释放）。
    """
    lock_path = os.path.abspath('my-snipaste.lock')
    try:
        import msvcrt
        lock_file = open(lock_path, 'w')
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        return lock_file   # 持有锁，正常启动
    except (IOError, OSError):
        # 抢锁失败 → 已有实例在运行
        return None
    except ImportError:
        # 非 Windows 环境（开发调试用），直接放行
        return None


from snip.app import App


def main():
    lock = _check_single_instance()
    if lock is None:
        # 已有实例，静默退出
        sys.exit(0)

    root = tk.Tk()
    root.withdraw()

    app = App(root)
    app.start()

    try:
        root.mainloop()
    finally:
        app.shutdown()
        # 释放锁文件
        try:
            import msvcrt
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            lock.close()
        except Exception:
            pass


if __name__ == '__main__':
    main()
