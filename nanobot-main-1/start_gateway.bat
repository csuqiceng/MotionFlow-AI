@echo off
REM 一键启动 gateway — 自包含,不依赖旧项目路径
cd /d "%~dp0"

set ROBOT_AI_BACKEND=zmotion_readonly
set ROBOT_CONTROLLER_HOST=10.168.3.21
set ROBOT_ZMOTION_WRAPPER_PATH=%cd%\vendor\zmotion\zauxdllPython.py
set ROBOT_ZMOTION_DLL_DIR=%cd%\vendor\zmotion
REM Gateway shares ONE ZAux connection across status reads + motion writes (like
REM the legacy Qt app). CLI/tests don't set this.
set ROBOT_AI_SHARED_CLIENT=1
set ROBOT_AI_FIRST_TEST_MAX_DELTA=2000
set ROBOT_AI_FIRST_TEST_MAX_PERCENT=100

echo Starting gateway...
echo   Backend: %ROBOT_AI_BACKEND%
echo   Controller: %ROBOT_CONTROLLER_HOST%
echo   SDK: %ROBOT_ZMOTION_DLL_DIR%
echo.

desktop\.build-venv\Scripts\python.exe -m nanobot gateway --foreground --config desktop\electron\default-config.json
