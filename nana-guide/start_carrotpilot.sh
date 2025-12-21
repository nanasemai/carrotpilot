#!/bin/bash

# Carrotpilot项目启动脚本
# 用于切换到项目目录，激活虚拟环境并启动项目

# 项目根目录
PROJECT_ROOT="$(realpath "$(dirname "$0")/..")"

echo "[INFO] 启动Carrotpilot项目..."
echo "[INFO] 项目根目录: $PROJECT_ROOT"

# 切换到项目目录
cd "$PROJECT_ROOT"
if [ $? -ne 0 ]; then
    echo "[ERROR] 无法切换到项目目录: $PROJECT_ROOT"
    exit 1
fi

# 激活虚拟环境
if [ -f ".venv/bin/activate" ]; then
    echo "[INFO] 激活虚拟环境..."
    source ".venv/bin/activate"
    if [ $? -ne 0 ]; then
        echo "[ERROR] 无法激活虚拟环境"
        exit 1
    fi
else
    echo "[WARNING] 虚拟环境不存在或未找到激活脚本"
    echo "[INFO] 继续使用当前环境启动..."
fi

# 设置必要的环境变量
export PYTHONPATH="$PROJECT_ROOT"
export ZMQ=1
export USE_WEBCAM=1
export LOG_READABLE=1

# 确保必要目录存在
mkdir -p "$PROJECT_ROOT/data/params/d"
mkdir -p "/tmp/openpilot"

# 启动项目
echo "[INFO] 执行启动脚本..."

./launch_chffrplus.sh

exit $?