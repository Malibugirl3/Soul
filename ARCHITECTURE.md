# Soul Core Architecture Specification

## 1. Purpose

This document defines the architectural constraints and core data model design for the Soul system.

Current phase objective:

- Design only the core contracts (model layer)
- Do not implement business logic
- Do not integrate with any frontend (e.g., VPet)
- Do not implement LLM, memory storage, or external systems
- Focus strictly on stable, versioned, extensible data models

This document must guide all code generation and architectural decisions.

---

# 2. Architectural Philosophy

Soul is a state-driven, event-based runtime system.

The architecture follows these principles:

1. All communication uses a unified Envelope model.
2. All inputs are Event.
3. All outputs are Response.
4. State is explicit and versioned (SoulState).
5. State updates use StatePatch (never full overwrite unless necessary).
6. Actions are abstract intents, not UI commands.
7. All models must include schema version identifiers.
8. The runtime signature is fixed:

handle_event(state: SoulState, event: Event)
    -> tuple[SoulState, Response]

No code should violate these constraints.

---

# 3. Directory Structure (Contracts Layer Only)

contracts/
  protocol.py
  envelope.py
  events.py
  response.py
  state.py
  control.py
  heartbeat.py
  error.py

Only data models are defined in this layer.
No business logic, no I/O, no external service calls.

---

# 4. Protocol Layer

## 4.1 ProtocolVersion

- v: str
- Current version: "1"

## 4.2 MessageType

Allowed values:

- event
- response
- control
- heartbeat
- error
- ack

---

# 5. Envelope Model

All communication must use Envelope.

## Envelope Fields

- v: str — protocol version
- type: MessageType
- id: str — unique message id
- ts: int — timestamp in milliseconds
- session_id: str
- trace: TraceContext | None
- payload: dict

## TraceContext

- trace_id: str
- span_id: str | None
- parent_span_id: str | None
- tags: dict[str, str] | None

Envelope must be transport-agnostic (usable in WebSocket or HTTP).

---

# 6. Event Model

Events represent canonical internal input to Soul.

## Event Schema

schema: "soul.event/1"

## Event Fields

- schema: str
- name: str — canonical event name
- source: SourceInfo
- ts: int
- text: str | None
- data: dict[str, Any]
- tags: dict[str, str]
- priority: int
- ttl_ms: int | None
- idempotency_key: str | None

## SourceInfo

- kind: str (user | system | tool | agent)
- id: str | None
- display: str | None

---

# 7. Response Model

Response represents Soul output intent.

## Response Schema

schema: "soul.response/1"

## Response Fields

- schema: str
- ts: int
- text: str
- actions: list[Action]
- state_patch: StatePatch | None
- debug: dict | None
- metrics: dict[str, float] | None

---

# 8. Action Model

Actions represent abstract system intentions.

## Action Fields

- type: str
- params: dict[str, Any]
- when: str | None
- idempotency_key: str | None
- requires: list[str]

Action types must not be frontend-specific.

Examples:

- state.set
- state.patch
- memory.write
- memory.forget
- tool.call
- emit.event

---

# 9. State Model

Soul maintains explicit state per session.

## SoulState Schema

schema: "soul.state/1"

## SoulState Fields

- schema: str
- session_id: str
- mode: ModeState
- dialog: DialogState
- memory: MemoryState
- flags: dict[str, bool]
- vars: dict[str, Any]

---

## ModeState

- name: str
- since_ts: int
- confidence: float

---

## DialogState

- turn_index: int
- last_user_text: str | None
- last_assistant_text: str | None
- working_memory: list[Utterance]
- topic: str | None

### Utterance

- role: str
- text: str
- ts: int

---

## MemoryState

- summary: str | None
- facts: list[str]
- pointers: dict[str, str]

MemoryState stores metadata only, not full memory storage.

---

# 10. StatePatch Model

State updates must use patch semantics.

## StatePatch Fields

- set: dict[str, Any]
- unset: list[str]
- inc: dict[str, float]

Patch paths use dot notation.

Example:

"mode.name": "office"
"dialog.turn_index": 12
"flags.debug": true

---

# 11. Control Model

## Control Schema

schema: "soul.control/1"

## Control Fields

- schema: str
- command: str
- args: dict[str, Any]

Example commands:

- mode.set
- session.reset
- debug.enable

---

# 12. Heartbeat Model

## Heartbeat Schema

schema: "soul.heartbeat/1"

## Fields

- schema: str
- kind: "ping" | "pong"
- seq: int
- sent_ts: int

---

# 13. Error Model

## Error Schema

schema: "soul.error/1"

## Fields

- schema: str
- code: str
- message: str
- details: dict[str, Any] | None

---

# 14. Strict Constraints

The following are forbidden:

- No frontend-specific fields
- No database logic
- No LLM calls
- No runtime orchestration code
- No memory store implementation
- No connector logic
- No external dependencies except Pydantic (if used)

This layer must remain pure data definitions.

---

# 15. Versioning Strategy

All models must include:

schema: "<model_name>/<version>"

