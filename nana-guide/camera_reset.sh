#!/bin/bash

# 摄像头参数恢复脚本
# 用于撤销之前的参数设置，恢复摄像头到默认状态

echo "[INFO] 开始恢复摄像头默认参数..."

# 1. 检查当前摄像头设备
echo "[INFO] 1. 检查摄像头设备..."
ls -la /dev/video*

# 2. 恢复每个摄像头的参数
for cam in /dev/video*; do
    if [ -c "$cam" ]; then
        echo "[INFO] 恢复摄像头 $cam 默认参数..."
        
        # 恢复曝光模式为自动
        v4l2-ctl -d "$cam" --set-ctrl=exposure_auto=3 2>/dev/null && echo "  - 曝光模式恢复为自动" || echo "  - 曝光模式恢复失败"
        
        # 恢复白平衡为自动
        v4l2-ctl -d "$cam" --set-ctrl=white_balance_temperature_auto=1 2>/dev/null && echo "  - 白平衡恢复为自动" || echo "  - 白平衡恢复失败"
        
        # 恢复自动对焦
        v4l2-ctl -d "$cam" --set-ctrl=focus_auto=1 2>/dev/null && echo "  - 自动对焦恢复为启用" || echo "  - 自动对焦恢复失败"
        
        # 重置亮度、对比度、饱和度、锐度为默认值
        v4l2-ctl -d "$cam" --set-ctrl=brightness=0 2>/dev/null && echo "  - 亮度重置为默认值" || echo "  - 亮度重置失败"
        v4l2-ctl -d "$cam" --set-ctrl=contrast=0 2>/dev/null && echo "  - 对比度重置为默认值" || echo "  - 对比度重置失败"
        v4l2-ctl -d "$cam" --set-ctrl=saturation=0 2>/dev/null && echo "  - 饱和度重置为默认值" || echo "  - 饱和度重置失败"
        v4l2-ctl -d "$cam" --set-ctrl=sharpness=0 2>/dev/null && echo "  - 锐度重置为默认值" || echo "  - 锐度重置失败"
        
        echo "  - 摄像头 $cam 参数恢复完成"
    fi
done

# 3. 恢复.env文件中的摄像头配置（如果之前被修改）
if [ -f "$PWD/.env" ]; then
    echo "[INFO] 检查.env文件摄像头配置..."
    
    # 检查是否有备份文件
    BACKUP_FILES=$(ls "$PWD/.env.backup."* 2>/dev/null | head -1)
    if [ ! -z "$BACKUP_FILES" ]; then
        echo "[INFO] 发现备份文件，恢复原始配置..."
        cp "$BACKUP_FILES" "$PWD/.env"
        echo "[INFO] .env文件已恢复到原始状态"
    else
        echo "[INFO] 未发现备份文件，保持当前配置"
    fi
fi

# 4. 创建摄像头测试脚本（测试恢复后的效果）
echo "[INFO] 创建摄像头测试脚本..."

cat > "$PWD/nana-guide/test_camera_after_reset.sh" << 'EOF'
#!/bin/bash

# 摄像头恢复后测试脚本

echo "[INFO] 摄像头恢复后测试开始..."

for cam in /dev/video*; do
    if [ -c "$cam" ]; then
        echo "=== 测试摄像头 $cam ==="
        
        # 显示当前参数状态
        echo "  当前参数状态:"
        v4l2-ctl -d "$cam" --get-ctrl=exposure_auto,white_balance_temperature_auto,brightness,contrast,saturation,sharpness 2>/dev/null | head -10
        
        # 测试摄像头是否能正常读取
        if timeout 3s ffmpeg -f v4l2 -i "$cam" -frames 1 -f null - 2>/dev/null; then
            echo "  ✅ 摄像头 $cam 工作正常"
        else
            echo "  ❌ 摄像头 $cam 测试失败"
        fi
        echo ""
    fi
done

echo "[INFO] 摄像头恢复后测试完成"
echo ""
echo "建议：重新启动Carrotpilot项目测试摄像头画面质量"
EOF

chmod +x "$PWD/nana-guide/test_camera_after_reset.sh"

echo ""
echo "[SUCCESS] 摄像头参数恢复完成!"
echo ""
echo "下一步操作:"
echo "1. 运行测试脚本: bash nana-guide/test_camera_after_reset.sh"
echo "2. 重新启动Carrotpilot项目"
echo "3. 检查摄像头画面是否恢复正常"
echo ""
echo "恢复内容包括:"
echo "- 曝光模式恢复为自动"
echo "- 白平衡恢复为自动"
echo "- 自动对焦恢复为启用"
echo "- 亮度、对比度、饱和度、锐度重置为默认值"
echo "- .env文件恢复到原始状态（如果存在备份）"