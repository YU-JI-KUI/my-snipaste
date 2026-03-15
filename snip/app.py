"""
应用主协调模块
负责把 hotkey / overlay / tray 串联起来
"""

import logging
import tkinter as tk
from tkinter import messagebox

from .hotkey import HotkeyManager
from .overlay import OverlayWindow
from .tray import TrayIcon


class App:
    def __init__(self, root: tk.Tk):
        self.root        = root
        self._hotkey_mgr = HotkeyManager(root)
        self._overlay    = None
        self._tray       = None
        self._snipping   = False

    def start(self):
        self._hotkey_mgr.register(self._trigger_snip)

        self._tray = TrayIcon(
            on_snip=lambda: self.root.after(0, self._trigger_snip),
            on_quit=lambda: self.root.after(0, self._quit),
            on_hotkey_config=lambda: self.root.after(0, self._show_hotkey_dialog),
            on_tray_failed=lambda: self.root.after(0, self._on_tray_failed),
        )
        self._tray.start()

        # 同步菜单显示当前快捷键
        self.root.after(500, lambda: self._tray.update_hotkey_label(self._hotkey_mgr.hotkey))
        logging.info(f'my-snipaste 已启动，快捷键: {self._hotkey_mgr.hotkey}')

    # ── 截图 ──────────────────────────────────────

    def _trigger_snip(self):
        if self._snipping:
            return
        self._snipping = True
        try:
            overlay = OverlayWindow(self.root, on_done=self._reset_snipping)
            self._overlay = overlay
            overlay.show()
        except Exception as e:
            logging.error(f'打开遮罩失败: {e}')
            self._reset_snipping()

    def _reset_snipping(self):
        self._snipping = False

    # ── 快捷键配置对话框 ───────────────────────────

    def _show_hotkey_dialog(self):
        """弹出快捷键配置窗口，用户按下组合键后保存"""
        dlg = tk.Toplevel(self.root)
        dlg.title('配置快捷键')
        dlg.resizable(False, False)
        dlg.attributes('-topmost', True)
        dlg.grab_set()   # 模态

        # 居中显示
        dlg.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        w, h = 360, 180
        dlg.geometry(f'{w}x{h}+{(sw-w)//2}+{(sh-h)//2}')
        dlg.configure(bg='#2C2C2C')

        current = self._hotkey_mgr.hotkey
        state   = {'keys': set(), 'hotkey': ''}

        tk.Label(dlg, text='当前快捷键：', bg='#2C2C2C', fg='#AAAAAA',
                 font=('微软雅黑', 9)).pack(pady=(16, 0))
        tk.Label(dlg, text=current.upper(), bg='#2C2C2C', fg='#0A84FF',
                 font=('微软雅黑', 11, 'bold')).pack()

        tk.Label(dlg, text='请按下新的快捷键组合：', bg='#2C2C2C', fg='#CCCCCC',
                 font=('微软雅黑', 9)).pack(pady=(12, 4))

        preview = tk.Label(dlg, text='等待按键...', bg='#3C3C3C', fg='#FFFFFF',
                           font=('微软雅黑', 12, 'bold'),
                           width=24, relief=tk.FLAT, pady=6)
        preview.pack()

        btn_frame = tk.Frame(dlg, bg='#2C2C2C')
        btn_frame.pack(pady=12)

        def on_key_press(e):
            # 收集修饰键 + 普通键
            mods = []
            if e.state & 0x4:  mods.append('ctrl')
            if e.state & 0x1:  mods.append('shift')
            if e.state & 0x20000: mods.append('alt')
            key = e.keysym.lower()
            # 过滤纯修饰键
            if key in ('control_l', 'control_r', 'shift_l', 'shift_r',
                       'alt_l', 'alt_r', 'super_l', 'super_r'):
                return
            parts = mods + [key]
            if len(parts) >= 2:   # 至少需要一个修饰键
                state['hotkey'] = '+'.join(parts)
                preview.config(text=state['hotkey'].upper(), fg='#30D158')
                btn_save.config(state=tk.NORMAL)
            else:
                preview.config(text='需要至少一个修饰键（Ctrl/Alt/Shift）', fg='#FF3B30')
                state['hotkey'] = ''
                btn_save.config(state=tk.DISABLED)

        dlg.bind('<KeyPress>', on_key_press)
        dlg.focus_force()

        def save():
            new_hk = state['hotkey']
            if not new_hk:
                return
            ok = self._hotkey_mgr.change(new_hk)
            if ok:
                self._tray.update_hotkey_label(new_hk)
                messagebox.showinfo('配置成功',
                                    f'快捷键已更改为：\n{new_hk.upper()}',
                                    parent=dlg)
                dlg.destroy()
            else:
                messagebox.showerror('配置失败',
                                     f'快捷键 {new_hk.upper()} 注册失败，\n'
                                     '可能已被其他程序占用，请换一个组合键。',
                                     parent=dlg)

        btn_save = tk.Button(btn_frame, text='保存', command=save,
                             bg='#30D158', fg='black', font=('微软雅黑', 9),
                             relief=tk.FLAT, padx=16, pady=4, cursor='hand2',
                             state=tk.DISABLED)
        btn_save.pack(side=tk.LEFT, padx=6)

        tk.Button(btn_frame, text='取消', command=dlg.destroy,
                  bg='#5A5A5A', fg='white', font=('微软雅黑', 9),
                  relief=tk.FLAT, padx=16, pady=4, cursor='hand2').pack(side=tk.LEFT, padx=6)

    # ── 托盘失败 ───────────────────────────────────

    def _on_tray_failed(self):
        messagebox.showerror(
            'my-snipaste',
            '系统托盘启动失败（pystray 未正确安装）。\n\n'
            '请关闭此窗口后重新双击 start.bat 安装依赖，\n'
            '或在任务管理器中结束 pythonw.exe 进程退出程序。',
        )

    # ── 退出 ──────────────────────────────────────

    def _quit(self):
        self.shutdown()
        self.root.quit()

    def shutdown(self):
        self._hotkey_mgr.unregister()
        if self._tray:
            self._tray.stop()
