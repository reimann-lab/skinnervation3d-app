@echo off
setlocal enabledelayedexpansion

:: ─────────────────────────────────────────────────────────────────────────────
::  SkInnervation3D — Windows installer launcher
::  Right-click this file → "Run as administrator"  (or just double-click)
:: ─────────────────────────────────────────────────────────────────────────────

title SkInnervation3D Installer

echo.
echo ============================================================
echo   SkInnervation3D - Installer Launcher
echo ============================================================
echo.

:: ── Check install.py is present ──────────────────────────────────────────────
if not exist "%~dp0install.py" (
    echo ERROR: install.py not found in the same folder as this script.
    echo Please download both files ^(install.bat AND install.py^) and try again.
    pause
    exit /b 1
)

:: ── Try to find Python 3.8+ on PATH ─────────────────────────────────────────
set "PYTHON="

for %%P in (python python3) do (
    if "!PYTHON!"=="" (
        %%P --version >nul 2>&1
        if !errorlevel! == 0 (
            for /f "tokens=2 delims= " %%V in ('%%P --version 2^>^&1') do (
                set "VER=%%V"
            )
            :: Accept anything starting with 3.
            if "!VER:~0,2!"=="3." (
                set "PYTHON=%%P"
            )
        )
    )
)

:: ── Also check common Miniforge / Miniconda / Anaconda locations ──────────────
if "!PYTHON!"=="" (
    for %%L in (
        "%USERPROFILE%\miniforge3\python.exe"
        "%USERPROFILE%\miniconda3\python.exe"
        "%USERPROFILE%\anaconda3\python.exe"
        "C:\ProgramData\miniforge3\python.exe"
        "C:\ProgramData\miniconda3\python.exe"
    ) do (
        if "!PYTHON!"=="" (
            if exist %%L (
                set "PYTHON=%%~L"
            )
        )
    )
)

:: ── Bootstrap Miniforge if still no Python ───────────────────────────────────
if "!PYTHON!"=="" (
    echo Python 3 not found. Downloading and installing Miniforge...
    echo.

    set "MF_URL=https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Windows-x86_64.exe"
    set "MF_INSTALLER=%TEMP%\Miniforge3-installer.exe"
    set "MF_TARGET=%USERPROFILE%\miniforge3"

    echo Downloading from:
    echo   !MF_URL!
    echo.

    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
        "Invoke-WebRequest -Uri '!MF_URL!' -OutFile '!MF_INSTALLER!' -UseBasicParsing"

    if not exist "!MF_INSTALLER!" (
        echo ERROR: Download failed. Please check your internet connection.
        echo Alternatively, install Miniforge manually from:
        echo   https://github.com/conda-forge/miniforge
        pause
        exit /b 1
    )

    echo Installing Miniforge silently to !MF_TARGET! ...
    echo ^(This may take a few minutes^)
    echo.

    :: NSIS silent install — /D must be last and use no quotes
    "!MF_INSTALLER!" /S /D=!MF_TARGET!

    :: Wait for installer to finish
    timeout /t 5 /nobreak >nul

    set "PYTHON=!MF_TARGET!\python.exe"

    if not exist "!PYTHON!" (
        echo ERROR: Miniforge installation failed.
        echo Please install it manually from https://github.com/conda-forge/miniforge
        echo and then re-run this installer.
        pause
        exit /b 1
    )

    echo ✓ Miniforge installed → !MF_TARGET!
    echo.
)

echo Using Python: !PYTHON!
for /f "tokens=*" %%V in ('"!PYTHON!" --version') do echo          %%V
echo.

:: ── Run the Python installer ─────────────────────────────────────────────────
"!PYTHON!" "%~dp0install.py"
set "EXIT_CODE=!errorlevel!"

if !EXIT_CODE! neq 0 (
    echo.
    echo ============================================================
    echo   Installation failed ^(exit code !EXIT_CODE!^).
    echo   Please scroll up to read the error message.
    echo ============================================================
) else (
    echo.
    echo ============================================================
    echo   Installation finished successfully!
    echo ============================================================
)

echo.
pause
exit /b !EXIT_CODE!
