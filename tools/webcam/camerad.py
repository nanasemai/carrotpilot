#!/usr/bin/env python3
import threading
import os
from collections import namedtuple

from msgq.visionipc import VisionIpcServer, VisionStreamType
from cereal import messaging

from openpilot.tools.webcam.camera import Camera
from openpilot.common.realtime import Ratekeeper

WIDE_CAM = os.getenv("WIDE_CAM")
CameraType = namedtuple("CameraType", ["msg_name", "stream_type", "cam_id"])
CAMERAS = [
  CameraType("roadCameraState", VisionStreamType.VISION_STREAM_ROAD, os.getenv("ROAD_CAM", "0")),
  CameraType("driverCameraState", VisionStreamType.VISION_STREAM_DRIVER, os.getenv("DRIVER_CAM", "2")),
]
if WIDE_CAM:
  CAMERAS.append(CameraType("wideRoadCameraState", VisionStreamType.VISION_STREAM_WIDE_ROAD, WIDE_CAM))

class Camerad:
  def __init__(self, camera_configs=None):
    # 默认摄像头配置（使用MJPG格式，适配1280x720分辨率）
    default_configs = {
      "roadCameraState": {
        "width": 1280,
        "height": 720,
        "fps": 30,
        "format": "mjpeg"
      },
      "driverCameraState": {
        "width": 1280,
        "height": 720,
        "fps": 20,
        "format": "mjpeg"
      },
      "wideRoadCameraState": {
        "width": 1280,
        "height": 720,
        "fps": 25,
        "format": "mjpeg"
      }
    }

    # 合并用户配置和默认配置
    if camera_configs:
      for cam_name, config in camera_configs.items():
        if cam_name in default_configs:
          default_configs[cam_name].update(config)

    self.camera_configs = default_configs

    # Filter cameras to only include those that exist
    self.available_cameras = []
    for c in CAMERAS:
      cam_device = f"/dev/video{c.cam_id}"
      if os.path.exists(cam_device):
        self.available_cameras.append(c)
        print(f"Camera {cam_device} found")
      else:
        print(f"Warning: Camera {cam_device} not found, skipping")

    if not self.available_cameras:
      raise RuntimeError("No cameras found! Please check camera connections and settings.")

    self.pm = messaging.PubMaster([c.msg_name for c in self.available_cameras])
    self.vipc_server = VisionIpcServer("camerad")

    self.cameras = []
    for c in self.available_cameras:
      cam_device = f"/dev/video{c.cam_id}"
      print(f"Opening {c.msg_name} at {cam_device}")

      # 获取该摄像头的配置
      config = self.camera_configs.get(c.msg_name, {})

      cam = Camera(
        c.msg_name,
        c.stream_type,
        cam_device,
        width=config.get("width"),
        height=config.get("height"),
        fps=config.get("fps", 20),
        format=config.get("format", "mjpeg")
      )
      self.cameras.append(cam)
      self.vipc_server.create_buffers(c.stream_type, 20, cam.W, cam.H)

    self.vipc_server.start_listener()

  def _send_yuv(self, yuv, frame_id, pub_type, yuv_type):
    eof = int(frame_id * 0.05 * 1e9)
    self.vipc_server.send(yuv_type, yuv, frame_id, eof, eof)
    dat = messaging.new_message(pub_type, valid=True)
    msg = {
      "frameId": frame_id,
      "transform": [1.0, 0.0, 0.0,
                    0.0, 1.0, 0.0,
                    0.0, 0.0, 1.0]
    }
    setattr(dat, pub_type, msg)
    self.pm.send(pub_type, dat)

  def camera_runner(self, cam):
    rk = Ratekeeper(cam.fps, None)
    for yuv in cam.read_frames():
      self._send_yuv(yuv, cam.cur_frame_id, cam.cam_type_state, cam.stream_type)
      cam.cur_frame_id += 1
      rk.keep_time()

  def run(self):
    threads = []
    for cam in self.cameras:
      cam_thread = threading.Thread(target=self.camera_runner, args=(cam,))
      cam_thread.start()
      threads.append(cam_thread)

    for t in threads:
      t.join()


def main():
  # 使用默认配置运行（已在__init__中设置）
  camerad = Camerad()
  camerad.run()


if __name__ == "__main__":
  main()
