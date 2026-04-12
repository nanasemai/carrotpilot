#!/bin/bash

# Carrotpilot项目启动脚本
# 用于终端环境启动，监控控制台输出

# 项目根目录
PROJECT_ROOT="$(realpath "$(dirname "$0")/..")"

echo "=========================================="
echo "  Carrotpilot 启动脚本"
echo "=========================================="
echo "项目根目录: $PROJECT_ROOT"
echo ""

# 清理残留进程
echo "[INFO] 清理残留进程..."
pkill -f -9 "(modeld|camerad|ui|controls|manager)" 2>/dev/null || true
sleep 2

# 切换到项目目录
cd "$PROJECT_ROOT" || {
    echo "[ERROR] 无法切换到项目目录: $PROJECT_ROOT"
    exit 1
}

# 确保必要目录存在
echo "[INFO] 确保必要目录存在..."
mkdir -p "$PROJECT_ROOT/data/params/d"
mkdir -p "/tmp/openpilot"

# 设置默认语言（如果未设置）
if [ ! -f "$PROJECT_ROOT/data/params/d/LanguageSetting" ]; then
    echo -n "main_en" > "$PROJECT_ROOT/data/params/d/LanguageSetting"
    echo "[INFO] 设置默认语言为: main_en"
fi

# 启动项目
echo "[INFO] 启动Carrotpilot..."
echo "=========================================="
echo ""
echo "按 Ctrl+C 退出"
echo ""

# 使用项目的主启动脚本，自动处理依赖和环境配置
bash ./launch_chffrplus.sh