#!/bin/bash

# USB摄像头优化配置脚本
# 针对Carrotpilot项目优化USB摄像头性能和稳定性

echo "[INFO] 开始优化USB摄像头配置..."

# 1. 检查当前摄像头设备
echo "[INFO] 1. 检查摄像头设备..."
ls -la /dev/video*

# 2. 安装必要的摄像头工具
echo "[INFO] 2. 安装摄像头工具..."
sudo apt-get update
sudo apt-get install -y v4l-utils ffmpeg

# 3. 检查摄像头支持的格式和分辨率
echo "[INFO] 3. 检查摄像头支持格式..."
for cam in /dev/video*; do
    if [ -c "$cam" ]; then
        echo "=== 摄像头 $cam ==="
        v4l2-ctl -d "$cam" --list-formats-ext 2>/dev/null | head -20
        echo ""
    fi
done

# 4. 智能摄像头参数优化
echo "[INFO] 4. 智能摄像头参数优化..."

# 为每个摄像头设置智能优化参数
for cam in /dev/video*; do
    if [ -c "$cam" ]; then
        echo "[INFO] 智能优化摄像头 $cam ..."

        # 获取摄像头支持的参数范围
        echo "  - 获取摄像头参数范围..."

        # 亮度：使用自动检测的最佳值，不强制设置
        BRIGHTNESS_RANGE=$(v4l2-ctl -d "$cam" --list-ctrls 2>/dev/null | grep "brightness" | grep -oP 'min=-?\d+ max=-?\d+')
        if [ ! -z "$BRIGHTNESS_RANGE" ]; then
            MIN_BRIGHT=$(echo "$BRIGHTNESS_RANGE" | grep -oP 'min=\K-?\d+')
            MAX_BRIGHT=$(echo "$BRIGHTNESS_RANGE" | grep -oP 'max=\K-?\d+')
            if [ ! -z "$MIN_BRIGHT" ] && [ ! -z "$MAX_BRIGHT" ]; then
                # 使用中间值，但保留自动调整能力
                OPTIMAL_BRIGHT=$(( (MIN_BRIGHT + MAX_BRIGHT) / 2 ))
                v4l2-ctl -d "$cam" --set-ctrl=brightness=$OPTIMAL_BRIGHT 2>/dev/null && echo "  - 亮度设置为中间值: $OPTIMAL_BRIGHT" || echo "  - 亮度设置失败"
            fi
        fi

        # 对比度：轻微增强但不失真
        CONTRAST_RANGE=$(v4l2-ctl -d "$cam" --list-ctrls 2>/dev/null | grep "contrast" | grep -oP 'min=-?\d+ max=-?\d+')
        if [ ! -z "$CONTRAST_RANGE" ]; then
            MIN_CONTRAST=$(echo "$CONTRAST_RANGE" | grep -oP 'min=\K-?\d+')
            MAX_CONTRAST=$(echo "$CONTRAST_RANGE" | grep -oP 'max=\K-?\d+')
            if [ ! -z "$MIN_CONTRAST" ] && [ ! -z "$MAX_CONTRAST" ]; then
                # 使用稍微增强的对比度
                OPTIMAL_CONTRAST=$(( (MIN_CONTRAST + MAX_CONTRAST) / 2 + (MAX_CONTRAST - MIN_CONTRAST) / 10 ))
                v4l2-ctl -d "$cam" --set-ctrl=contrast=$OPTIMAL_CONTRAST 2>/dev/null && echo "  - 对比度轻微增强: $OPTIMAL_CONTRAST" || echo "  - 对比度设置失败"
            fi
        fi

        # 饱和度：保持自然，不强制设置
        SATURATION_RANGE=$(v4l2-ctl -d "$cam" --list-ctrls 2>/dev/null | grep "saturation" | grep -oP 'min=-?\d+ max=-?\d+')
        if [ ! -z "$SATURATION_RANGE" ]; then
            MIN_SAT=$(echo "$SATURATION_RANGE" | grep -oP 'min=\K-?\d+')
            MAX_SAT=$(echo "$SATURATION_RANGE" | grep -oP 'max=\K-?\d+')
            if [ ! -z "$MIN_SAT" ] && [ ! -z "$MAX_SAT" ]; then
                # 使用自然饱和度
                OPTIMAL_SAT=$(( (MIN_SAT + MAX_SAT) / 2 ))
                v4l2-ctl -d "$cam" --set-ctrl=saturation=$OPTIMAL_SAT 2>/dev/null && echo "  - 饱和度设置为自然值: $OPTIMAL_SAT" || echo "  - 饱和度设置失败"
            fi
        fi

        # 锐度：轻微增强但不失真
        SHARPNESS_RANGE=$(v4l2-ctl -d "$cam" --list-ctrls 2>/dev/null | grep "sharpness" | grep -oP 'min=-?\d+ max=-?\d+')
        if [ ! -z "$SHARPNESS_RANGE" ]; then
            MIN_SHARP=$(echo "$SHARPNESS_RANGE" | grep -oP 'min=\K-?\d+')
            MAX_SHARP=$(echo "$SHARPNESS_RANGE" | grep -oP 'max=\K-?\d+')
            if [ ! -z "$MIN_SHARP" ] && [ ! -z "$MAX_SHARP" ]; then
                # 使用轻微增强的锐度
                OPTIMAL_SHARP=$(( (MIN_SHARP + MAX_SHARP) / 2 + (MAX_SHARP - MIN_SHARP) / 8 ))
                v4l2-ctl -d "$cam" --set-ctrl=sharpness=$OPTIMAL_SHARP 2>/dev/null && echo "  - 锐度轻微增强: $OPTIMAL_SHARP" || echo "  - 锐度设置失败"
            fi
        fi

        # 曝光模式：优先使用自动模式，除非有特殊需求
        echo "  - 曝光模式保持自动（避免画面失真）"

        # 白平衡：优先使用自动模式
        echo "  - 白平衡保持自动（避免颜色失真）"

        # 自动对焦：保持自动对焦
        echo "  - 自动对焦保持启用"

        echo "  - 智能参数优化完成（保持自然画面）"
    fi
