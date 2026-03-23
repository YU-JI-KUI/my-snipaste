# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

**my-snipaste** 是一个面向 Windows 用户的轻量截图工具，用于公司内网环境（无法安装 Snipaste）。
参考产品：https://www.snipaste.com/

用户从 GitHub 下载源码，双击 `start.bat`（或受限环境下双击 `start.pyw`）即可运行，无需安装。

## 技术栈

- **Python 3.8+**，GUI 用 `tkinter`（内置，无需安装）
- `keyboard` — 全局热键（回调在独立线程）
- `Pillow` — 截图 + 图片处理 + 标注合成
- `pystray` — 系统托盘图标（独立线程）
- `pywin32` — 写入剪贴板（CF_DIB 格式，不依赖 PowerShell）

## 开发命令

```bash
pip install -r requirements.txt
python main.py        # 开发调试（有终端输出）
pythonw main.py       # 生产运行（无黑窗口）
```

## 启动方式

| 文件 | 适用场景 |
|------|---------|
| `start.bat` | 普通 Windows 环境 |
| `start.pyw` | 企业内网禁止执行 .bat / PowerShell 的受限环境，双击即可 |
| `stop.bat` | 普通环境强制终止 |
| `stop.pyw` | 受限环境强制终止（通常用托盘「退出」即可） |

`.pyw` 由 Windows 关联到 `pythonw.exe`，属于文件打开操作，不受 BAT/PS1 脚本执行策略限制。

## 架构总览

```
main.py
  └─ App (snip/app.py)
       ├─ HotkeyManager (snip/hotkey.py)   # 全局热键，atexit 清理
       ├─ TrayIcon     (snip/tray.py)       # 系统托盘，独立 daemon 线程
       └─ OverlayWindow (snip/overlay.py)   # 核心：全屏遮罩 + 选区 + 编辑
            └─ _PinWindow                   # 贴图浮动窗口（内部类）
```

> `snip/editor.py` 和 `snip/editor_mixin.py` 是历史遗留文件，当前主流程不使用，
> 所有截图编辑逻辑已全部迁移到 `overlay.py`。

## 核心模块详解：overlay.py

这是整个项目最复杂的文件（约 1050 行），承载了所有截图和编辑逻辑。

### 两个阶段

**阶段一：拖拽绘制（phase='draw'）**
- 全屏 `Toplevel` + `Canvas` 覆盖屏幕
- 底层放原始截图，上层放变暗版（四块拼接，露出选区）
- 鼠标拖拽实时更新 4 块暗图裁剪范围 → 选区高亮效果
- 松手且选区 >= 5px → 进入阶段二

**阶段二：编辑（phase='edit'）**
- 选框变蓝，出现 8 个控制柄（Handles）
- 浮动工具栏（独立 `Toplevel`）出现在选区正下方
- Move 工具：拖控制柄调整大小，拖内部移动选区
- 其他工具（text/arrow/rect/mosaic）：在选区内直接绘制标注
- 点击选区外 → 回到阶段一重新绘制

### 标注系统

每个标注是一个 dict，存入 `self._annotations[]`：

```python
# 箭头
{'type': 'arrow', 'x1': ..., 'y1': ..., 'x2': ..., 'y2': ..., 'color': ..., 'size': ..., 'canvas_id': ...}
# 矩形
{'type': 'rect',  'x1': ..., 'y1': ..., 'x2': ..., 'y2': ..., 'color': ..., 'size': ..., 'canvas_id': ...}
# 文字
{'type': 'text',  'x': ...,  'y': ...,  'text': ..., 'color': ..., 'size': ..., 'canvas_id': ...}
# 马赛克（破坏性操作，用快照支持撤销）
{'type': 'mosaic', 'x1': ..., ..., 'snapshot': <full_img_copy>}
```

`canvas_id` 是 tkinter Canvas item id，撤销时用它精确删除，不能用 tag 顺序查找。

### 图层顺序（从底到顶）

```
_id_bright          原始截图（最底层）
_id_dim_top/bottom/left/right  四块暗图，拼出遮罩效果
bright_region       马赛克后刷新的选区亮图
annotation tag      所有标注（箭头/矩形/文字）
_id_rect            选区边框（蓝色）
handle_ids          8 个控制柄（最顶层）
```

### 工具栏设计

- 独立 `Toplevel`，`overrideredirect=True`，`topmost=True`
- 宽度自适应内容，居中对齐选区下方（`_reposition_toolbar`）
- Move 拖动时 `withdraw()` 隐藏，松手后 `deiconify()` 恢复
- 标注操作完成后调 `_ensure_toolbar_visible()` 强制 `deiconify + lift`
- `_style_row`（颜色+字号）只在 text/arrow/rect 工具激活时 `pack` 显示，其余工具 `pack_forget()`
- 切换工具后必须 `update_idletasks()` + `_reposition_toolbar()`，否则高度变化后位置错误

### 贴图（_PinWindow）

