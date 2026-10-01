@echo off
REM EVK-F9P GPS Display Program - Batch Launcher
REM This batch file provides quick launch of GPS/RTK programs

setlocal enabledelayedexpansion

set PYTHON=C:\Users\keita\AppData\Local\Programs\Python\Python311\python.exe
set WORKDIR=%~dp0

echo.
echo ========================================
echo EVK-F9P GPS & RTK Control Program
echo ========================================
echo.
echo 1. GPS Display (gps_display.py)
echo 2. RTK Input - Interactive Mode
echo 3. RTK Input with rtk2go.com
echo 4. Debug Serial (debug_serial.py)
echo 5. Exit
echo.

set /p choice="Select option (1-5): "

if "%choice%"=="1" (
    echo.
    echo Running GPS Display...
    "%PYTHON%" "%WORKDIR%gps_display.py"
) else if "%choice%"=="2" (
    echo.
    echo Running RTK Input (Interactive Mode)...
    "%PYTHON%" "%WORKDIR%rtk_input.py" --interactive
) else if "%choice%"=="3" (
    echo.
    echo Running RTK Input with rtk2go.com
    echo.
    set /p port="Enter serial port [COM13]: "
    if "!port!"=="" set port=COM13
    
    set /p server="Enter NTRIP server [rtk2go.com]: "
    if "!server!"=="" set server=rtk2go.com
    
    set /p mountpoint="Enter mountpoint (e.g., YMSK): "
    if "!mountpoint!"=="" (
        echo ERROR: Mountpoint required!
        pause
        exit /b 1
    )
    
    echo.
    echo Connecting to %server%/%mountpoint%...
    "%PYTHON%" "%WORKDIR%rtk_input.py" ^
        --port !port! ^
        --server !server! ^
        --mountpoint !mountpoint! ^
        --interactive
) else if "%choice%"=="4" (
    echo.
    echo Running Debug Serial...
    "%PYTHON%" "%WORKDIR%debug_serial.py"
) else if "%choice%"=="5" (
    echo.
    echo Exiting...
    exit /b 0
) else (
    echo.
    echo Invalid option!
    pause
    exit /b 1
)

pause
