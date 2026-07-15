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
echo The installer is in the release-build4 folder.
pause
exit /b 0
