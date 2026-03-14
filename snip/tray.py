"""
系统托盘图标模块
使用 pystray 库在 Windows 通知区域显示图标
右键菜单提供：截图、退出
"""

import logging
import threading
from PIL import Image, ImageDraw


def _create_default_icon() -> Image.Image:
    """
    生成一个简单的内置图标（纯代码绘制，不依赖外部文件）
    蓝底白色剪刀形状，16x16
    """
    size = 64
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 蓝色圆形背景
    draw.ellipse([2, 2, size - 2, size - 2], fill='#0A84FF')

    # 白色相机轮廓（简化版）
    # 外框
    draw.rectangle([12, 20, 52, 48], outline='white', width=3, fill=None)
    # 镜头圆
    draw.ellipse([22, 24, 42, 44], outline='white', width=3)
    # 取景器凸起
    draw.rectangle([20, 16, 30, 22], fill='white')

    return img


class TrayIcon:
    """系统托盘图标，运行在独立线程"""

    def __init__(self, on_snip, on_quit):
        """
        on_snip: 点击截图时的回调
        on_quit: 点击退出时的回调
        """
        self._on_snip = on_snip
        self._on_quit = on_quit
        self._icon = None
        self._thread = None

    def start(self):
        """在后台线程启动托盘图标"""
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        try:
            import pystray
        except ImportError:
            logging.warning('pystray 未安装，系统托盘不可用')
            return

        try:
            icon_image = _create_default_icon()

            menu = pystray.Menu(
                pystray.MenuItem('截图 (Ctrl+Alt+A)', self._on_snip_clicked, default=True),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem('退出', self._on_quit_clicked),
            )

            self._icon = pystray.Icon(
                name='my-snipaste',
                icon=icon_image,
                title='my-snipaste 截图工具',
                menu=menu
            )

            self._icon.run()

        except Exception as e:
            logging.error(f'托盘图标运行失败: {e}')

    def _on_snip_clicked(self, icon, item):
        self._on_snip()

    def _on_quit_clicked(self, icon, item):
        self.stop()
        self._on_quit()

    def stop(self):
        if self._icon:
            try:
                self._icon.stop()
            except Exception:
                pass
