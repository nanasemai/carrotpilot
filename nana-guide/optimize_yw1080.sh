#!/bin/bash

# YW1080 USB摄像头专用优化脚本
# 针对Carrotpilot项目优化YW1080摄像头的性能和稳定性
# 注意：YW1080最大帧率约20fps，无法达到30fps

set -e

echo "=========================================="
echo "  YW1080 USB摄像头优化脚本"
echo "=========================================="
echo ""

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 检测摄像头
detect_camera() {
    echo "[INFO] 检测摄像头设备..."
    
    if [ ! -e /dev/video0 ]; then
        echo -e "${RED}[ERROR] 未检测到摄像头设备！${NC}"
        exit 1
    fi
    
    # 获取摄像头信息
    CAMERA_INFO=$(v4l2-ctl --all 2>/dev/null | grep -E "Card type|Bevice Caps" | head -2)
    echo -e "${GREEN}[OK] 检测到摄像头：${NC}"
    echo "$CAMERA_INFO"
    echo ""
}

# 优化摄像头参数
optimize_camera_params() {
    echo "[INFO] 优化摄像头参数..."
    echo ""
    
    CAM_DEVICE="/dev/video0"
    
    # 1. 设置MJPEG格式（必须的）
    echo "  1) 设置MJPEG格式..."
    v4l2-ctl -d "$CAM_DEVICE" --set-fmt-video=width=1920,height=1080,pixelformat=MJPG 2>/dev/null
    echo "     ✅ 已设置为1920x1080 MJPEG"
    
    # 2. 关闭自动曝光（关键步骤）
    echo "  2) 关闭自动曝光..."
    if v4l2-ctl -d "$CAM_DEVICE" --set-ctrl=exposure_auto=1 2>/dev/null; then
        echo "     ✅ 已关闭自动曝光（手动模式）"
    else
        echo "     ⚠️ 无法设置自动曝光模式"
    fi
    
    # 3. 设置曝光时间
    echo "  3) 设置曝光时间..."
    if v4l2-ctl -d "$CAM_DEVICE" --set-ctrl=exposure_time_absolute=100 2>/dev/null; then
        echo "     ✅ 曝光时间已设置为100"
    else
        echo "     ⚠️ 无法设置曝光时间"
    fi
    
    # 4. 优化图像参数
    echo "  4) 优化图像参数..."
    v4l2-ctl -d "$CAM_DEVICE" --set-ctrl=brightness=32 2>/dev/null && echo "     ✅ 亮度=32"
    v4l2-ctl -d "$CAM_DEVICE" --set-ctrl=contrast=32 2>/dev/null && echo "     ✅ 对比度=32"
    v4l2-ctl -d "$CAM_DEVICE" --set-ctrl=saturation=64 2>/dev/null && echo "     ✅ 饱和度=64"
    v4l2-ctl -d "$CAM_DEVICE" --set-ctrl=sharpness=3 2>/dev/null && echo "     ✅ 锐度=3"
    
    # 5. 关闭背光补偿（有时会降低帧率）
    v4l2-ctl -d "$CAM_DEVICE" --set-ctrl=backlight_compensation=0 2>/dev/null && echo "     ✅ 背光补偿=0"
    
    echo ""
}

# 优化USB电源管理
optimize_usb_power() {
    echo "[INFO] 优化USB电源管理..."
    
    # 检查是否有root权限
    if [ "$EUID" -ne 0 ]; then
        echo -e "${YELLOW}[WARNING] 需要root权限来优化USB电源管理${NC}"
        echo "         请手动运行：sudo $0 --usb-power"
        echo ""
        return
    fi
    
    # 禁用USB自动挂起
    for usb in /sys/bus/usb/devices/*/power/control; do
        if [ -f "$usb" ]; then
            echo "on" > "$usb" 2>/dev/null
        fi
    done
    
    # 设置USB自动挂起延迟
    for usb in /sys/bus/usb/devices/*/power/autosuspend_delay_ms; do
        if [ -f "$usb" ]; then
            echo "-1" > "$usb" 2>/dev/null
        fi
    done
    
    echo -e "${GREEN}[OK] USB电源管理优化完成${NC}"
    echo ""
}

