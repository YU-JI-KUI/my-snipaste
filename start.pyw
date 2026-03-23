"""
my-snipaste 启动器（无控制台窗口版）
适用于无法执行 .bat / PowerShell 的受限环境（如企业内网策略限制）
双击此文件即可启动，无需任何命令行操作。

运行原理：
  .pyw 文件由 Windows 自动关联到 pythonw.exe，天然无黑窗口。
  此脚本先静默安装依赖，再在同一进程内直接运行 main.py。
"""
import subprocess
import sys
import os

# 切换到脚本所在目录，确保相对路径正确
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# ── 第一步：静默安装依赖 ─────────────────────────────────────────────────────
result = subprocess.run(
    [sys.executable, '-m', 'pip', 'install', '-r', 'requirements.txt',
     '--disable-pip-version-check', '-q'],
    capture_output=True,
    text=True,
    encoding='utf-8',
    errors='replace',
)

if result.returncode != 0:
    # 安装失败，用 tkinter 弹窗提示（tkinter 是内置库，此时肯定可用）
    try:
        import tkinter as tk
        from tkinter import messagebox
        _root = tk.Tk()
        _root.withdraw()
        messagebox.showerror(
            'my-snipaste 启动失败',
            '依赖安装失败，请检查 pip 镜像配置或手动安装依赖。\n\n'
            '参考 README.md「内网环境配置 pip 镜像」章节。\n\n'
            f'错误详情：\n{result.stderr[:600]}'
        )
        _root.destroy()
    except Exception:
        pass
    sys.exit(1)

# ── 第二步：在当前进程内直接运行 main.py（已是 pythonw，无控制台）────────────
_main_path = os.path.abspath('main.py')
with open(_main_path, 'r', encoding='utf-8') as _f:
    _code = compile(_f.read(), _main_path, 'exec')

exec(_code, {'__name__': '__main__', '__file__': _main_path, '__spec__': None})
