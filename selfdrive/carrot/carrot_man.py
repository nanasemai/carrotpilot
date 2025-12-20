import fcntl
import json
import math
import os
import socket
import struct
import subprocess
import threading
import time
import numpy as np
import zmq
from datetime import datetime

# from ftplib import FTP  # FTP导入已注释，因为FTP上传功能已禁用
from cereal import log
import cereal.messaging as messaging
from openpilot.common.realtime import Ratekeeper
from openpilot.common.params import Params
from openpilot.common.filter_simple import MyMovingAverage
from openpilot.system.hardware import PC, TICI
from openpilot.selfdrive.navd.helpers import Coordinate
from opendbc.car.common.conversions import Conversions as CV

from openpilot.selfdrive.carrot.carrot_serv import CarrotServ
from openpilot.selfdrive.carrot.carrot_speed import CarrotSpeed

from openpilot.common.gps import get_gps_location_service
from openpilot.common.swaglog import cloudlog

try:
  from shapely.geometry import LineString
  SHAPELY_AVAILABLE = True
except ImportError:
  SHAPELY_AVAILABLE = False

NetworkType = log.DeviceState.NetworkType

# 全局日志级别配置，控制控制台输出频率
# DEBUG: 显示所有日志（调试用）
# INFO: 只显示INFO和ERROR级别（默认生产环境）
# ERROR: 只显示ERROR级别
CONSOLE_LOG_LEVEL = "INFO"

# 日志级别优先级
LOG_LEVELS = {
  "DEBUG": 0,
  "INFO": 1,
  "ERROR": 2
}

# 控制台日志打印函数
def print_friendly(msg, level="INFO"):
  """格式化日志输出函数 - 控制台和日志文件双输出
  格式: 时间戳 | 级别 | 模块 | 消息
  根据 CONSOLE_LOG_LEVEL 控制控制台输出频率
  """
  timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
  module_name = "CARROT"
  
  # 根据日志级别控制控制台输出
  if LOG_LEVELS.get(level, 0) >= LOG_LEVELS.get(CONSOLE_LOG_LEVEL, 1):
    print(f"{timestamp} | {level:<5} | {module_name:<10} | {msg}")

  # 同时写入到 cloudlog（所有级别都写入）
  if level == "DEBUG":
    cloudlog.debug(f"{module_name}: {msg}")
  elif level == "INFO":
    cloudlog.info(f"{module_name}: {msg}")
  elif level == "ERROR":
    cloudlog.error(f"{module_name}: {msg}")

################ CarrotNavi
## 국가법령정보센터: 도로설계기준
#V_CURVE_LOOKUP_BP = [0., 1./800., 1./670., 1./560., 1./440., 1./360., 1./265., 1./190., 1./135., 1./85., 1./55., 1./30., 1./15.]
#V_CRUVE_LOOKUP_VALS = [300, 150, 120, 110, 100, 90, 80, 70, 60, 50, 45, 35, 30]
V_CURVE_LOOKUP_BP = [0., 1./800., 1./670., 1./560., 1./440., 1./360., 1./265., 1./190., 1./135., 1./85., 1./55., 1./30., 1./25.]
V_CRUVE_LOOKUP_VALS = [300, 150, 120, 110, 100, 90, 80, 70, 60, 50, 40, 15, 5]

# Haversine formula to calculate distance between two GPS coordinates
#haversine_cache = {}
def haversine(lon1, lat1, lon2, lat2):
    #key = (lon1, lat1, lon2, lat2)
    #if key in haversine_cache:
    #    return haversine_cache[key]

    R = 6371000  # Radius of Earth in meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    distance = 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    #haversine_cache[key] = distance
    return distance


# Get the closest point on a segment between two coordinates
def closest_point_on_segment(p1, p2, current_position):
    x1, y1 = p1
    x2, y2 = p2
    px, py = current_position

    dx = x2 - x1
    dy = y2 - y1
    if dx == 0 and dy == 0:
        return p1  # p1 and p2 are the same point

    # Parameter t is the projection factor onto the line segment
    t = ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)
    t = max(0, min(1, t))  # Clamp t to the segment

    closest_x = x1 + t * dx
    closest_y = y1 + t * dy

    return (closest_x, closest_y)


