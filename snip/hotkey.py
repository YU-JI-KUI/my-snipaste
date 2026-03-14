"""
全局热键管理模块
keyboard 库的回调运行在独立线程，必须用 root.after(0, fn) 派发回 tkinter 主线程
"""

import atexit
import logging

try:
    import keyboard
    KEYBOARD_AVAILABLE = True
except ImportError:
    KEYBOARD_AVAILABLE = False
    logging.warning('keyboard 库未安装，全局热键不可用')


class HotkeyManager:
    # 默认截图快捷键
    DEFAULT_HOTKEY = 'ctrl+alt+a'

    def __init__(self, root):
        self.root = root
        self._hotkey = None
        self._callback = None
        atexit.register(self._cleanup)

    def register(self, callback, hotkey=None):
        """注册全局热键，callback 会被安全地派发回 tkinter 主线程"""
        if not KEYBOARD_AVAILABLE:
            logging.error('keyboard 库不可用，无法注册热键')
            return False

        self._callback = callback
        self._hotkey = hotkey or self.DEFAULT_HOTKEY

        def safe_dispatch():
            try:
                self.root.after(0, self._callback)
            except Exception as e:
                logging.error(f'热键回调派发失败: {e}')

        try:
            keyboard.add_hotkey(
                self._hotkey,
                safe_dispatch,
                suppress=False
            )
            logging.info(f'已注册热键: {self._hotkey}')
            return True
        except Exception as e:
            logging.error(f'注册热键失败: {e}')
            return False

    def unregister(self):
        """注销当前热键"""
        if not KEYBOARD_AVAILABLE:
            return
        try:
            if self._hotkey:
                keyboard.remove_hotkey(self._hotkey)
                self._hotkey = None
        except Exception as e:
            logging.error(f'注销热键失败: {e}')

    def _cleanup(self):
        """程序退出时清理所有键盘钩子，防止残留"""
        if not KEYBOARD_AVAILABLE:
            return
        try:
            keyboard.unhook_all()
        except Exception:
            pass

    @property
    def hotkey(self):
        return self._hotkey or self.DEFAULT_HOTKEY
