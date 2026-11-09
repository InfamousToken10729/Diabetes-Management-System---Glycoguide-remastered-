@echo off
setlocal enabledelayedexpansion

title GlycoGuide Remastered — Executable Builder
echo ====================================================================
echo      GlycoGuide Remastered — Standalone Windows (.exe) Builder
echo ====================================================================
echo.

set ROOT_DIR=%~dp0
cd /d "%ROOT_DIR%"

:: Check for PyInstaller
python -m pip show pyinstaller >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [1/3] Installing PyInstaller...
    python -m pip install pyinstaller
) else (
    echo [1/3] PyInstaller is ready.
)

echo [2/3] Building standalone GlycoGuide.exe...
python -m PyInstaller --noconfirm --clean --onefile ^
    --name "GlycoGuide" ^
    --add-data "static;static" ^
    --add-data "templates;templates" ^
    --icon "static/img/favicon.ico" ^
    app.py

if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] PyInstaller compilation failed.
    pause
    exit /b 1
)

:: Move exe to remastered root
if exist "dist\GlycoGuide.exe" (
    copy /y "dist\GlycoGuide.exe" "%ROOT_DIR%GlycoGuide.exe" >nul
)

:: Clean up build intermediates
if exist "build" rd /s /q "build"
if exist "dist" rd /s /q "dist"
if exist "GlycoGuide.spec" del /f /q "GlycoGuide.spec"

echo.
echo ====================================================================
echo [3/3] Build Complete!
echo Standalone Executable created: %ROOT_DIR%GlycoGuide.exe
echo You can now run GlycoGuide.exe directly on any Windows PC!
echo ====================================================================
echo.
pause
