"""
应用主协调模块
负责把 hotkey / overlay / editor / tray 串联起来
"""

import logging
import tkinter as tk
from tkinter import messagebox

from .hotkey import HotkeyManager
from .overlay import OverlayWindow
from .tray import TrayIcon


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self._hotkey_mgr = HotkeyManager(root)
        self._overlay = None
        self._tray = None
        self._snipping = False

    def start(self):
        # 注册全局热键，失败时静默处理（不弹窗），仍可通过托盘截图
        self._hotkey_mgr.register(self._trigger_snip)

        # 启动系统托盘
        self._tray = TrayIcon(
            on_snip=lambda: self.root.after(0, self._trigger_snip),
            on_quit=lambda: self.root.after(0, self._quit),
            on_tray_failed=lambda: self.root.after(0, self._on_tray_failed),
        )
        self._tray.start()

        logging.info(f'my-snipaste 已启动，快捷键: {self._hotkey_mgr.hotkey}')

    def _trigger_snip(self):
        if self._snipping:
            return
        self._snipping = True

        try:
            overlay = OverlayWindow(
                self.root,
                on_done=self._reset_snipping,
            )
            self._overlay = overlay
            overlay.show()
        except Exception as e:
            logging.error(f'打开遮罩失败: {e}')
            self._reset_snipping()

    def _reset_snipping(self):
        self._snipping = False

    def _on_tray_failed(self):
        """托盘启动失败时提示用户，并提供退出入口"""
        messagebox.showerror(
            'my-snipaste',
            '系统托盘启动失败（pystray 未正确安装）。\n\n'
            '请关闭此窗口后重新双击 start.bat 安装依赖，\n'
            '或在任务管理器中结束 pythonw.exe 进程退出程序。',
        )

    def _quit(self):
        self.shutdown()
        self.root.quit()

    def shutdown(self):
        self._hotkey_mgr.unregister()
        if self._tray:
            self._tray.stop()
