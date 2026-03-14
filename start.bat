@echo off
chcp 65001 >nul
title my-snipaste 截图工具

echo ====================================
echo   my-snipaste 截图工具 启动中...
echo ====================================
echo.

:: 检查 Python 是否已安装
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 Python！
    echo.
    echo 请先安装 Python 3.8 或更高版本：
    echo https://www.python.org/downloads/
    echo.
    echo 安装时请勾选 "Add Python to PATH" 选项！
    echo.
    pause
    exit /b 1
)

echo [1/2] 正在检查并安装依赖...
pip install -r requirements.txt -q
if errorlevel 1 (
    echo.
    echo [警告] 依赖安装可能失败，尝试继续启动...
    echo 如果程序无法运行，请手动执行：pip install -r requirements.txt
    echo.
)

echo [2/2] 正在启动截图工具...
echo.
echo 程序已在后台运行，请查看系统托盘（右下角）。
echo 快捷键：Ctrl+Alt+A
echo.

:: 使用 pythonw 启动（不显示黑色 cmd 窗口）
:: 如果 pythonw 不可用，fallback 到 python
where pythonw >nul 2>&1
if errorlevel 1 (
    start /b python main.py
) else (
    start pythonw main.py
)

exit /b 0
