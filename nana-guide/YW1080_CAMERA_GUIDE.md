# YW1080 USB摄像头配置指南

## 摄像头基本信息

| 属性 | 值 |
|------|-----|
| 型号 | YW1080 (Z-Star Venus USB2.0 Camera) |
| 驱动 | uvcvideo |
| 接口 | USB 2.0 |
| 设备路径 | /dev/video0, /dev/video1 |

## 技术规格

### 支持的分辨率和帧率

#### YUYV格式（未压缩）
| 分辨率 | 最大帧率 | 备注 |
|--------|----------|------|
| 1920×1080 | 5 fps | 不推荐 |
| 1280×720 | 7.5 fps | 不推荐 |
| 640×480 | 30 fps | 可用但分辨率低 |

#### **MJPEG格式（压缩，推荐）**
| 分辨率 | 最大帧率 | 推荐 |
|--------|----------|------|
| 1920×1080 | **20 fps** | ✅ 推荐 |
| 1280×720 | **20 fps** | ✅ 推荐 |
| 640×480 | 30 fps | 分辨率太低 |

## 性能测试结果

### 实际帧率测试
```
测试条件：1080p, MJPEG格式
目标帧率：30 fps
实际帧率：18-20 fps
结论：摄像头硬件限制，无法达到30fps
```

### 帧率受限原因分析

**已排除的因素**：
- ❌ USB 2.0带宽瓶颈（实际带宽足够）
- ❌ 自动曝光时间过长（已测试手动曝光）
- ❌ USB数据流错误（无报错）
- ❌ 驱动程序问题（uvcvideo正常）

**确认的原因**：
- ✅ **硬件限制**：Sensor或固件将最大帧率限制在20fps
- ✅ 该摄像头为消费级产品，非工业级设计

## 最佳配置方案

### 推荐配置（已优化）

```python
# tools/webcam/camerad.py 中的配置
camera_configs = {
    "roadCameraState": {
        "width": 1920,
        "height": 1080,
        "fps": 20,  # 与摄像头实际能力匹配
        "format": "mjpeg"  # 使用压缩格式节省带宽
    }
}
```

### 环境变量配置

```bash
# .env 文件
export USE_WEBCAM=1
export ROAD_CAM=0
```

## 摄像头参数优化

### 可调参数

| 参数 | 当前值 | 推荐值 | 说明 |
|------|--------|--------|------|
| exposure_auto | 3 (Auto) | **1 (Manual)** | 关闭自动曝光 |
| exposure_time_absolute | 384 | 100-150 | 手动设置曝光时间 |
| brightness | 0 | 32 | 适当提高亮度 |
| contrast | 2 | 32 | 适当提高对比度 |
| saturation | 64 | 64 | 保持默认 |
| sharpness | 2 | 3 | 轻微提高锐度 |

### 不可调参数
- ❌ gain（增益）：该摄像头不支持
- ❌ 压缩率：无法调整JPEG质量

### 设置命令

```bash
# 关闭自动曝光
v4l2-ctl -d /dev/video0 --set-ctrl=exposure_auto=1

# 设置曝光时间
v4l2-ctl -d /dev/video0 --set-ctrl=exposure_time_absolute=100

# 设置图像参数
v4l2-ctl -d /dev/video0 --set-ctrl=brightness=32
v4l2-ctl -d /dev/video0 --set-ctrl=contrast=32
v4l2-ctl -d /dev/video0 --set-ctrl=saturation=64
v4l2-ctl -d /dev/video0 --set-ctrl=sharpness=3
```

## 快速测试

### 测试帧率
```bash
# 使用v4l2-ctl测试
v4l2-ctl -d /dev/video0 --set-fmt-video=width=1920,height=1080,pixelformat=MJPG \
    --stream-mmap --stream-count=100 --stream-to=/dev/null

# 使用ffmpeg测试
ffmpeg -f v4l2 -framerate 20 -video_size 1920x1080 -input_format mjpeg \
    -i /dev/video0 -t 3 -f null -
```

### 查看当前配置
```bash
# 查看所有参数
v4l2-ctl -d /dev/video0 --list-ctrls

# 查看当前格式
v4l2-ctl -d /dev/video0 --get-fmt-video
```

## 常见问题

### Q1: 无法达到30fps？
**A**: 该摄像头硬件限制，最大约20fps。建议使用20fps目标配置。

### Q2: 画面太暗怎么办？
**A**: 提高brightness和contrast值，或改善环境光照。该摄像头不支持增益控制。

### Q3: 帧率不稳定？
**A**: 尝试：1) 使用USB 3.0端口；2) 关闭其他USB设备；3) 启用USB电源管理。

### Q4: 摄像头被占用？
**A**: 检查是否有其他进程使用：`lsof /dev/video0`

## USB电源管理优化

为避免摄像头因USB省电断开，可以优化电源管理：

```bash
# 禁用USB自动挂起
for usb in /sys/bus/usb/devices/*/power/control; do
    echo "on" | sudo tee "$usb"
done
```

## 升级建议

如果需要更高帧率（30fps+），建议更换以下摄像头：

1. **罗技C920/C930e**
   - 支持1080p@30fps
   - USB 3.0接口
   - 价格：¥300-500

2. **工业级USB 3.0摄像头**
   - 支持高帧率
   - 可调增益
   - 价格：¥500-2000

## 文件说明

| 文件 | 说明 |
|------|------|
| `YW1080_CAMERA_GUIDE.md` | 本文档 |
| `camera_optimize_v2.sh` | 针对YW1080的优化脚本 |
| `test_camera.sh` | 摄像头测试脚本 |

## 相关文档

- [X86_USAGE_GUIDE.md](./X86_USAGE_GUIDE.md) - 完整使用指南
- [camera_optimize.sh](./camera_optimize.sh) - 通用摄像头优化脚本
