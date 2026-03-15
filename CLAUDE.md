# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

**my-snipaste** 是一个面向 Windows 用户的轻量截图工具，用于公司内网环境（公司未提供 Snipaste，用户自建）。

用户从 GitHub 下载源码，双击 `start.bat` 即可运行，无需安装。

## 技术栈

- **Python 3.8+**，GUI 用 `tkinter`（内置）
- `keyboard` — 全局热键
- `Pillow` — 截图 + 图片合成
- `pystray` — 系统托盘图标

## 开发命令

```bash
pip install -r requirements.txt
python main.py        # 开发调试（有终端输出）
pythonw main.py       # 生产运行（无黑窗口）
```

## 项目结构

```
main.py               # 入口：DPI 声明、单实例锁、异常捕获、启动 App
snip/
  app.py              # 协调模块：串联 hotkey/overlay/tray
  hotkey.py           # 全局热键注册（keyboard 库），atexit 清理
  overlay.py          # 全屏遮罩 + 选区 + 内嵌 EditCanvas 编辑
  editor.py           # EditorWindow（独立模式，继承 AnnotationMixin）
  editor_mixin.py     # AnnotationMixin：所有标注逻辑、工具栏、保存复制
  tray.py             # 系统托盘图标（pystray，独立线程）
```

## 当前功能列表

- **Ctrl+Alt+A** 全局热键触发截图
- **选区流程（两阶段）**：
  - 阶段一：拖拽绘制选区（黑色选框）
  - 阶段二：松手后 **EditCanvas 立即叠加在选区上方**，工具栏同时显示，可直接标注
    - 拖动选区边框/控制点：EditCanvas 隐藏，松手后更新位置重新显示
    - 点击选区外：销毁 EditCanvas，重新绘制选区
    - ESC / 右键：取消整个截图流程

### 编辑器

截图后进入编辑器，默认为移动模式。工具栏是独立浮动窗口，贴在图片正下方。

**浮动工具栏（图标 + hover tooltip）：**

| 图标 | 工具 | 说明 |
|------|------|------|
| ✥ | 移动 | 拖动整个编辑器窗口；拖动时工具栏自动隐藏，停止后归位 |
| T | 文字 | 点击输入文字，背景色取点击位置像素（视觉透明） |
| → | 箭头 | 拖拽绘制带箭头线段 |
| □ | 矩形 | 拖拽绘制空心矩形框 |
| ▦ | 马赛克 | 拖拽选区打码（缩小1/10再放大，快照方案支持撤销） |
| ↩ | 撤销 | Ctrl+Z，逐步撤销，马赛克撤销恢复图片快照 |
| 📌 | 贴图 | 工具栏消失，图片加橙色边框常驻屏幕，双击/右键关闭 |
| 💾 | 保存 | Ctrl+S，弹出对话框，默认保存到桌面 |
| ✓ | 复制 | Ctrl+C，复制到剪贴板后直接关闭（无确认框） |
| ✕ | 关闭 | 关闭编辑器 |

**第二行：** 颜色色块×8 + 当前色指示 + 字号调节（8~72）

- **系统托盘**：右键菜单截图 / 退出
- **单实例**：msvcrt 文件锁，重复启动静默退出

## 关键设计决策

**DPI 感知**：`ctypes.windll.shcore.SetProcessDpiAwareness(2)` 必须在 `import tkinter` 之前调用。

**线程安全**：`keyboard` 回调在独立线程，所有 UI 操作通过 `root.after(0, fn)` 派发回主线程。

**截图时机**：`overlay.py` 中必须先 `ImageGrab.grab()` 截图，再创建遮罩窗口。

**选区高亮**：预生成变暗版截图（`ImageEnhance.Brightness`），拖拽时用四张裁剪暗图贴到选区外四个区域，选区内显示原图。不使用 stipple / alpha 窗口，Windows 兼容性最好。

**浮动工具栏**：工具栏是独立 `tk.Toplevel`，不嵌在主窗口里。宽度自适应内容（`winfo_reqwidth()`），居中对齐图片下方。拖动时 `withdraw()` 隐藏，松手后先 `_reposition_toolbar()` 算好坐标再 `deiconify()` 显示（顺序不能反，否则位置抖动）。工具栏按钮点击后需 `self._win.focus_force()` 把焦点还给主窗口，否则键盘快捷键失效。

**颜色/字号行按需显示**：`self._style_row` 默认不 pack，切换到文字/箭头/矩形工具时 pack 显示，切换到移动/马赛克时 `pack_forget()` 隐藏。切换后需 `update_idletasks()` + `_reposition_toolbar()` 重新定位工具栏（因为高度变了）。

**选区调整模式**：overlay.py 分两阶段。阶段一拖拽绘制，松手后进入阶段二（`_enter_adjust_mode`）。阶段二有8个控制点（`HANDLES`），`_hit_handle` 检测点击、`_hit_inside` 检测移动，点击选区外重新进入阶段一。