- `_compose()` 用 PIL 重绘所有标注到裁剪图上，返回最终 PIL Image
- 创建独立 `Toplevel`，橙色边框（`highlightthickness=3`）
- 窗口 geometry 必须是 `图片尺寸 + BORDER*2`（边框占额外像素）
- 实例必须存入 `root._pin_windows[]`，防止 GC 回收导致图片消失（PhotoImage 被释放后图片变空白）
- 关闭时从列表移除自身，让 GC 正常回收

## 关键设计决策

**DPI 感知**：`ctypes.windll.shcore.SetProcessDpiAwareness(2)` 必须在 `import tkinter` 之前调用（`main.py` 最顶部）。否则高分辨率屏幕坐标偏移。

**线程安全**：`keyboard` 和 `pystray` 回调都在独立线程，所有 UI 操作必须通过 `root.after(0, fn)` 派发回主线程。

**截图时机**：`show()` 里必须先 `ImageGrab.grab()` 截图，再 `_build_window()` 创建遮罩，否则会截到遮罩本身。

**选区高亮实现**：不使用 stipple / alpha 窗口（Windows 兼容性差）。预生成变暗版截图（`ImageEnhance.Brightness`），拖拽时裁剪四块暗图贴到选区外四个区域，选区内显示原图。

**控制柄 vs 标注工具互斥**：`_edit_press` 里，只有 Move 工具才检测控制柄命中。其他工具点击选区内一律走标注流程，避免误触发 `_start_adjust` → 工具栏被 `withdraw`。

**马赛克撤销用快照方案**：`paste()` 是破坏性操作，直接修改 `self._full_img` 像素。每次马赛克前存整张图的快照，撤销时恢复并重绘。

**复制剪贴板**：`win32clipboard.SetClipboardData(CF_DIB, bmp_data[14:])` 直接写入 BMP 格式（去掉 14 字节文件头）。不依赖 PowerShell，无黑窗口，无延迟。禁止改回 PowerShell 方案。

**Canvas 布局用 pack**：Canvas 必须用 `pack` 并明确指定 `width/height`，`place` 布局不约束窗口尺寸，tkinter 会自动收缩截图。

**单实例锁**：`msvcrt.locking()` 文件锁，进程退出时自动释放，比 bat 里的 tasklist 检测可靠。

## 历史 Bug 记录

| # | 现象 | 根因 | 修复 |
|---|------|------|------|
| 1 | start.bat 闪退 | 工作目录错误，找不到 snip 包 | `cd /d "%~dp0"` + `os.chdir` |
| 2 | 黑窗口不关闭 | `python start /b` 挂起 | 改为 `start "" pythonw main.py` |
| 3 | 多实例 | bat 里 tasklist 检测失效 | Python 内 `msvcrt.locking()` 文件锁 |
| 4 | 复制有黑窗口卡顿 | PowerShell 子进程 | 改用 `pywin32` CF_DIB 直写剪贴板 |
| 5 | 截图变小 | geometry 只设位置不设尺寸；Canvas 用 place | Canvas 改 pack；geometry 加宽高 |
| 6 | 切换工具后工具栏消失 | 控制柄检测优先级最高，点选区内误触发 `_start_adjust` → `withdraw` | 标注工具模式下跳过控制柄检测 |
| 7 | 贴图后图片消失 | `_PinWindow` 无引用被 GC，`_tk_img` 释放 | 存入 `root._pin_windows[]` |
| 8 | 贴图边框裁剪图片 | 窗口 geometry 未含 `highlightthickness` | geometry 加 `BORDER*2` |
| 9 | 撤销删错标注 | `find_withtag('annotation')` 顺序不可靠 | 每个标注存 `canvas_id`，精确删除 |

## 回归测试清单

每次修改后必须验证：

1. `Ctrl+Alt+A` 触发截图，选区外变暗，选区内高亮
2. 选区调整：控制柄拖动调整大小，选区内拖动移动位置（Move 工具下）
3. 所有工具按钮可见（✥ T → □ ▦ ↩ 📌 💾 ✓ ✕），切换后工具栏**始终显示**
4. Move 拖动时工具栏隐藏，松手后恢复
5. 文字：点击输入，Enter 确认，文字可拖动位置，Ctrl+Z 撤销
6. 箭头/矩形：拖拽绘制，Ctrl+Z 撤销
7. 马赛克：拖拽打码，Ctrl+Z 完全恢复（图片还原）
8. 贴图（📌）：overlay 关闭，橙色边框窗口出现在选区位置，可拖动，双击/右键关闭
9. 多次贴图可同时存在，互不干扰
10. 保存：弹出文件对话框，默认桌面，文件写入成功
11. 复制：overlay 关闭，粘贴到其他应用验证内容含标注
12. 点击选区外重新绘制：标注清空，工具栏随之销毁重建

## 语言要求

所有代码注释、用户提示文字使用**中文**，回复也使用中文。
