@echo off
chcp 65001 >nul
cd /d "%~dp0"

:: 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 Python，请先安装 Python 3.8+
    echo 安装时请勾选 "Add Python to PATH"
    pause
    exit /b 1
)

:: 安装依赖（失败则报错退出，不静默继续）
echo [1/2] 检查依赖...
python -m pip install -r requirements.txt --disable-pip-version-check -q
if errorlevel 1 (
    echo.
    echo [错误] 依赖安装失败，请检查网络连接后重试
    echo 若在内网环境，请联系管理员配置 pip 镜像源
    pause
    exit /b 1
)

echo [2/2] 启动程序...

:: 启动程序（新窗口后台运行，本窗口立即关闭）
start "" pythonw main.py

exit
