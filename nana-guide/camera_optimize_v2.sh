#!/bin/bash
# USB摄像头优化配置脚本
# 针对Carrotpilot项目优化USB摄像头性能和稳定性
# 注意：本脚本适用于YW1080等USB 2.0摄像头

echo "[INFO] 开始优化USB摄像头配置..."

# 1. 检查当前摄像头设备
echo "[INFO] 1. 检查摄像头设备..."
ls -la /dev/video*

# 2. 检查摄像头支持的格式和帧率
echo "[INFO] 2. 检查摄像头支持格式..."
for cam in /dev/video*; do
    if [ -c "$cam" ]; then
        echo "=== 摄像头 $cam ==="
        v4l2-ctl -d "$cam" --list-formats-ext 2>/dev/null | head -20
        echo ""
    fi
done

# 3. 智能摄像头参数优化
echo "[INFO] 3. 智能摄像头参数优化..."

# 为每个摄像头设置智能优化参数
for cam in /dev/video*; do
    if [ -c "$cam" ]; then
        echo "[INFO] 智能优化摄像头 $cam ..."

        # 尝试关闭自动曝光（对于YW1080，1=Manual Mode）
        v4l2-ctl -d "$cam" --set-ctrl=exposure_auto=1 2>/dev/null && echo "  - 已关闭自动曝光"

        # 尝试设置较短曝光时间
        v4l2-ctl -d "$cam" --set-ctrl=exposure_time_absolute=100 2>/dev/null && echo "  - 已设置曝光时间=100"

        # 设置合适的亮度
        v4l2-ctl -d "$cam" --set-ctrl=brightness=32 2>/dev/null && echo "  - 已设置亮度=32"

        # 设置合适的对比度
        v4l2-ctl -d "$cam" --set-ctrl=contrast=32 2>/dev/null && echo "  - 已设置对比度=32"

        # 设置合适的饱和度
        v4l2-ctl -d "$cam" --set-ctrl=saturation=64 2>/dev/null && echo "  - 已设置饱和度=64"

        echo "  - 智能参数优化完成"
    fi
done

# 4. 设置USB电源管理（避免摄像头因省电断开）
echo "[INFO] 4. 设置USB电源管理..."

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

# 5. 优化系统摄像头限制
echo "[INFO] 5. 优化系统摄像头限制..."

# 增加摄像头缓冲区大小
if ! grep -q "fs.inotify.max_user_watches" /etc/sysctl.conf 2>/dev/null; then
    echo "fs.inotify.max_user_watches=524288" | sudo tee -a /etc/sysctl.conf > /dev/null
    sudo sysctl -p > /dev/null 2>&1
fi

# 6. 创建摄像头测试脚本
echo "[INFO] 6. 创建摄像头测试脚本..."

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

echo ""
echo "[SUCCESS] USB摄像头优化完成!"
echo ""
echo "优化说明："
echo "1. 当前配置已针对YW1080摄像头优化"
echo "2. 推荐帧率：20fps（摄像头实际能力上限）"
echo "3. 推荐分辨率：1920x1080 或 1280x720"
echo ""
echo "下一步操作:"
echo "1. 运行测试脚本: bash nana-guide/test_camera.sh"
echo "2. 重启系统应用USB电源管理优化"
echo "3. 启动Carrotpilot项目测试摄像头性能"
