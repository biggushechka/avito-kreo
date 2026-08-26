@echo off
cd /d "%~dp0"
title Generator Kreo - Web Service

echo ===================================================
echo   Starting Generator Kreo (Ad Marketing Generator)  
echo ===================================================

:: Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in your PATH.
    echo Please install Python 3.9+ and try again.
    pause
    exit /b 1
)

:: Create virtual environment if it doesn't exist
if not exist .venv (
    echo [INFO] Creating Python virtual environment in .venv folder...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
)

:: Activate virtual environment
echo [INFO] Activating virtual environment...
call .venv\Scripts\activate

:: Install/Upgrade dependencies
echo [INFO] Checking and installing dependencies...
pip install -r requirements.txt
if errorlevel 1 (
    echo [WARNING] Some dependencies failed to install. Retrying...
    pip install -r requirements.txt
)

:: Start FastAPI server
echo [INFO] Starting FastAPI server on http://127.0.0.1:8000...
echo [INFO] The web interface will open automatically.
python main.py

if errorlevel 1 (
    echo [ERROR] Server stopped with error.
    pause
)