# Get path after a certain distance from the current position
def get_path_after_distance(start_index, coordinates, current_position, distance_m):
    total_distance = 0
    path_after_distance = []
    closest_index = -1
    closest_point = None
    min_distance = float('inf')

    start_index = max(0, start_index - 2)

    # 가까운 점만 탐색하도록 수정
    for i in range(start_index, len(coordinates) - 1):
        p1 = coordinates[i]
        p2 = coordinates[i + 1]
        candidate_point = closest_point_on_segment(p1, p2, current_position)
        distance = haversine(current_position[0], current_position[1], candidate_point[0], candidate_point[1])

        if distance < min_distance:
            min_distance = distance
            closest_point = candidate_point
            closest_index = i
        elif distance > min_distance and min_distance < 10:
            break

    start_index = closest_index
    # Start from the closest point and calculate the path after the specified distance
    if closest_index != -1:
        path_after_distance.append(closest_point)

        path_after_distance.append(coordinates[closest_index + 1])
        total_distance = haversine(closest_point[0], closest_point[1], coordinates[closest_index + 1][0],
                                   coordinates[closest_index + 1][1])

        # Traverse the path forward from the next point
        for i in range(closest_index + 1, len(coordinates) - 1):
            coord1 = coordinates[i]
            coord2 = coordinates[i + 1]
            segment_distance = haversine(coord1[0], coord1[1], coord2[0], coord2[1])

            if total_distance + segment_distance >= distance_m and segment_distance > 0:
                remaining_distance = distance_m - total_distance
                ratio = remaining_distance / segment_distance
                interpolated_lon = coord1[0] + ratio * (coord2[0] - coord1[0])
                interpolated_lat = coord1[1] + ratio * (coord2[1] - coord1[1])
                path_after_distance.append((interpolated_lon, interpolated_lat))
                break

            total_distance += segment_distance
            path_after_distance.append(coord2)

    return path_after_distance, start_index, closest_point


def calculate_angle(point1, point2):
    delta_lon = point2[0] - point1[0]
    delta_lat = point2[1] - point1[1]
    return math.degrees(math.atan2(delta_lat, delta_lon))

# Convert GPS coordinates to relative x, y coordinates based on a reference point and heading
def gps_to_relative_xy(gps_path, reference_point, heading_deg):
    ref_lon, ref_lat = reference_point
    relative_coordinates = []

    # Convert heading from degrees to radians
    heading_rad = math.radians(heading_deg)

    for lon, lat in gps_path:
        # Convert lat/lon differences to meters (assuming small distances for simple approximation)
        x = (lon - ref_lon) * 40008000 * math.cos(math.radians(ref_lat)) / 360
        y = (lat - ref_lat) * 40008000 / 360

        # Rotate coordinates based on the heading angle to align with the car's direction
        x_rot = x * math.cos(heading_rad) - y * math.sin(heading_rad)
        y_rot = x * math.sin(heading_rad) + y * math.cos(heading_rad)

        relative_coordinates.append((y_rot, x_rot))

    return relative_coordinates


# Calculate curvature given three points using a faster vector-based method
#curvature_cache = {}
def calculate_curvature(p1, p2, p3):
    #key = (p1, p2, p3)
    #if key in curvature_cache:
    #    return curvature_cache[key]

    v1 = (p2[0] - p1[0], p2[1] - p1[1])
    v2 = (p3[0] - p2[0], p3[1] - p2[1])

    cross_product = v1[0] * v2[1] - v1[1] * v2[0]
    len_v1 = math.sqrt(v1[0] ** 2 + v1[1] ** 2)
    len_v2 = math.sqrt(v2[0] ** 2 + v2[1] ** 2)

    if len_v1 * len_v2 == 0:
        curvature = 0
    else:
        curvature = cross_product / (len_v1 * len_v2 * len_v1)

    #curvature_cache[key] = curvature
    return curvature

