"""
my-snipaste 强制终止脚本（无控制台窗口版）
双击此文件可强制关闭所有 my-snipaste 进程。

注意：通常无需使用此文件，右键系统托盘图标 → 退出 即可正常关闭。
仅在程序卡死无法响应时使用。
"""
import subprocess
import sys
import os

os.chdir(os.path.dirname(os.path.abspath(__file__)))

# 用 taskkill（Windows 内置命令，非 PowerShell）终止进程
# 按命令行参数过滤，避免误杀其他 Python 进程
_cmds = [
    ['taskkill', '/f', '/im', 'pythonw.exe', '/fi', 'WINDOWTITLE eq my-snipaste*'],
    ['taskkill', '/f', '/im', 'python.exe',  '/fi', 'COMMANDLINE eq *main.py*'],
]
for _cmd in _cmds:
    subprocess.run(_cmd, capture_output=True)

# 提示用户
try:
    import tkinter as tk
    from tkinter import messagebox
    _root = tk.Tk()
    _root.withdraw()
    messagebox.showinfo('my-snipaste', '已发送关闭指令。\n若程序仍在运行，请在任务管理器中手动结束 pythonw.exe 进程。')
    _root.destroy()
except Exception:
    pass
