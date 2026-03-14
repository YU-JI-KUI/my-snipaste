"""
应用主协调模块
负责把 hotkey / overlay / editor / tray 串联起来
"""

import logging
import tkinter as tk
from tkinter import messagebox

from .hotkey import HotkeyManager
from .overlay import OverlayWindow
from .editor import EditorWindow
from .tray import TrayIcon


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self._hotkey_mgr = HotkeyManager(root)
        self._overlay = None
        self._tray = None
        self._snipping = False   # 防止重复触发

    def start(self):
        """初始化所有组件并启动"""
        # 注册全局热键
        ok = self._hotkey_mgr.register(self._trigger_snip)
        if not ok:
            messagebox.showwarning(
                'my-snipaste',
                'keyboard 库未安装或热键注册失败。\n'
                '请运行 start.bat 安装依赖，或通过托盘菜单截图。'
            )

        # 启动系统托盘
        self._tray = TrayIcon(
            on_snip=lambda: self.root.after(0, self._trigger_snip),
            on_quit=lambda: self.root.after(0, self._quit)
        )
        self._tray.start()

        hotkey = self._hotkey_mgr.hotkey
        logging.info(f'my-snipaste 已启动，快捷键: {hotkey}')

    def _trigger_snip(self):
        """触发截图流程（由热键或托盘菜单调用）"""
        if self._snipping:
            return
        self._snipping = True

        try:
            overlay = OverlayWindow(
                self.root,
                on_captured=self._on_captured,
                on_cancelled=self._reset_snipping
            )
            self._overlay = overlay
            overlay.show()
        except Exception as e:
            logging.error(f'打开遮罩失败: {e}')
            self._reset_snipping()

    def _reset_snipping(self):
        self._snipping = False

    def _on_captured(self, image):
        """截图完成的回调，打开编辑器"""
        self._snipping = False
        try:
            EditorWindow(self.root, image)
        except Exception as e:
            logging.error(f'打开编辑器失败: {e}')
            messagebox.showerror('my-snipaste', f'打开编辑器失败：{e}')

    def _quit(self):
        """退出程序"""
        self.shutdown()
        self.root.quit()

    def shutdown(self):
        """清理资源"""
        self._hotkey_mgr.unregister()
        if self._tray:
            self._tray.stop()