**马赛克撤销用快照方案**：`paste()` 是破坏性操作，直接修改 `self._image` 像素。每次马赛克前存 `{'type': 'mosaic_snapshot', 'image': self._image.copy()}` 进 `_annotations`，撤销时恢复。

**贴图模式**：点 📌 后销毁工具栏，Canvas 加 `highlightthickness=3, highlightbackground='#FF6B00'` 橙色边框，解绑标注事件，重新绑定纯拖动 + 双击/右键关闭。

**复制剪贴板**：使用 `pywin32` 的 `win32clipboard`，直接写入 `CF_DIB` 格式（BMP 去掉 14 字节文件头）。不依赖 PowerShell，无黑窗口，无启动延迟。禁止再用 PowerShell 子进程方案。

**文字透明背景**：取点击坐标对应的截图像素颜色作为 Entry bg，视觉上融入截图背景。

**单实例锁**：`msvcrt.locking()` 文件锁，比 bat 里的 tasklist 检测可靠。

**Canvas 布局用 pack，不用 place**：Canvas 必须用 `canvas.pack(side=tk.TOP)` 并明确指定 `width/height` 参数。`place` 布局 + 不设窗口尺寸会导致 tkinter 自动收缩窗口，截图显示变小。

**窗口尺寸必须同时设置宽高**：`win.geometry(f'+{x}+{y}')` 只设位置不设尺寸，tkinter 会把窗口缩到最小。正确写法：
```python
win.update_idletasks()
actual_h = win.winfo_reqheight()
win.geometry(f'{dw}x{actual_h}+{x}+{y}')
```

**回归测试要求**：每次修改后必须检查以下所有项目，不能等用户反馈：
1. 截图尺寸是否正确（不变小）
2. 所有工具按钮可见（✥ T → □ ▦ ↩ 📌 💾 ✓ ✕）
3. 浮动工具栏贴在图片正下方
4. 拖动图片时工具栏隐藏，松手后归位
5. 文字工具能否输入并显示
6. 箭头/矩形工具能否正常绘制
7. 马赛克拖拽打码，Ctrl+Z 可撤销
8. 贴图模式：工具栏消失，橙色边框，双击关闭
9. 保存弹出文件对话框
10. 复制成功后直接关闭（不弹确认框）

## 历史 Bug 记录（从错误中学习）

| # | Bug 现象 | Root Cause | 修复方法 |
|---|---------|-----------|---------|
| 1 | 双击 start.bat 无反应 / 闪退 | bat 没有 `cd /d "%~dp0"`，工作目录错误找不到 snip 包 | 加 `cd /d "%~dp0"`；main.py 加 `os.chdir` |
| 2 | start.bat 启动后黑窗口不关闭 | 用了 `python start /b` 导致窗口挂起 | 改为 `start "" pythonw main.py`，bat 结尾 `exit` |
| 3 | 重复启动多个实例 | bat 里 tasklist+findstr 看不到命令行参数，检测失效 | 改为 Python 内 `msvcrt.locking()` 文件锁 |
| 4 | 热键注册失败弹窗打扰用户 | 注册失败时调用 `showwarning` | 改为静默处理，只写 error.log |
| 5 | ESC 取消截图后无法再截图 | `_snipping` 标志没有在 `on_cancelled` 中重置 | app.py 加 `on_cancelled=self._reset_snipping` |
| 6 | 选区外半透明效果渲染异常 | `stipple='gray50'` 在部分 Windows tkinter 版本渲染不正确 | 改为四块裁剪暗图方案（`ImageEnhance.Brightness`） |
| 7 | 保存按钮不见了 | 单行工具栏控件数量太多，右侧按钮被挤出可视区域 | 改为两行工具栏布局 |
| 8 | 复制有黑窗口 + 卡顿，且依赖 PowerShell | 用 subprocess 启动 PowerShell 子进程操作剪贴板，效率差且不稳定 | 改用 `pywin32` 的 `win32clipboard.SetClipboardData(CF_DIB, dib_data)`，纯 Python 直接写剪贴板 |
| 9 | **截图显示变小** | `geometry` 只设位置 `+x+y` 没设尺寸；Canvas 用 `place` 布局不约束窗口大小，tkinter 自动收缩 | Canvas 改用 `pack(side=TOP)` 并指定 `width/height`；`geometry` 改为 `f'{dw}x{actual_h}+{x}+{y}'` |
| 10 | **切换工具后工具栏消失** | `_set_tool` 调用 `focus_force()` 把焦点交还主窗口，Windows 上 Toplevel 工具栏被主窗口遮挡 | `focus_force()` 前先调用 `toolbar_win.lift()` |
| 11 | **贴图边框裁剪图片** | `_PinWindow` 窗口几何只设了图片尺寸，`highlightthickness=3` 边框占了额外像素，图片右/下被截断 | 窗口 geometry 改为 `{iw+BORDER*2}x{ih+BORDER*2}` |

## 语言要求

所有代码注释、用户提示文字使用**中文**，回复也使用中文。
