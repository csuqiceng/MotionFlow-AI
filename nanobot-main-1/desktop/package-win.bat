@echo off
setlocal

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0package-win.ps1"
set "exitCode=%ERRORLEVEL%"

if not "%exitCode%"=="0" (
    echo.
    echo Packaging failed. Review the error above.
    pause
    exit /b %exitCode%
)

echo.
echo The verified Setup.exe and SHA-256 file are in release-build4.
pause
exit /b 0
