"""
全局热键管理模块
keyboard 库的回调运行在独立线程，必须用 root.after(0, fn) 派发回 tkinter 主线程
配置持久化到 config.json，下次启动自动读取
"""

import atexit
import json
import logging
import os

try:
    import keyboard
    KEYBOARD_AVAILABLE = True
except ImportError:
    KEYBOARD_AVAILABLE = False
    logging.warning('keyboard 库未安装，全局热键不可用')

_CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'config.json')


def _load_config() -> dict:
    try:
        with open(_CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _save_config(data: dict):
    try:
        with open(_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f'保存配置失败: {e}')


class HotkeyManager:
    DEFAULT_HOTKEY = 'ctrl+alt+a'

    def __init__(self, root):
        self.root = root
        self._hotkey  = None
        self._callback = None
        # 从配置文件读取上次保存的快捷键
        cfg = _load_config()
        self._saved_hotkey = cfg.get('hotkey', self.DEFAULT_HOTKEY)
        atexit.register(self._cleanup)

    def register(self, callback, hotkey=None):
        """注册全局热键，hotkey 为 None 时使用配置文件中的值"""
        if not KEYBOARD_AVAILABLE:
            logging.error('keyboard 库不可用，无法注册热键')
            return False

        self._callback = callback
        self._hotkey   = hotkey or self._saved_hotkey

        def safe_dispatch():
            try:
                self.root.after(0, self._callback)
            except Exception as e:
                logging.error(f'热键回调派发失败: {e}')

        try:
            keyboard.add_hotkey(self._hotkey, safe_dispatch, suppress=False)
            logging.info(f'已注册热键: {self._hotkey}')
            return True
        except Exception as e:
            logging.error(f'注册热键失败: {e}')
            return False

    def change(self, new_hotkey: str) -> bool:
        """注销旧热键，注册新热键，并持久化到配置文件"""
        if not KEYBOARD_AVAILABLE:
            return False
        # 注销旧热键
        self.unregister()
        # 注册新热键
        ok = self.register(self._callback, new_hotkey)
        if ok:
            # 持久化
            cfg = _load_config()
            cfg['hotkey'] = new_hotkey
            _save_config(cfg)
            self._saved_hotkey = new_hotkey
        return ok

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
        return self._hotkey or self._saved_hotkey
