# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

**my-snipaste** 是一个面向 Windows 用户的轻量截图工具，用于公司内网环境。
参考产品：https://zh.snipaste.com/

用户从 GitHub 下载源码，双击 `start.bat` 即可运行，无需安装。

## 技术栈

- **Python 3.8+**，GUI 用 `tkinter`（内置）
- `keyboard` — 全局热键
- `Pillow` — 截图 + 图片合成
- `pystray` — 系统托盘图标

## 开发命令

```bash
# 安装依赖
pip install -r requirements.txt

# 运行（开发时用 python，可以看到终端输出）
python main.py

# Windows 生产运行（无黑窗口）
pythonw main.py
```

## 项目结构

```
main.py          # 入口：DPI 声明、异常捕获、启动 App
snip/
  app.py         # 协调模块：串联 hotkey/overlay/editor/tray
  hotkey.py      # 全局热键注册（keyboard 库），atexit 清理钩子
  overlay.py     # 全屏遮罩 + 区域选择（最复杂，含多显示器逻辑）
  editor.py      # 截图编辑器（文字标注、保存、复制剪贴板）
  tray.py        # 系统托盘图标（pystray，独立线程运行）
```

## 关键设计决策

**DPI 感知**：`ctypes.windll.shcore.SetProcessDpiAwareness(2)` 必须在 `import tkinter` 之前调用（在 `main.py` 最顶部），否则高分辨率屏幕坐标偏移。

**线程安全**：`keyboard` 回调在独立线程，所有 UI 操作必须通过 `root.after(0, fn)` 派发回主线程。

**截图时机**：`overlay.py` 中必须先 `ImageGrab.grab()` 截图，再创建遮罩窗口，避免截到遮罩本身。

**多显示器坐标**：Canvas 坐标是相对于虚拟屏幕左上角的，截图被 resize 过，crop 前需要用 `scale_x = orig_w / vw` 换算回原始像素坐标。

**文字标注两阶段**：
- 编辑态：`canvas.create_window()` 嵌入 Entry 控件
- 固化态：`canvas.delete('entry_window')` + 记录到 `self._annotations[]`
- 保存时：Pillow `ImageDraw.text()` 重绘所有标注到原始截图

**中文字体**：保存时用 `ImageFont.truetype('C:/Windows/Fonts/msyh.ttc', size)` 支持中文，fallback 到 `ImageFont.load_default()`。

**复制剪贴板**：通过 PowerShell `System.Windows.Forms.Clipboard::SetImage()` 实现，不增加额外依赖。

## 语言要求

所有代码注释、用户提示文字使用**中文**，回复也使用中文。
