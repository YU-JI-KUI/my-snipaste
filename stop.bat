@echo off
chcp 65001 >nul
title 关闭 my-snipaste

echo 正在关闭 my-snipaste...
taskkill /f /im pythonw.exe /fi "WINDOWTITLE eq my-snipaste*" >nul 2>&1
taskkill /f /im python.exe /fi "COMMANDLINE eq *main.py*" >nul 2>&1

echo 已关闭。
timeout /t 2 >nul