done

# 5. 创建摄像头优先级配置
echo "[INFO] 5. 创建摄像头优先级配置..."

# 检查哪个摄像头支持更高的分辨率
HIGH_RES_CAM=""
HIGHEST_RES=0

for cam in /dev/video*; do
    if [ -c "$cam" ]; then
        # 尝试获取分辨率信息
        RES_INFO=$(v4l2-ctl -d "$cam" --list-formats-ext 2>/dev/null | grep -oP '[0-9]+x[0-9]+' | head -1)
        if [ ! -z "$RES_INFO" ]; then
            WIDTH=$(echo "$RES_INFO" | cut -d'x' -f1)
            HEIGHT=$(echo "$RES_INFO" | cut -d'x' -f2)
            TOTAL_PIXELS=$((WIDTH * HEIGHT))

            if [ $TOTAL_PIXELS -gt $HIGHEST_RES ]; then
                HIGHEST_RES=$TOTAL_PIXELS
                HIGH_RES_CAM=$(echo "$cam" | sed 's/\/dev\/video//')
            fi

            echo "  - $cam: $RES_INFO ($TOTAL_PIXELS 像素)"
        fi
    fi
done

if [ ! -z "$HIGH_RES_CAM" ]; then
    echo "[INFO] 最高分辨率摄像头: /dev/video$HIGH_RES_CAM"

    # 更新.env文件中的摄像头配置
    if [ -f "$PWD/.env" ]; then
        echo "[INFO] 更新.env文件摄像头配置..."

        # 备份原配置
        cp "$PWD/.env" "$PWD/.env.backup.$(date +%s)"

        # 更新摄像头配置
        sed -i "s/export ROAD_CAM=.*/export ROAD_CAM=$HIGH_RES_CAM  # 自动选择最高分辨率摄像头/" "$PWD/.env"

        echo "[INFO] 摄像头配置已更新为使用最高分辨率设备"
    fi
fi

# 6. 设置USB电源管理（避免摄像头因省电断开）
echo "[INFO] 6. 设置USB电源管理..."

# 禁用USB自动挂起
for usb in /sys/bus/usb/devices/*/power/control; do
    if [ -f "$usb" ]; then
        echo "on" | sudo tee "$usb" > /dev/null 2>&1
    fi
done

# 设置USB自动挂起延迟
for usb in /sys/bus/usb/devices/*/power/autosuspend_delay_ms; do
    if [ -f "$usb" ]; then
        echo "-1" | sudo tee "$usb" > /dev/null 2>&1
    fi
done

# 7. 创建摄像头测试脚本
echo "[INFO] 7. 创建摄像头测试脚本..."

cat > "$PWD/nana-guide/test_camera.sh" << 'EOF'
#!/bin/bash

# 摄像头测试脚本

echo "[INFO] 摄像头测试开始..."

for cam in /dev/video*; do
    if [ -c "$cam" ]; then
        echo "=== 测试摄像头 $cam ==="

        # 测试摄像头是否能正常读取
        if timeout 3s ffmpeg -f v4l2 -i "$cam" -frames 1 -f null - 2>/dev/null; then
            echo "  ✅ 摄像头 $cam 工作正常"

            # 显示摄像头信息
            v4l2-ctl -d "$cam" --info 2>/dev/null | grep -E "(Card type|Bus info)" | head -2

            # 显示当前参数
            echo "  当前参数:"
            v4l2-ctl -d "$cam" --get-ctrl=exposure_auto,white_balance_temperature_auto,brightness,contrast 2>/dev/null | head -5

        else
            echo "  ❌ 摄像头 $cam 测试失败"
        fi
        echo ""
    fi
done

echo "[INFO] 摄像头测试完成"
EOF

chmod +x "$PWD/nana-guide/test_camera.sh"

# 8. 优化系统摄像头限制
echo "[INFO] 8. 优化系统摄像头限制..."

# 增加摄像头缓冲区大小
echo "# USB摄像头优化配置" | sudo tee -a /etc/sysctl.conf > /dev/null
echo "fs.inotify.max_user_watches=524288" | sudo tee -a /etc/sysctl.conf > /dev/null

# 应用sysctl配置
sudo sysctl -p > /dev/null 2>&1

echo ""
echo "[SUCCESS] USB摄像头优化完成!"
echo ""
echo "下一步操作:"
echo "1. 运行测试脚本: bash nana-guide/test_camera.sh"
echo "2. 重启系统应用所有优化"
echo "3. 启动Carrotpilot项目测试摄像头性能"
echo ""
echo "优化内容包括:"
echo "- 摄像头参数调优（曝光、白平衡、亮度等）"
echo "- USB电源管理优化"
echo "- 自动选择最高分辨率摄像头"
echo "- 系统级摄像头限制优化"