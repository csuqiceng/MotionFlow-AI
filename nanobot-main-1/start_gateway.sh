#!/usr/bin/env bash
# 一键启动 gateway — 自包含,不依赖旧项目路径
cd "$(dirname "$0")"

export ROBOT_AI_BACKEND="zmotion_readonly"
export ROBOT_CONTROLLER_HOST="10.168.3.21"
export ROBOT_ZMOTION_WRAPPER_PATH="$(pwd)/vendor/zmotion/zauxdllPython.py"
export ROBOT_ZMOTION_DLL_DIR="$(pwd)/vendor/zmotion"
export ROBOT_AI_FIRST_TEST_MAX_DELTA=2000
export ROBOT_AI_FIRST_TEST_MAX_PERCENT=100

echo "Starting gateway..."
echo "  Backend: $ROBOT_AI_BACKEND"
echo "  Controller: $ROBOT_CONTROLLER_HOST"
echo "  SDK: $ROBOT_ZMOTION_DLL_DIR"
echo ""

.venv-robot-desktop/Scripts/python.exe -m nanobot gateway --foreground