class CarrotMan:
  def __init__(self):
    print_friendly("CarrotMan initialization started")
    self.params = Params()
    self.params_memory = Params("/dev/shm/params")
    self.gps_location_service = get_gps_location_service(self.params)
    self.sm = messaging.SubMaster(['deviceState', 'carState', 'controlsState', 'radarState', 'longitudinalPlan', 'modelV2', 'selfdriveState', 'carControl', 'navRouteNavd', self.gps_location_service, 'navInstruction'])
    self.pm = messaging.PubMaster(['carrotMan', "navRoute", "navInstructionCarrot"])

    self.carrot_serv = CarrotServ()

    self.show_panda_debug = False
    self.broadcast_ip = self.get_broadcast_address()
    self.broadcast_port = 7705
    self.carrot_man_port = 7706
    self.connection = None

    self.ip_address = "0.0.0.0"
    self.remote_addr = None

    self.turn_speed_last = 250
    self.curvatureFilter = MyMovingAverage(20)
    self.carrot_curve_speed_params()

    self.carrot_zmq_thread = threading.Thread(target=self.carrot_cmd_zmq, args=[])
    self.carrot_zmq_thread.daemon = True
    self.carrot_zmq_thread.start()

    self.carrot_panda_debug_thread = threading.Thread(target=self.carrot_panda_debug, args=[])
    self.carrot_panda_debug_thread.daemon = True
    self.carrot_panda_debug_thread.start()

    self.carrot_route_thread = threading.Thread(target=self.carrot_route, args=[])
    self.carrot_route_thread.daemon = True
    self.carrot_route_thread.start()

    self.is_running = True
    threading.Thread(target=self.broadcast_version_info).start()

    self.navi_points = []
    self.navi_points_start_index = 0
    self.navi_points_active = False
    self.navd_active = False

    self.active_carrot_last = False

    self.is_metric = self.params.get_bool("IsMetric")

  def get_broadcast_address(self):
    # 在Ubuntu PC环境中，尝试自动检测可用的网络接口
    interfaces_to_try = [b'wlan0', b'eth0', b'enp0s3', b'enp0s25']  # 常见的Ubuntu网络接口
    if not PC:  # 如果不是PC设备，只使用wlan0
      interfaces_to_try = [b'wlan0']

    for iface in interfaces_to_try:
      try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
          # 获取IP地址
          ip = fcntl.ioctl(
            s.fileno(),
            0x8919,  # SIOCGIFADDR
            struct.pack('256s', iface)
          )[20:24]
          local_ip = socket.inet_ntoa(ip)

          # 获取子网掩码
          netmask = fcntl.ioctl(
            s.fileno(),
            0x891b,  # SIOCGIFNETMASK
            struct.pack('256s', iface)
          )[20:24]
          netmask = socket.inet_ntoa(netmask)

          # 计算广播地址
          ip_bytes = socket.inet_aton(local_ip)
          netmask_bytes = socket.inet_aton(netmask)
          broadcast_bytes = bytes([a | ~b & 0xFF for a, b in zip(ip_bytes, netmask_bytes)])
          broadcast_ip = socket.inet_ntoa(broadcast_bytes)

          return broadcast_ip
      except (OSError, Exception):
        continue

    # 如果所有接口都失败，尝试使用get_local_ip方法并计算广播地址
    try:
      local_ip = self.get_local_ip()
      if not local_ip.startswith("Error:"):
        # 简单的广播地址计算：将最后一个字节改为255
        # 这适用于常见的子网掩码（如255.255.255.0）
        ip_parts = local_ip.split('.')
        if len(ip_parts) == 4:
          ip_parts[-1] = '255'
          return '.'.join(ip_parts)
    except Exception:
      pass

    return None

  def get_local_ip(self):
      try:
          # 외부 서버와의 연결을 통해 로컬 IP 확인
          with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
              s.connect(("8.8.8.8", 80))  # Google DNS로 연결 시도
              return s.getsockname()[0]
      except Exception as e:
          return f"Error: {e}"

  # 브로드캐스트 메시지 전송
  def broadcast_version_info(self):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    frame = 0
    self.save_toggle_values()

    carrot_speed = CarrotSpeed(neighbor_ring=2)
    self.params_memory.put_int_nonblocking("CarrotSpeed", 0)

    rk = Ratekeeper(20, print_delay_threshold=None)

    carrotIndex_last = self.carrot_serv.carrotIndex
    phone_gps_frame = self.carrot_serv.phone_gps_frame
    carrot_speed_active_count = 0
    self.v_cruise_last = 0
    self.long_active = False
    self.v_cruise_change = 0
    self._last_vt = 0.0
    self.gas_pressed_count = 0
    self._last_viz_t = 0.0

    while self.is_running:
      try:
        self.sm.update(0)
        if self.sm.updated['navRouteNavd']:
          self.send_routes(self.sm['navRouteNavd'].coordinates, True)
        remote_addr = self.remote_addr
        remote_ip = remote_addr[0] if remote_addr is not None else ""
        vturn_speed = self.carrot_curve_speed(self.sm)
        coords, distances, route_speed = self.carrot_navi_route()

        #print("coords=", coords)
        #print("curvatures=", curvatures)
        self.carrot_serv.update_navi(remote_ip, self.sm, self.pm, vturn_speed, coords, distances, route_speed, self.gps_location_service)

        if phone_gps_frame != self.carrot_serv.phone_gps_frame:
          phone_gps_frame = self.carrot_serv.phone_gps_frame
          carrot_speed_active_count = 10
        else:
          carrot_speed_active_count -= 1

        if carrot_speed_active_count > 0:
          self.carrot_speed_serv(carrot_speed, frame)

        if frame % 20 == 0 or remote_addr is not None:
          try:
            self.broadcast_ip = self.get_broadcast_address() if remote_addr is None else remote_addr[0]
            # 在Ubuntu环境中，统一使用get_local_ip方法获取IP地址
            # 这个方法更可靠，因为它通过连接到外部服务器来确定正确的接口IP
            ip_address = self.get_local_ip()
            if ip_address != self.ip_address:
              self.ip_address = ip_address
              self.remote_addr = None
            self.params_memory.put_nonblocking("NetworkAddress", self.ip_address)

            msg = self.make_send_message()
            if self.broadcast_ip is not None:
              dat = msg.encode('utf-8')
              sock.sendto(dat, (self.broadcast_ip, self.broadcast_port))
            #for i in range(1, 255):
            #  ip_tuple = socket.inet_aton(self.broadcast_ip)
            #  new_ip = ip_tuple[:-1] + bytes([i])
            #  address = (socket.inet_ntoa(new_ip), self.broadcast_port)
            #  sock.sendto(dat, address)

            if remote_addr is None:
              print_friendly(f"Broadcasting: {self.broadcast_ip}:{msg}", level="DEBUG")
              if not self.navd_active:
                #print("clear path_points: navd_active: ", self.navd_active)
                self.navi_points = []
                self.navi_points_active = False

          except Exception as e:
            if self.connection:
              self.connection.close()
            self.connection = None
            print_friendly(f"Broadcast error: {e}", level="ERROR")
            traceback.print_exc()

        rk.keep_time()
        frame += 1
      except Exception as e:
        print_friendly(f"Broadcast version info error: {e}", level="ERROR")
        traceback.print_exc()
        time.sleep(1)

  def carrot_speed_serv(self, carrot_speed, frame):
    v_ego = a_ego = 0.0
    gas_pressed = False
    v_ego_kph = 0
    v_cruise_apply = 20  # 默认值

    if self.sm.alive['carState'] and self.sm.alive['carControl']:
      CS = self.sm['carState']
      CC = self.sm['carControl']
      v_ego = CS.vEgo
      a_ego = CS.aEgo
      gas_pressed = CS.gasPressed
      v_ego_kph = v_ego * 3.6

      if gas_pressed:
        self.gas_pressed_count = 200
        self.v_cruise_change = 0
      elif self._last_vt == CS.vCruise:
        self.v_cruise_last = CS.vCruise
      elif self.long_active and CC.longActive: # and self.gas_pressed_count == 0:
        if self.v_cruise_last < CS.vCruise:  # 속도가 증가하면
          if v_ego_kph < CS.vCruise:
            self.v_cruise_change = 100
          else:
            self.v_cruise_change = 0
        elif self.v_cruise_last > CS.vCruise: # 속도가 감소하면
          if v_ego_kph < CS.vCruise: # 주행속도가 느리면
            self.v_cruise_change = -100 #100
          else:                       # 주행속도가 빠르면
            self.v_cruise_change = -100

        if self.v_cruise_change != 0:
          self.gas_pressed_count = 0
      else:
        self.v_cruise_change = 0

      self.long_active = CC.longActive
      self.v_cruise_last = CS.vCruise

      # 只有在CS和v_ego_kph有效的情况下才计算v_cruise_apply
      v_cruise_apply = max(min(CS.vCruise, v_ego_kph), 20)
    else:
      self.v_cruise_change = 0

    now = time.monotonic()
    heading = self.carrot_serv.bearing #nPosAnglePhone
    lat, lon = self.carrot_serv.vpPosPointLat, self.carrot_serv.vpPosPointLon #self.carrot_serv.estimate_position(self.carrot_serv.phone_latitude, self.carrot_serv.phone_longitude, heading, v_ego, now - self.carrot_serv.last_update_gps_time_phone)
    vt = carrot_speed.query_target_dist(lat, lon, heading, 0.0)
    if self.v_cruise_change != 0:
      carrot_speed.add_sample(lat, lon, heading, v_cruise_apply if self.v_cruise_change > 0 else (- v_cruise_apply))
      if self.v_cruise_change > 0:
        self.v_cruise_change -= 1
      if self.v_cruise_change < 0:
        self.v_cruise_change += 1
    else:
      if self.gas_pressed_count > 0:
        vt = max(vt, v_cruise_apply)
        carrot_speed.add_sample(lat, lon, heading, vt)

      self.params_memory.put_int_nonblocking("CarrotSpeed", int(vt))

    self._last_vt = vt
    if gas_pressed and a_ego < -0.5: #self._last_vt < 0.0:
      carrot_speed.invalidate_last_hit(window_s=2.0, action="clear")
    self.gas_pressed_count = max(0, self.gas_pressed_count - 1)

    if now - self._last_viz_t > 0.5: # 2Hz
        self._last_viz_t = now
        viz_json = carrot_speed.export_cells_around(lat, lon, heading, ring=2, max_points=64)
        # 메모리 Params에 쓰는 게 좋음 (디스크 말고)
        self.params_memory.put_nonblocking("CarrotSpeedViz", viz_json)

    carrot_speed.maybe_save()



  def carrot_navi_route(self):

    if self.carrot_serv.active_carrot > 1:
      if False and self.navd_active:  # mabox always active
        self.navd_active = False
        self.params.remove("NavDestination")
    if not self.navi_points_active or not SHAPELY_AVAILABLE or (self.carrot_serv.active_carrot <= 1 and not self.navd_active):
      #print(f"navi_points_active: {self.navi_points_active}, active_carrot: {self.carrot_serv.active_carrot}")
      if self.navi_points_active:
        print_friendly(f"navi_points_active: {self.navi_points_active}, active_carrot: {self.carrot_serv.active_carrot}, navd_active: {self.navd_active}", level="DEBUG")
        #haversine_cache.clear()
        #curvature_cache.clear()
        self.navi_points = []
        self.navi_points_active = False
        if self.active_carrot_last > 1:
          #self.params.remove("NavDestination")
          pass
      self.active_carrot_last = self.carrot_serv.active_carrot
      return [],[],300

    current_position = (self.carrot_serv.vpPosPointLon, self.carrot_serv.vpPosPointLat)
    heading_deg = self.carrot_serv.bearing

    distance_interval = 10.0
    out_speed = 300
    path, self.navi_points_start_index, start_point = get_path_after_distance(self.navi_points_start_index, self.navi_points, current_position, 300)
    relative_coords = []
    if path:
        #relative_coords = gps_to_relative_xy(path, current_position, heading_deg)
        relative_coords = gps_to_relative_xy(path, start_point, heading_deg)
        # Resample relative_coords at 5m intervals using LineString
        line = LineString(relative_coords)
        resampled_points = []
        resampled_distances = []
        current_distance = 0
        while current_distance <= line.length:
            point = line.interpolate(current_distance)
            resampled_points.append((point.x, point.y))
            resampled_distances.append(current_distance)
            current_distance += distance_interval

        curvatures = []
        distances = []
        distance = 10.0
        sample = 4
        if len(resampled_points) >= sample * 2 + 1:
            # Calculate curvatures and speeds based on curvature
            speeds = []
            for i in range(len(resampled_points) - sample * 2):
                distance += distance_interval
                p1, p2, p3 = resampled_points[i], resampled_points[i + sample], resampled_points[i + sample * 2]
                curvature = calculate_curvature(p1, p2, p3)
                curvatures.append(curvature)
                speed = np.interp(abs(curvature), V_CURVE_LOOKUP_BP, V_CRUVE_LOOKUP_VALS)
                if abs(curvature) < 0.02:
                  speed = max(speed, self.carrot_serv.nRoadLimitSpeed)
                speeds.append(speed)
                distances.append(distance)
            #print(f"curvatures= {[round(s, 4) for s in curvatures]}")
            #print(f"speeds= {[round(s, 1) for s in speeds]}")
            # Apply acceleration limits in reverse to adjust speeds
            accel_limit = self.carrot_serv.autoNaviSpeedDecelRate # m/s^2
            accel_limit_kmh = accel_limit * 3.6  # Convert to km/h per second
            out_speeds = [0] * len(speeds)
            out_speeds[-1] = speeds[-1]  # Set the last speed as the initial value
            v_ego_kph = self.sm['carState'].vEgo * 3.6

            time_delay = self.carrot_serv.autoNaviSpeedCtrlEnd
            time_wait = 0
            for i in range(len(speeds) - 2, -1, -1):
                target_speed = speeds[i]
                next_out_speed = out_speeds[i + 1]

                if target_speed < next_out_speed:
                  time_delay = max(0, ((v_ego_kph - target_speed) / accel_limit_kmh))
                  time_wait = - time_delay

                # Calculate time interval for the current segment based on speed
                time_interval = distance_interval / (next_out_speed / 3.6) if next_out_speed > 0 else 0

                time_apply = min(time_interval, max(0, time_interval + time_wait))

                # Calculate maximum allowed speed with acceleration limit
                max_allowed_speed = next_out_speed + (accel_limit_kmh * time_apply)
                adjusted_speed = min(target_speed, max_allowed_speed)

                #time_wait += time_interval
                time_wait += min(2.0, time_interval)

                out_speeds[i] = adjusted_speed

            #distance_advance = self.sm['carState'].vEgo * 3.0  # Advance distance by 3.0 seconds
            #out_speed = interp(distance_advance, distances, out_speeds)
            out_speed = out_speeds[0]
            #print(f"out_speeds= {[round(s, 1) for s in out_speeds]}")
    else:
        resampled_points = []
        resampled_distances = []
        curvatures = []
        speeds = []
        distances = []
        #self.params.remove("NavDestination")

    return resampled_points, resampled_distances, out_speed #speeds, distances


  def make_send_message(self):
    msg = {}
    msg['Carrot2'] = self.params.get("Version").decode('utf-8')
    isOnroad = self.params.get_bool("IsOnroad")
    msg['IsOnroad'] = isOnroad
    msg['CarrotRouteActive'] = self.navi_points_active
    msg['ip'] = self.ip_address
    msg['port'] = self.carrot_man_port
    self.controls_active = False
    self.xState = 0
    self.trafficState = 0
    v_ego_kph = 0
    log_carrot = ""
    v_cruise_kph = 0
    carcruiseSpeed = 0
    if not isOnroad:
      self.xState = 0
      self.trafficState = 0
    else:
      if self.sm.alive['carState']:
        carState = self.sm['carState']
        v_ego_kph = int(carState.vEgoCluster * 3.6 + 0.5)
        log_carrot = carState.logCarrot
        v_cruise_kph = carState.vCruise
        carcruiseSpeed = carState.cruiseState.speed * 3.6
      if self.sm.alive['selfdriveState']:
        selfdrive = self.sm['selfdriveState']
        self.controls_active = selfdrive.active
      if self.sm.alive['longitudinalPlan']:
        lp = self.sm['longitudinalPlan']
        self.xState = lp.xState
        self.trafficState = lp.trafficState

    msg['log_carrot'] = log_carrot
    msg['v_cruise_kph'] = v_cruise_kph
    msg['carcruiseSpeed'] = carcruiseSpeed
    msg['v_ego_kph'] = v_ego_kph
    msg['tbt_dist'] = self.carrot_serv.xDistToTurn
    msg['sdi_dist'] = self.carrot_serv.xSpdDist
    msg['active'] = self.controls_active
    msg['xState'] = self.xState
    msg['trafficState'] = self.trafficState
    return json.dumps(msg)

  def receive_fixed_length_data(self, sock, length):
    buffer = b""
    while len(buffer) < length:
      data = sock.recv(length - len(buffer))
      if not data:
        raise ConnectionError("Connection closed before receiving all data")
      buffer += data
    return buffer


  def carrot_man_thread(self):
    while True:
      try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
          sock.settimeout(10)  # 소켓 타임아웃 설정 (10초)
          sock.bind(('0.0.0.0', self.carrot_man_port))  # UDP 포트 바인딩
          print_friendly("UDP thread started...")

          while True:
            try:
              #self.remote_addr = None
              # 데이터 수신 (UDP는 recvfrom 사용)
              try:
                data, remote_addr = sock.recvfrom(4096)  # 최대 4096 바이트 수신
                #print(f"Received data from {self.remote_addr}")

                if not data:
                  raise ConnectionError("No data received")

                if self.remote_addr is None:
                  print_friendly(f"Connected to: {remote_addr}")
                self.remote_addr = remote_addr
                try:
                  json_obj = json.loads(data.decode())
                  self.carrot_serv.update(json_obj)
                except Exception as e:
                  print_friendly(f"json error...: {e}", level="ERROR")
                  print_friendly(f"Data: {data}", level="DEBUG")

                # 응답 메시지 생성 및 송신 (UDP는 sendto 사용)
                #try:
                #  msg = self.make_send_message()
                #  sock.sendto(msg.encode('utf-8'), self.remote_addr)
                #except Exception as e:
                #  print(f"carrot_man_thread: send error...: {e}")

              except TimeoutError:
                print_friendly("Waiting for data (timeout)...", level="DEBUG")
                self.remote_addr = None
                time.sleep(1)

              except Exception as e:
                print_friendly(f"error...: {e}", level="ERROR")
                self.remote_addr = None
                break

            except Exception as e:
              print_friendly(f"recv error...: {e}", level="ERROR")
              self.remote_addr = None
              break

          time.sleep(1)
      except Exception as e:
        self.remote_addr = None
        print_friendly(f"Network error, retrying...: {e}", level="ERROR")
        time.sleep(2)


  def parse_kisa_data(self, data: bytes):
    result = {}

    try:
      decoded = data.decode('utf-8')
    except UnicodeDecodeError:
      print_friendly(f"Decoding error: {data}", level="ERROR")
      return result

    parts = decoded.split('/')
    for part in parts:
      if ':' in part:
        key, value = part.split(':', 1)
        try:
          result[key] = int(value)
        except ValueError:
          result[key] = value
    return result

  def kisa_app_thread(self):
    while True:
      try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
          sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
          sock.settimeout(10)  # 소켓 타임아웃 설정 (10초)
          sock.bind(('', 12345))  # UDP 포트 바인딩
          print_friendly("KISA UDP thread started...")

          while True:
            try:
              #self.remote_addr = None
              # 데이터 수신 (UDP는 recvfrom 사용)
              try:
                data, remote_addr = sock.recvfrom(4096)  # 최대 4096 바이트 수신
                #print(f"Received data from {self.remote_addr}")

                if not data:
                  raise ConnectionError("No data received")

                #if self.remote_addr is None:
                #  print("Connected to: ", remote_addr)
                #self.remote_addr = remote_addr
                try:
                  print_friendly(f"Data: {data}", level="DEBUG")
                  kisa_data = self.parse_kisa_data(data)
                  self.carrot_serv.update_kisa(kisa_data)
                  #json_obj = json.loads(data.decode())
                  #print_friendly(f"JSON obj: {json_obj}", level="DEBUG")
                except Exception as e:
                  traceback.print_exc()
                  print_friendly(f"json error...: {e}", level="ERROR")
                  print_friendly(f"Data: {data}", level="DEBUG")

              except TimeoutError:
                print_friendly("Waiting for data (timeout)...", level="DEBUG")
                #self.remote_addr = None
                time.sleep(1)

              except Exception as e:
                print_friendly(f"error...: {e}", level="ERROR")
                #self.remote_addr = None
                break

            except Exception as e:
              print_friendly(f"recv error...: {e}", level="ERROR")
              #self.remote_addr = None
              break

          time.sleep(1)
      except Exception as e:
        #self.remote_addr = None
        print_friendly(f"Network error, retrying...: {e}", level="ERROR")
        time.sleep(2)

  def make_tmux_data(self):
    try:
      # Use LOG_ROOT environment variable instead of hardcoded path
      log_root = os.environ.get('LOG_ROOT', '/data/media/0/realdata')
      tmux_log_path = os.path.join(log_root, 'tmux.log')
      subprocess.run(f"rm {tmux_log_path}; tmux capture-pane -pq -S-1000 > {tmux_log_path}", shell=True, capture_output=True, text=False)
      # Use project root directory instead of hardcoded path
      apilot_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "selfdrive", "apilot.py")
      subprocess.run(apilot_path, shell=True, capture_output=True, text=False)
    except Exception as e:
      print_friendly(f"TMUX creation error: {e}", level="ERROR")
      return

  def send_tmux(self, ftp_password, tmux_why, send_settings=False):
    # FTP上传功能已禁用
    print_friendly("FTP upload disabled: send_tmux method has been disabled")
    # 保留save_toggle_values调用（如果需要）
    if send_settings:
      self.save_toggle_values()

  def carrot_panda_debug(self):
    #time.sleep(2)
    while True:
      if self.show_panda_debug:
        self.show_panda_debug = False
        try:
          # Use project root directory instead of hardcoded path
          script_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "selfdrive", "debug", "debug_console_carrot.py")
          subprocess.run(script_path, shell=True)
        except Exception as e:
          print_friendly(f"debug_console error: {e}", level="ERROR")
          time.sleep(2)
      else:
        time.sleep(1)

  def save_toggle_values(self):
    try:
      import openpilot.selfdrive.frogpilot.fleetmanager.helpers as fleet

      toggle_values = fleet.get_all_toggle_values()
      # Use PARAMS_ROOT environment variable, default to /data/params, then get parent directory
      params_root = os.environ.get('PARAMS_ROOT', '/data/params')
      data_dir = os.path.dirname(params_root)  # Get parent directory of params

      # Ensure the directory exists before writing the file
      if not os.path.exists(data_dir):
        os.makedirs(data_dir)

      file_path = os.path.join(data_dir, 'toggle_values.json')
      with open(file_path, 'w') as file:
        json.dump(toggle_values, file, indent=2)
    except Exception as e:
      print_friendly(f"save_toggle_values error: {e}", level="ERROR")

  def carrot_cmd_zmq(self):

    context = zmq.Context()
    def setup_socket():
        socket = context.socket(zmq.REP)
        socket.bind("tcp://*:7710")
        poller = zmq.Poller()
        poller.register(socket, zmq.POLLIN)
        return socket, poller

    socket, poller = setup_socket()
    isOnroadCount = 0
    is_tmux_sent = False

    print_friendly("ZMQ command thread started...")
    while True:
      try:
        socks = dict(poller.poll(100))

        if socket in socks and socks[socket] == zmq.POLLIN:
          message = socket.recv(zmq.NOBLOCK)
          print_friendly(f"Received:7710 request: {message}", level="DEBUG")
          json_obj = json.loads(message.decode())
        else:
          json_obj = None

        if json_obj is None:
          isOnroadCount = isOnroadCount + 1 if self.params.get_bool("IsOnroad") else 0
          if isOnroadCount == 0:
            is_tmux_sent = False
          if isOnroadCount == 1:
            self.show_panda_debug = True

          network_type = self.sm['deviceState'].networkType # if not force_wifi else NetworkType.wifi
          networkConnected = False if network_type == NetworkType.none else True

          if isOnroadCount == 500:
            self.make_tmux_data()
          if isOnroadCount > 500 and not is_tmux_sent and networkConnected:
            self.send_tmux("Ekdrmsvkdlffjt7710", "onroad", send_settings = True)
            is_tmux_sent = True
          if self.params.get_bool("CarrotException") and networkConnected:
            self.params.put_bool("CarrotException", False)
            self.make_tmux_data()
            self.send_tmux("Ekdrmsvkdlffjt7710", "exception")
        elif 'echo_cmd' in json_obj:
          try:
            result = subprocess.run(json_obj['echo_cmd'], shell=True, capture_output=True, text=False)
            exitStatus = result.returncode
            try:
              stdout = result.stdout.decode('utf-8')
              stderr = result.stderr.decode('utf-8')
            except UnicodeDecodeError:
              stdout = result.stdout.decode('euc-kr', 'ignore')
              stderr = result.stderr.decode('euc-kr', 'ignore')

            echo = json.dumps({"echo_cmd": json_obj['echo_cmd'], "exitStatus": exitStatus, "result": stdout, "error": stderr})
          except Exception as e:
            echo = json.dumps({"echo_cmd": json_obj['echo_cmd'], "exitStatus": exitStatus, "result": "", "error": f"exception error: {str(e)}"})
          #print(echo)
          socket.send(echo.encode())
        elif 'tmux_send' in json_obj:
          self.make_tmux_data()
          self.send_tmux(json_obj['tmux_send'], "tmux_send")
          echo = json.dumps({"tmux_send": json_obj['tmux_send'], "result": "success"})
          socket.send(echo.encode())
      except Exception as e:
        print_friendly(f"error: {e}", level="ERROR")
        socket.close()
        time.sleep(1)
        socket, poller = setup_socket()

  def recvall(self, sock, n):
    """n바이트를 수신할 때까지 반복적으로 데이터를 받는 함수"""
    data = bytearray()
    while len(data) < n:
      packet = sock.recv(n - len(data))
      if not packet:
        return None
      data.extend(packet)
    return data

  def receive_double(self, sock):
    double_data = self.recvall(sock, 8)  # Double은 8바이트
    return struct.unpack('!d', double_data)[0]

  def receive_float(self, sock):
    float_data = self.recvall(sock, 4)  # Float은 4바이트
    return struct.unpack('!f', float_data)[0]


  def send_routes(self, coords, from_navd=False):
    if from_navd:
      if len(coords) > 0:
        self.navi_points = [(c.longitude, c.latitude) for c in coords]
        self.navi_points_start_index = 0
        self.navi_points_active = True
        print_friendly(f"Received points from navd: {len(self.navi_points)}")
        self.navd_active = True

        # 경로수신 -> carrotman active되고 약간의 시간지연이 발생함..
        if not from_navd:
          self.carrot_serv.active_count = 80
          self.carrot_serv.active_sdi_count = self.carrot_serv.active_sdi_count_max
          self.carrot_serv.active_carrot = 2

        coords = [{"latitude": c.latitude, "longitude": c.longitude} for c in coords]
        #print("navdNaviPoints=", self.navi_points)
      else:
        print_friendly("Received points from navd: 0")
        self.navd_active = False

    msg = messaging.new_message('navRoute', valid=True)
    msg.navRoute.coordinates = coords
    self.pm.send('navRoute', msg)

  def carrot_route(self):
    host = '0.0.0.0'  # 혹은 다른 호스트 주소
    port = 7709  # 포트 번호

    try:
      with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, port))
        s.listen()

        while True:
          print_friendly("waiting connection from CarrotMan route")
          conn, addr = s.accept()
          with conn:
            print_friendly(f"Connected by {addr}")
            #self.clear_route()

            # 전체 데이터 크기 수신
            total_size_bytes = self.recvall(conn, 4)
            if not total_size_bytes:
              print_friendly("Connection closed or error occurred", level="DEBUG")
              continue
            try:
              total_size = struct.unpack('!I', total_size_bytes)[0]
              # 전체 데이터를 한 번에 수신
              all_data = self.recvall(conn, total_size)
              if all_data is None:
                  print_friendly("Connection closed or incomplete data received", level="DEBUG")
                  continue

              self.navi_points = []
              points = []
              for i in range(0, len(all_data), 8):
                x, y = struct.unpack('!ff', all_data[i:i+8])
                self.navi_points.append((x, y))
                coord = Coordinate.from_mapbox_tuple((x, y))
                points.append(coord)
              coords = [c.as_dict() for c in points]
              self.navi_points_start_index = 0
              self.navi_points_active = True
              print_friendly(f"Received points: {len(self.navi_points)}")
              #print("Received points:", self.navi_points)

              self.send_routes(coords)
              """
              try:
                module_name = "route_engine"
                class_name = "RouteEngine"
                moduel = importlib.import_module(module_name)
                cls = getattr(moduel, class_name)
                route_engine_instance = cls(name="Loaded at Runtime")

                route_engine_instance.send_route_coords(coords, True)
              except Exception as e:
                print_friendly(f"route_engine error: {e}", level="ERROR")

              #msg = messaging.new_message('navRoute', valid=True)
              #msg.navRoute.coordinates = coords
              #self.pm.send('navRoute', msg)
              """

              if len(coords):
                dest = coords[-1]
                dest['place_name'] = "External Navi"
                self.params.put("NavDestination", json.dumps(dest))

            except Exception as e:
              print_friendly(f"{e}", level="ERROR")
    except Exception as e:
      print_friendly("CarrotMan route server error", level="ERROR")
      print_friendly(f"{e}", level="ERROR")

  def carrot_curve_speed_params(self):
    self.autoCurveSpeedFactor = self.params.get_int("AutoCurveSpeedFactor")*0.01
    self.autoCurveSpeedAggressiveness = self.params.get_int("AutoCurveSpeedAggressiveness")*0.01

  def carrot_curve_speed(self, sm):
    self.carrot_curve_speed_params()
    if not sm.alive['carState'] and not sm.alive['modelV2']:
        return 250
    #print(len(sm['modelV2'].orientationRate.z))
    if len(sm['modelV2'].orientationRate.z) == 0:
        return 250

    return self.vturn_speed(sm['carState'], sm)

  def vturn_speed(self, CS, sm):
    TARGET_LAT_A = 1.9  # m/s^2

    modelData = sm['modelV2']
    v_ego = max(CS.vEgo, 0.1)
    # Set the curve sensitivity
    orientation_rate = np.array(modelData.orientationRate.z) * self.autoCurveSpeedFactor
    velocity = np.array(modelData.velocity.x)

    # Get the maximum lat accel from the model
    max_index = np.argmax(np.abs(orientation_rate))
    curv_direction = np.sign(orientation_rate[max_index])
    max_pred_lat_acc = np.amax(np.abs(orientation_rate) * velocity)

    # Get the maximum curve based on the current velocity
    max_curve = max_pred_lat_acc / (v_ego**2)

    # Set the target lateral acceleration
    adjusted_target_lat_a = TARGET_LAT_A * self.autoCurveSpeedAggressiveness

    # Get the target velocity for the maximum curve
    #turnSpeed = max(abs(adjusted_target_lat_a / max_curve)**0.5  * 3.6, self.autoCurveSpeedLowerLimit)
    turnSpeed = max(abs(adjusted_target_lat_a / max_curve)**0.5  * 3.6, 5)
    turnSpeed = min(turnSpeed, 250)
    return turnSpeed * curv_direction



import traceback

def main():
  print_friendly("CarrotManager Started")
  #print("Carrot GitBranch = {}, {}".format(Params().get("GitBranch"), Params().get("GitCommitDate")))
  carrot_man = CarrotMan()

  print_friendly(f"CarrotMan instance created: {carrot_man}")
  threading.Thread(target=carrot_man.kisa_app_thread).start()
  while True:
    try:
      carrot_man.carrot_man_thread()
    except Exception as e:
      print_friendly(f"CarrotMan error: {e}", level="ERROR")
      traceback.print_exc()
      time.sleep(10)


if __name__ == "__main__":
  main()