When upgrading:

- Do not mutate v1 schema
- Introduce new schema version
- Maintain backward compatibility through adapters

---

# 16. Validation Requirements

Each model must:

- Be serializable to JSON
- Be validated on construction
- Reject invalid field types
- Enforce priority range (-10 to 10 suggested)
- Enforce timestamp as millisecond precision integer

---

# 17. Development Order

1. Define protocol enums/constants
2. Implement Envelope
3. Implement Event
4. Implement Response and Action
5. Implement SoulState
6. Implement StatePatch
7. Add Control/Heartbeat/Error

Do not skip order.

---

# 18. Future Extension Points

These areas are intentionally extensible:

- Action types
- Event names
- State flags
- State vars
- Memory pointers
- Metrics
- Trace tags

Do not prematurely optimize these.

---

# 19. v0.2 Federated Architecture

## 19.1 Overview

Soul v0.2 evolves the monolithic runtime into a **federated multi-agent architecture**. The Core becomes a lightweight protocol bus + state aggregator — it does no AI work itself. All capabilities are provided by semi-autonomous **Nodes** that connect via the Envelope protocol, can join/leave dynamically, and communicate through Spark signals.

## 19.2 Design Principles

1. **Core does not reason.** Core routes envelopes, aggregates state, manages node lifecycle.
2. **Every capability is a Node.** LLM inference, memory storage, perception enrichment, action execution — each is a separate node.
3. **Nodes register capabilities.** Each node tells Core what actions it can perform (JSON Schema). The ReasoningNode discovers available actions dynamically.
4. **New capability = new Node type, never Core changes.**
5. **Pipeline is configurable.** Different event types can have different processing chains.
6. **Graceful degradation.** If a node is unavailable, the pipeline skips it instead of crashing.

## 19.3 Directory Structure (v0.2)

```
src/soul/
  contracts/     # [EXTENDED] Pure data models
    protocol.py  # New: MessageType (register, capability_announce, spark...),
                 #      UrgencyLevel (immediate, soon, later),
                 #      SparkVerb (notify, command, emit)
    node.py      # [NEW] NodeIdentity, NodeRegistration, NodeStatus
    capability.py # [NEW] ActionSchema, CapabilityManifest
    spark.py     # [NEW] SparkMessage (inter-node signaling)
    subscription.py # [NEW] StateSubscription, StateChangeNotification
    response.py  # [MODIFIED] Added data field, node_id + urgency to Action
    state.py     # [FIXED] schema_id bug, added state_version
    events.py    # [MODIFIED] EventName is now extensible (str-based)

  core/          # [NEW] Lightweight orchestrator
    router.py           # Facade: dispatch Envelope by type
    node_registry.py    # Node lifecycle (register, heartbeat, timeout)
    action_registry.py  # Action catalog with LLM tool-catalogue generation
    event_bus.py        # Priority queues + Spark protocol routing
    state_aggregator.py # Authoritative state holder, patch application
    pipeline.py         # Configurable processing chain
    session_manager.py  # Migrated from runtime/

  nodes/         # [NEW] Capability providers
    base.py            # BaseNode: WS client, registration, heartbeat, reconnect
    reasoning.py       # ReasoningNode: LLM-powered decision-making
    memory.py          # MemoryNode: working/long-term memory
    perception.py      # PerceptionNode: time/perceptual context
    action.py          # ActionNode: execute text.send, state.set, etc.

  runtime/       # [DEPRECATED] v0.1 legacy code
    engine.py          # -> nodes/reasoning.py
    router.py          # -> core/router.py
    session_manager.py # -> core/session_manager.py

  connectors/
    websocket_server.py # [REFACTORED] Dual-connection: client + node
```

## 19.4 Pipeline Data Flow

```
User Input -> WS Server -> Core Router -> EventBus -> Pipeline
  -> Step 1: PerceptionNode (enrich with time/session context)
  -> Step 2: MemoryNode (retrieve relevant memories/facts)
  -> Step 3: ReasoningNode (LLM decides text + actions)
  -> Step 4: ActionNode (execute text.send, state.set, etc.)
  -> StateAggregator (apply StatePatch) -> Response -> WS -> User
```

## 19.5 Spark Protocol (Inter-node Signaling)

| Verb | Direction | Purpose |
|------|-----------|---------|
| notify | source -> target | Fire-and-forget event |
| command | source -> target | Request-reply (correlation_id) |
| emit | source -> broadcast | Broadcast to all nodes of target_type |

Urgency levels: `immediate` (preempt), `soon` (next slot), `later` (background).

## 19.6 Migration

Use `--legacy` flag to run the old v0.1 engine:
```
python -m src.soul.connectors.websocket_server --legacy
```

Use `--standalone` to run v0.2 with all nodes in-process:
```
python -m src.soul.connectors.websocket_server --standalone
```

Default (no flags) runs v0.2 in networked mode, expecting nodes to connect via WebSocket.

---

# End of Specification

This document governs all Soul core model design.
Any code generation must strictly adhere to this specification.