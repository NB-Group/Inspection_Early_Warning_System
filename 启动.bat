@echo off
chcp 65001 >nul
title 消污除腐 - 人脸识别预警系统

echo.
echo ========================================
echo   消污除腐 - 人脸识别预警系统
echo ========================================
echo.

:: 检查Python是否安装
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到Python，请先安装Python 3.8或更高版本
    echo.
    pause
    exit /b 1
)

:: 检查依赖是否安装
echo [信息] 检查依赖...
python -c "import cv2" >nul 2>&1
if errorlevel 1 (
    echo [警告] 检测到依赖未安装，正在安装...
    echo.
    pip install -r requirements.txt
    if errorlevel 1 (
        echo [错误] 依赖安装失败
        pause
        exit /b 1
    )
)

:: 启动程序
echo [信息] 启动程序...
echo.
python main.py

if errorlevel 1 (
    echo.
    echo [错误] 程序异常退出
    pause
)



