from __future__ import annotations

from enum import Enum

# Protocol version for Envelope (transport-level)
PROTOCOL_VERSION = "1"
MAX_WORKING_MEMORY = 20


class MessageType(str, Enum):
    # Existing
    event = "event"
    response = "response"
    control = "control"
    heartbeat = "heartbeat"
    error = "error"
    ack = "ack"
    # Federation — node lifecycle
    register = "register"
    register_ack = "register_ack"
    unregister = "unregister"
    capability_announce = "capability_announce"
    # Federation — action dispatch
    action_request = "action_request"
    action_result = "action_result"
    # Federation — state subscriptions
    state_subscribe = "state_subscribe"
    state_unsubscribe = "state_unsubscribe"
    state_notify = "state_notify"
    # Federation — event routing
    event_forward = "event_forward"
    spark = "spark"


class UrgencyLevel(str, Enum):
    immediate = "immediate"
    soon = "soon"
    later = "later"


class SparkVerb(str, Enum):
    notify = "notify"
    command = "command"
    emit = "emit"


# Known event names (extensible — new names can be added by nodes)
class EventName:
    USER_MESSAGE = "user.message"
    MODE_SET = "mode.set"
    SPARK_NOTIFY = "spark.notify"
    SPARK_COMMAND = "spark.command"
    NODE_JOIN = "node.join"
    NODE_LEAVE = "node.leave"