# 测试摄像头帧率
test_camera_fps() {
    echo "[INFO] 测试摄像头帧率..."
    echo ""
    
    echo "  测试条件：1920x1080 MJPEG"
    echo "  预计帧率：18-20 fps（摄像头硬件限制）"
    echo ""
    
    # 清理可能占用摄像头的进程
    pkill -9 ffmpeg 2>/dev/null || true
    sleep 1
    
    # 测试帧率
    echo "  开始测试（3秒）..."
    echo "  ----------------------------------------"
    
    RESULT=$(timeout 4 ffmpeg -f v4l2 -framerate 20 -video_size 1920x1080 \
        -input_format mjpeg -i /dev/video0 -t 3 -f null - 2>&1 | grep "fps=")
    
    echo "  $RESULT"
    echo "  ----------------------------------------"
    echo ""
    
    # 解析结果
    if echo "$RESULT" | grep -q "fps=.*[0-9]\+\.[0-9]\+"; then
        FPS=$(echo "$RESULT" | grep -oP 'fps=\s*\K[0-9]+\.[0-9]+' | head -1)
        echo -e "  测试结果：${GREEN}${FPS} fps${NC}"
        
        # 判断是否达到预期
        if (( $(echo "$FPS >= 18" | bc -l) )); then
            echo -e "  状态：${GREEN}正常（符合预期）${NC}"
        else
            echo -e "  状态：${YELLOW}偏低${NC}"
        fi
    else
        echo -e "  ${YELLOW}无法准确解析帧率${NC}"
    fi
    echo ""
}

# 验证当前配置
verify_config() {
    echo "[INFO] 当前摄像头配置..."
    echo ""
    
    echo "  格式信息："
    v4l2-ctl -d /dev/video0 --get-fmt-video 2>/dev/null | grep -E "Width|Height|Pixel" | sed 's/^/    /'
    echo ""
    
    echo "  曝光设置："
    v4l2-ctl -d /dev/video0 -L 2>/dev/null | grep -E "exposure" | sed 's/^/    /'
    echo ""
}

# 显示使用说明
show_usage() {
    echo "用法: $0 [选项]"
    echo ""
    echo "选项:"
    echo "  all           执行所有优化（默认）"
    echo "  detect        仅检测摄像头"
    echo "  params        仅优化摄像头参数"
    echo "  usb-power     优化USB电源管理（需要root）"
    echo "  test          测试帧率"
    echo "  verify        验证当前配置"
    echo "  help          显示此帮助信息"
    echo ""
}

# 主程序
main() {
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    ROOT_DIR="$(dirname "$SCRIPT_DIR")"
    
    echo "工作目录: $ROOT_DIR"
    echo ""
    
    case "${1:-all}" in
        all)
            detect_camera
            verify_config
            optimize_camera_params
            optimize_usb_power
            test_camera_fps
            ;;
        detect)
            detect_camera
            ;;
        params)
            optimize_camera_params
            ;;
        usb-power)
            optimize_usb_power
            ;;
        test)
            test_camera_fps
            ;;
        verify)
            verify_config
            ;;
        help|--help|-h)
            show_usage
            exit 0
            ;;
        *)
            echo -e "${RED}未知选项: $1${NC}"
            show_usage
            exit 1
            ;;
    esac
    
    echo "=========================================="
    echo "  优化完成！"
    echo "=========================================="
    echo ""
    echo "注意事项："
    echo "1. YW1080摄像头最大帧率约20fps，无法达到30fps"
    echo "2. 当前配置已针对摄像头能力优化"
    echo "3. 如需更高帧率，建议更换USB 3.0摄像头"
    echo ""
}

# 运行主程序
main "$@"
