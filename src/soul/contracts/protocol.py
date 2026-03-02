from __future__ import annotations  # 这个是为了支持自引用类型 例如 Envelope -> Envelope
from enum import Enum

# Protocol version for Envelope (transport-level)
PROTOCOL_VERSION = "1"
MAX_WORKING_MEMORY = 20

class MessageType(str, Enum):
    event = "event"             # 事件消息
    response = "response"       # 响应消息
    control = "control"         # 控制消息
    heartbeat = "heartbeat"     # 心跳消息
    error = "error"             # 错误消息
    ack = "ack"                 # 确认消息

class EventName(str, Enum):
    USER_MESSAGE = "user.message"
    MODE_SET = "mode.set"