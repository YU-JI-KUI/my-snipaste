"""
系统托盘图标模块
使用 pystray 库在 Windows 通知区域显示图标
右键菜单提供：截图、配置快捷键、退出
"""

import logging
import threading
from PIL import Image, ImageDraw


def _create_default_icon() -> Image.Image:
    """生成内置图标（纯代码绘制，不依赖外部文件）"""
    size = 64
    img  = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([2, 2, size - 2, size - 2], fill='#0A84FF')
    draw.rectangle([12, 20, 52, 48], outline='white', width=3, fill=None)
    draw.ellipse([22, 24, 42, 44], outline='white', width=3)
    draw.rectangle([20, 16, 30, 22], fill='white')
    return img


class TrayIcon:
    """系统托盘图标，运行在独立线程"""

    def __init__(self, on_snip, on_quit, on_hotkey_config=None, on_tray_failed=None):
        """
        on_snip:          点击截图时的回调
        on_quit:          点击退出时的回调
        on_hotkey_config: 点击「配置快捷键」时的回调（可选）
        on_tray_failed:   托盘启动失败时的回调（可选）
        """
        self._on_snip          = on_snip
        self._on_quit          = on_quit
        self._on_hotkey_config = on_hotkey_config
        self._on_tray_failed   = on_tray_failed
        self._icon             = None
        self._thread           = None
        self._current_hotkey   = 'Ctrl+Alt+A'   # 用于菜单标题显示，由外部更新

    def update_hotkey_label(self, hotkey: str):
        """更新菜单上显示的快捷键文字，需重建菜单生效"""
        self._current_hotkey = hotkey.replace('+', '+').title()
        if self._icon:
            try:
                self._icon.menu = self._build_menu()
                self._icon.update_menu()
            except Exception:
                pass

    def _build_menu(self):
        import pystray
        items = [
            pystray.MenuItem(
                f'截图 ({self._current_hotkey})',
                self._on_snip_clicked,
                default=True,
            ),
            pystray.Menu.SEPARATOR,
        ]
        if self._on_hotkey_config:
            items.append(
                pystray.MenuItem('配置快捷键...', self._on_hotkey_config_clicked)
            )
            items.append(pystray.Menu.SEPARATOR)
        items.append(pystray.MenuItem('退出', self._on_quit_clicked))
        return pystray.Menu(*items)

    def start(self):
        """在后台线程启动托盘图标"""
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        try:
            import pystray
        except ImportError:
            logging.error('pystray 未安装，系统托盘不可用')
            if self._on_tray_failed:
                self._on_tray_failed()
            return

        try:
            self._icon = pystray.Icon(
                name='my-snipaste',
                icon=_create_default_icon(),
                title='my-snipaste 截图工具',
                menu=self._build_menu(),
            )
            self._icon.run()
        except Exception as e:
            logging.error(f'托盘图标运行失败: {e}')
            if self._on_tray_failed:
                self._on_tray_failed()

    def _on_snip_clicked(self, icon, item):
        self._on_snip()

    def _on_hotkey_config_clicked(self, icon, item):
        self._on_hotkey_config()

    def _on_quit_clicked(self, icon, item):
        self.stop()
        self._on_quit()

    def stop(self):
        if self._icon:
            try:
                self._icon.stop()
            except Exception:
                pass
