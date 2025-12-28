import logging
import os
import time
import warnings
from pathlib import Path
from logging.handlers import BaseRotatingHandler

import zmq

from openpilot.common.logging_extra import SwagLogger, SwagFormatter, SwagLogFileFormatter, HumanReadableFormatter, AnsiColorStripFormatter
from openpilot.system.hardware.hw import Paths
from openpilot.common.params import Params


def get_file_handler():
  Path(Paths.swaglog_root()).mkdir(parents=True, exist_ok=True)
  base_filename = os.path.join(Paths.swaglog_root(), "swaglog")
  handler = SwaglogRotatingFileHandler(base_filename)
  return handler

def get_system_boottime() -> float:
  """获取系统启动时间戳（秒级精度）
  通过/proc/stat文件获取更准确的启动时间
  当无法获取时（如Windows系统）回退到当前时间"""
  try:
    with open('/proc/stat', 'r') as f:
      for line in f:
        if line.startswith('btime'):
          return float(line.split()[1])
  except:
    return time.time()  # 回退到当前时间

class SwaglogRotatingFileHandler(BaseRotatingHandler):
  def __init__(self, base_filename, interval=60, max_bytes=1024*256, backup_count=2500, encoding=None):
    super().__init__(base_filename, mode="a", encoding=encoding, delay=True)
    self.base_filename = base_filename
    self.interval = interval # seconds
    self.max_bytes = max_bytes
    self.backup_count = backup_count
    self.log_files = self.get_existing_logfiles()
    # 使用新的文件名格式参数
    boot_ts = get_system_boottime()
    self.hex_ts = hex(int(boot_ts))[2:]  # 基于系统启动时间的十六进制表示
    # 初始化计数器，同一hex_ts下从1开始
    self.rollover_count = 0
    self.last_rollover = None
    self.doRollover()

  def _open(self):
    self.last_rollover = time.monotonic()
    timestamp = time.strftime("%Y%m%d_%H%M%S")

    # 查找当前hex_ts下的最大计数器值
    max_count = 0
    base_dir = os.path.dirname(self.base_filename)
    for fn in os.listdir(base_dir):
      if fn.startswith(f"{os.path.basename(self.base_filename)}.{self.hex_ts}"):
        parts = fn.split(".")
        if len(parts) >= 4 and parts[-2].isdigit():
          count = int(parts[-2])
          if count > max_count:
            max_count = count

    # 设置新的计数器值（当前hex_ts下的最大值+1）
    self.rollover_count = max_count + 1
    next_filename = f"{self.base_filename}.{self.hex_ts}.{timestamp}.{self.rollover_count:06d}.log"

    # 确保文件名唯一（防止并发创建）
    while os.path.exists(next_filename) and self.rollover_count < 1000000:
      self.rollover_count += 1
      next_filename = f"{self.base_filename}.{self.hex_ts}.{timestamp}.{self.rollover_count:06d}.log"

    if self.rollover_count >= 1000000:
      raise RuntimeError("Rollover count exceeded maximum limit")

    stream = open(next_filename, self.mode, encoding=self.encoding)
    self.log_files.insert(0, next_filename)
    return stream

  def get_existing_logfiles(self):
    log_files = list()
    base_dir = os.path.dirname(self.base_filename)
    for fn in os.listdir(base_dir):
      fp = os.path.join(base_dir, fn)
      if fp.startswith(self.base_filename) and os.path.isfile(fp):
        log_files.append(fp)
    # 按修改时间排序，确保最旧的文件在最后
    return sorted(log_files, key=lambda f: os.path.getmtime(f))

  def shouldRollover(self, record):
    # 检查stream是否有效
    if not self.stream:
      return True

    size_exceeded = self.max_bytes > 0 and self.stream.tell() >= self.max_bytes
    time_exceeded = self.interval > 0 and self.last_rollover + self.interval <= time.monotonic()
    return size_exceeded or time_exceeded

  def doRollover(self):
    if self.stream:
      self.stream.close()
    self.stream = self._open()

    # 重新排序日志文件列表，确保最旧的文件在最后
    self.log_files = sorted(self.log_files, key=lambda f: os.path.getmtime(f))

    if self.backup_count > 0:
      while len(self.log_files) > self.backup_count:
        to_delete = self.log_files.pop()  # 删除最后一个文件（最旧的）
        if os.path.exists(to_delete):  # 安全检查
          try:
            os.remove(to_delete)
          except Exception as e:
            # 记录删除错误但不中断程序
            logging.error(f"Failed to delete old log file {to_delete}: {e}")

class UnixDomainSocketHandler(logging.Handler):
  def __init__(self, formatter):
    logging.Handler.__init__(self)
    self.setFormatter(formatter)
    self.pid = None

    self.zctx = None
    self.sock = None

  def __del__(self):
    self.close()

  def close(self):
    if self.sock is not None:
      self.sock.close()
    if self.zctx is not None:
      self.zctx.term()

  def connect(self):
    self.zctx = zmq.Context()
    self.sock = self.zctx.socket(zmq.PUSH)
    self.sock.setsockopt(zmq.LINGER, 10)
    self.sock.connect(Paths.swaglog_ipc())
    self.pid = os.getpid()

  def emit(self, record):
    if os.getpid() != self.pid:
      # TODO suppresses warning about forking proc with zmq socket, fix root cause
      warnings.filterwarnings("ignore", category=ResourceWarning, message="unclosed.*<zmq.*>")
      self.connect()

    msg = self.format(record).rstrip('\n')
    # print("SEND".format(repr(msg)))
    try:
      s = chr(record.levelno)+msg
      self.sock.send(s.encode('utf8'), zmq.NOBLOCK)
    except zmq.error.Again:
      # drop :/
      pass


class ForwardingHandler(logging.Handler):
  def __init__(self, target_logger):
    super().__init__()
    self.target_logger = target_logger

  def emit(self, record):
    self.target_logger.handle(record)


def add_file_handler(log):
  """
  Function to add the file log handler to swaglog.
  This can be used to store logs when logmessaged is not running.
  """
  handler = get_file_handler()
  handler.setFormatter(SwagLogFileFormatter(log))
  log.addHandler(handler)


cloudlog = log = SwagLogger()
log.setLevel(logging.DEBUG)


outhandler = logging.StreamHandler()

print_level = os.environ.get('LOGPRINT', 'warning')
if print_level == 'debug':
  outhandler.setLevel(logging.DEBUG)
elif print_level == 'info':
  outhandler.setLevel(logging.INFO)
elif print_level == 'warning':
  outhandler.setLevel(logging.WARNING)

# 检查是否启用可读性日志格式
readable_logs = os.environ.get('LOG_READABLE', '0')
if readable_logs == "1":
  # 使用新的可读性格式化器
  outhandler.setFormatter(HumanReadableFormatter())
else:
  # 使用原始格式化器，但去除颜色代码
  original_formatter = SwagFormatter(log)
  outhandler.setFormatter(AnsiColorStripFormatter(original_formatter))

ipchandler = UnixDomainSocketHandler(SwagFormatter(log))

log.addHandler(outhandler)
# logs are sent through IPC before writing to disk to prevent disk I/O blocking
log.addHandler(ipchandler)
