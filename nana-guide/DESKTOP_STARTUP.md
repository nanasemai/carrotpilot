# Carrotpilot 桌面自启动配置

这是一个更简单可靠的开机自启动方案，使用桌面环境自启动功能。

## 方法1：桌面启动器（推荐）

### 步骤1：创建桌面启动器

将桌面启动器文件复制到自启动目录：

```bash
# 复制到用户自启动目录
cp /home/ubuntu/carrotpilot/nana-guide/carrotpilot.desktop ~/.config/autostart/

# 如果目录不存在，创建它
mkdir -p ~/.config/autostart/
```

### 步骤2：修改启动器文件中的用户名

编辑桌面启动器文件，将 `ubuntu` 替换为您的实际用户名：

```bash
sed -i 's/ubuntu/your-username/g' ~/.config/autostart/carrotpilot.desktop
```

### 步骤3：设置权限

```bash
chmod +x ~/.config/autostart/carrotpilot.desktop
```

## 方法2：手动添加到启动应用程序

### 步骤1：打开启动应用程序

在Ubuntu中搜索"启动应用程序"并打开。

### 步骤2：添加新启动项

点击"添加"按钮，填写以下信息：

- **名称**: Carrotpilot
- **命令**: 
  ```bash
  /bin/bash -c "cd /home/ubuntu/carrotpilot && bash /home/ubuntu/carrotpilot/nana-guide/start_carrotpilot.sh"
  ```
- **描述**: Carrotpilot Autonomous Driving Project

### 步骤3：设置延迟启动

在命令前添加延迟，确保图形环境完全启动：

```bash
sleep 10 && /bin/bash -c "cd /home/ubuntu/carrotpilot && bash /home/ubuntu/carrotpilot/nana-guide/start_carrotpilot.sh"
```

## 方法3：使用crontab（备用方案）

### 步骤1：编辑crontab

```bash
crontab -e
```

### 步骤2：添加启动任务

在文件末尾添加：

```bash
@reboot sleep 30 && /bin/bash /home/ubuntu/carrotpilot/nana-guide/start_carrotpilot.sh
```

## 测试启动脚本

在设置自启动前，先手动测试启动脚本：

```bash
# 切换到项目目录
cd ~/carrotpilot

# 测试启动脚本
bash nana-guide/start_carrotpilot.sh
```

## 验证自启动

重启系统后，检查项目是否自动启动：

```bash
# 检查进程
ps aux | grep launch_chffrplus

# 检查是否有相关进程运行
ps aux | grep carrotpilot
```

## 优势

1. **简单可靠**：不需要复杂的systemd配置
2. **图形环境支持**：在用户桌面环境中运行，有完整的图形权限
3. **易于调试**：启动时会在终端显示，便于查看错误信息
4. **延迟启动**：确保系统完全启动后再运行项目

## 注意事项

1. 确保用户已设置自动登录
2. 启动脚本中的路径需要正确
3. 如果项目启动失败，终端会保持打开显示错误信息
4. 建议先手动测试启动脚本确保正常工作