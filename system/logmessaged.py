#!/usr/bin/env python3
import os
import json
import zmq
import logging
from typing import NoReturn

import cereal.messaging as messaging
from openpilot.common.logging_extra import SwagLogFileFormatter, HumanReadableFormatter
from openpilot.system.hardware.hw import Paths
from openpilot.common.swaglog import get_file_handler


def main() -> NoReturn:
  log_handler = get_file_handler()

  # 检查是否启用可读性日志格式
  readable_logs = os.environ.get('LOG_READABLE', '0')
  if readable_logs == "1":
    # 使用新的可读性格式化器
    log_handler.setFormatter(HumanReadableFormatter())
  else:
    # 使用原始格式化器
    log_handler.setFormatter(SwagLogFileFormatter(None))

  log_level = 20  # logging.INFO

  ctx = zmq.Context.instance()
  sock = ctx.socket(zmq.PULL)
  sock.bind(Paths.swaglog_ipc())

  # and we publish them
  log_message_sock = messaging.pub_sock('logMessage')
  error_log_message_sock = messaging.pub_sock('errorLogMessage')

  try:
    while True:
      dat = b''.join(sock.recv_multipart())
      level = dat[0]
      raw_bytes = dat[1:]

      try:
        record = dat[1:].decode("utf-8", errors="replace")
      except Exception as e:
        print(f"decode error: {e}, skipping log")
        print(f"Raw bytes (hex): {raw_bytes.hex()[:200]}...")  # 앞부분만 출력
        # 不再设置参数，因为我们已经移除了参数依赖
        continue

      if level >= log_level:
        # 创建LogRecord对象而不是直接传递字符串
        try:
          # 解析JSON消息
          if record.startswith('{'):
            msg_dict = json.loads(record)
            log_record = logging.LogRecord(
              name=msg_dict.get('name', 'unknown'),
              level=level,
              pathname=msg_dict.get('pathname', ''),
              lineno=msg_dict.get('lineno', 0),
              msg=msg_dict,
              args=(),
              exc_info=None
            )
            # 设置模块名
            log_record.module = msg_dict.get('module', 'unknown')
          else:
            # 普通文本消息
            log_record = logging.LogRecord(
              name='text_log',
              level=level,
              pathname='',
              lineno=0,
              msg=record,
              args=(),
              exc_info=None
            )
            log_record.module = 'unknown'

          log_handler.emit(log_record)
        except Exception as e:
          # 如果解析失败，使用原始字符串作为消息
          log_record = logging.LogRecord(
            name='fallback',
            level=level,
            pathname='',
            lineno=0,
            msg=record,
            args=(),
            exc_info=None
          )
          log_record.module = 'unknown'
          log_handler.emit(log_record)

      if len(record) > 2*1024*1024:
        print("WARNING: log too big to publish", len(record))
        print(record[:100])
        continue

      # then we publish them
      msg = messaging.new_message(None, valid=True, logMessage=record)
      log_message_sock.send(msg.to_bytes())

      if level >= 40:  # logging.ERROR
        msg = messaging.new_message(None, valid=True, errorLogMessage=record)
        error_log_message_sock.send(msg.to_bytes())
  finally:
    sock.close()
    ctx.term()

    # can hit this if interrupted during a rollover
    try:
      log_handler.close()
    except ValueError:
      pass

if __name__ == "__main__":
  main()
