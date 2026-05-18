# Solace Agent Mesh — Broker Topics & Payload Reference

This document catalogues every Solace topic the Agent Mesh (SAM) uses at runtime, the
payload shape on each topic, and who publishes / subscribes to it.

> All topic patterns are derived directly from
> `solace_agent_mesh/common/a2a/protocol.py` (v1.20.4 — the version pinned in
> this repo's `requirements.txt`). Concrete examples use this project's
> namespace `default_namespace/` (from `.env`) and the
> `WeddingVenueAgent` / `CateringAgent` / `webui_gateway` names from
> `configs/`.

---

## 0. Conventions

### Namespace and base topic

Every topic is rooted at the SAM namespace, then the A2A protocol prefix:

```
{namespace}/a2a/v1/...
```

For this project:

```
NAMESPACE=default_namespace/      →  base = default_namespace/a2a/v1
```

(`namespace.rstrip('/')` is applied — trailing slash on `NAMESPACE` is harmless.)

### Wildcards

Solace topic wildcards are used in subscriptions, not publishes:

| Wildcard | Meaning |
|---|---|
| `*` | matches exactly one topic level |
| `>` | matches one **or more** trailing levels (only allowed at the end) |

### Two address families

SAM uses two distinct topic trees, each with its own purpose:

| Tree | Purpose | Examples |
|---|---|---|
| `{namespace}/a2a/v1/...` | The **A2A protocol** — request/response, status streaming, discovery, trust | `.../agent/request/...`, `.../discovery/agentcards` |
| `{namespace}/sam/...`    | **SAM system events** — broker-side lifecycle/coordination events that aren't A2A messages | `.../sam/events/session/deleted`, `.../sam/v1/feedback/submit` |

There is also one legacy/utility topic outside both trees:
`{namespace}/a2a/events/agent/deregistered` (note: no `/v1/`).

---

## 1. Topic catalogue

### 1.1 Discovery — agent cards

| | |
|---|---|
| **Publish topic** | `{namespace}/a2a/v1/discovery/agentcards` |
| **Example** | `default_namespace/a2a/v1/discovery/agentcards` |
| **Publishers** | every agent app (e.g. `WeddingVenueAgent`, `CateringAgent`, `OrchestratorAgent`) |
| **Subscribers** | every agent (to learn its peers), every gateway, the Platform service |
| **Cadence** | `agent_card_publishing.interval_seconds` in each agent YAML — `10s` in this project |
| **Purpose** | An agent advertises *itself*: name, description, skills, supported input/output modes, capabilities. Receivers build their peer-agent registry from these. |

**Payload — `AgentCard` (A2A v0.3.0)**

```jsonc
{
  "name": "WeddingVenueAgent",
  "description": "A specialized agent for finding available wedding venues...",
  "protocol_version": "0.3.0",
  "preferred_transport": "JSONRPC",
  "capabilities": { /* AgentCapabilities — streaming, push-notifications, etc. */ },
  "default_input_modes":  ["text"],
  "default_output_modes": ["text"],
  "skills": [
    { "id": "search_venues",            "name": "Search Venues",            "description": "...", "tags": [], "examples": [] },
    { "id": "get_venue_details",        "name": "Get Venue Details",        "description": "...", "tags": [], "examples": [] },
    { "id": "check_venue_availability", "name": "Check Venue Availability", "description": "...", "tags": [], "examples": [] },
    { "id": "get_venue_quote",          "name": "Get Venue Quote",          "description": "...", "tags": [], "examples": [] },
    { "id": "save_venue_search_report", "name": "Save Venue Search Report", "description": "...", "tags": [], "examples": [] }
  ]
  // ... documentation_url, icon_url, provider, security, security_schemes, signatures (optional)
}
```

Full schema: `a2a.types.AgentCard` (Pydantic) — see
`.venv/lib/python3.13/site-packages/a2a/types.py:1723`.

---

### 1.2 Discovery — gateway cards

| | |
|---|---|
| **Publish topic** | `{namespace}/a2a/v1/discovery/gatewaycards` |
| **Example** | `default_namespace/a2a/v1/discovery/gatewaycards` |
| **Publishers** | every gateway (e.g. the WebUI gateway in `configs/gateways/webui.yaml`) |
| **Subscribers** | Platform service, other gateways |
| **Purpose** | Gateways advertise themselves for platform monitoring and deployment tracking. The payload is an `AgentCard` with a gateway extension (see `BaseGatewayComponent._build_gateway_card`, line ~2459). |

### 1.3 Discovery — wildcard subscription

| | |
|---|---|
| **Subscription** | `{namespace}/a2a/v1/discovery/>` |
| **Example** | `default_namespace/a2a/v1/discovery/>` |
| **Used by** | Platform service (`configs/services/platform.yaml`) — receives both agent and gateway cards through one subscription. |

---

### 1.4 Agent request (delegation)

| | |
|---|---|
| **Publish topic** | `{namespace}/a2a/v1/agent/request/{agent_name}` |
| **Example** | `default_namespace/a2a/v1/agent/request/WeddingVenueAgent` |
| **Publishers** | the OrchestratorAgent (first hop) **or** any peer agent calling another via `inter_agent_communication` |
| **Subscribers** | the target agent (it subscribes to its own request topic) |
| **Purpose** | Send a JSON-RPC `message/send` or `message/stream` request *into* a specific agent. Used both for the orchestrator's first delegation and for the automatic vendor-chain handoffs (Venue → Catering → Decorator → Photo). |

**Payload — A2A JSON-RPC request envelope**

```jsonc
{
  "jsonrpc": "2.0",
  "id": "req-7c41a8...",            // request id, used to correlate responses
  "method": "message/send",         // or "message/stream" for SSE-like streaming
  "params": {
    "message": {
      "role": "user",               // user | agent
      "parts": [
        { "kind": "text", "text": "A venue has been confirmed for 120 guests..." }
        // | DataPart  { "kind": "data",  "data": { ... } }
        // | FilePart  { "kind": "file",  "file": { "name": "...", "mime_type": "...", "bytes": "..." | "uri": "..." } }
      ],
      "task_id":    "task-0a4...",   // present when continuing a task
      "context_id": "ctx-12...",     // groups related tasks (e.g. a wedding-planning session)
      "metadata":   { /* arbitrary */ }
    }
    // Optional: "configuration": { ... } for streaming/push-notification options
  }
}
```

Supported methods (from `a2a.types`):

| Method | Purpose |
|---|---|
| `message/send`              | Non-streaming send |
| `message/stream`            | Streaming send (status updates flow back via 1.5/1.6) |
| `tasks/get`                 | Fetch the current state of a task by ID |
| `tasks/cancel`              | Cancel an in-flight task |

---

### 1.5 Agent → peer status (sub-task progress)

| | |
|---|---|
| **Publish topic** | `{namespace}/a2a/v1/agent/status/{delegating_agent_name}/{sub_task_id}` |
| **Example** | `default_namespace/a2a/v1/agent/status/WeddingVenueAgent/task-0a4...` |
| **Publishers** | the agent **executing** a sub-task (e.g. `CateringAgent` working on a request from `WeddingVenueAgent`) |
| **Subscribers** | the **delegating** agent (e.g. `WeddingVenueAgent`) via the subscription pattern below |
| **Subscription pattern** | `{namespace}/a2a/v1/agent/status/{self_agent_name}/>` |
| **Purpose** | Stream incremental progress (`TaskStatusUpdateEvent`) back to the agent that delegated. Also carries SAM "signal" data parts: tool-invocation-start, tool-result, llm-invocation, agent-progress-update, artifact-creation-progress. |

**Payload — `TaskStatusUpdateEvent` wrapped in JSON-RPC**

```jsonc
{
  "jsonrpc": "2.0",
  "id": "req-7c41a8...",
  "result": {
    "kind":       "status-update",
    "task_id":    "task-0a4...",
    "context_id": "ctx-12...",
    "status": {
      "state":     "working",        // submitted|working|input-required|completed|failed|canceled|...
      "timestamp": "2026-09-14T10:42:11.022Z",
      "message": {
        "role": "agent",
        "parts": [
          { "kind": "data", "data": {
              "type": "agent_progress_update",
              "status_text": "Searching caterers in London..."
          }}
        ]
      }
    },
    "is_final":   false,             // true means this status is the last on this topic
    "metadata":   { "agent_name": "CateringAgent" }
  }
}
```

The `data` part inside the message is a SAM **signal** — one of the schemas in
§ 2. Final responses come over the *response* topic (next section), not status.

---

### 1.6 Agent → peer response (final sub-task result)

| | |
|---|---|
| **Publish topic** | `{namespace}/a2a/v1/agent/response/{delegating_agent_name}/{sub_task_id}` |
| **Example** | `default_namespace/a2a/v1/agent/response/WeddingVenueAgent/task-0a4...` |
| **Publishers** | the agent that finished a sub-task |
| **Subscribers** | the delegating agent via `.../agent/response/{self_agent_name}/>` |
| **Purpose** | Single-shot final response (success or error) for a sub-task. Closes out a delegation started over topic 1.4. |

**Payload — `Task` or `JSONRPCErrorResponse`**

```jsonc
{
  "jsonrpc": "2.0",
  "id": "req-7c41a8...",
  "result": {
    "kind":       "task",
    "id":         "task-0a4...",
    "context_id": "ctx-12...",
    "status": {
      "state": "completed",
      "timestamp": "2026-09-14T10:43:55Z",
      "message": { "role": "agent", "parts": [
        { "kind": "text", "text": "Found 4 caterers in London. Top match: Bombay Brasserie..." }
      ]}
    },
    "artifacts": [
      {
        "artifact_id": "catering_quote_v1",
        "name":        "catering_quote.txt",
        "parts":       [ /* TextPart | DataPart | FilePart */ ],
        "metadata":    { "uri": "artifact://catering_quote.txt?version=1" }
      }
    ],
    "history":    [ /* prior messages, if requested */ ],
    "metadata":   { "agent_name": "CateringAgent" }
  }
}
```

Errors arrive as `JSONRPCErrorResponse` with `error.code`/`error.message`
(`InternalError`, `InvalidRequestError`, etc.).

---

### 1.7 Agent → gateway status (user-facing progress)

| | |
|---|---|
| **Publish topic** | `{namespace}/a2a/v1/gateway/status/{gateway_id}/{task_id}` |
| **Example** | `default_namespace/a2a/v1/gateway/status/webui-7f3a/task-0a4...` |
| **Publishers** | the top-level agent handling the user's turn (typically the OrchestratorAgent — or whichever agent the gateway delegated to) |
| **Subscribers** | the gateway that originated the request, via `.../gateway/status/{self_gateway_id}/>` |
| **Purpose** | Streams `TaskStatusUpdateEvent` and `TaskArtifactUpdateEvent` toward the gateway so it can forward them to the browser (SSE). This is what powers the live "Searching venues..." indicator and artifact previews in the WebUI. |

Payload shape is identical to **1.5**, plus also `TaskArtifactUpdateEvent`:

```jsonc
{
  "jsonrpc": "2.0",
  "id": "req-...",
  "result": {
    "kind":       "artifact-update",
    "task_id":    "task-0a4...",
    "context_id": "ctx-12...",
    "artifact": { /* Artifact — same shape as above */ },
    "append":      false,            // true to append parts to an existing artifact
    "last_chunk":  true              // signals end of streamed artifact creation
  }
}
```

---

### 1.8 Agent → gateway response (final response to user)

| | |
|---|---|
| **Publish topic** | `{namespace}/a2a/v1/gateway/response/{gateway_id}/{task_id}` |
| **Example** | `default_namespace/a2a/v1/gateway/response/webui-7f3a/task-0a4...` |
| **Publishers** | the agent that completed the user-visible task |
| **Subscribers** | the originating gateway via `.../gateway/response/{self_gateway_id}/>` |
| **Purpose** | Single-shot terminal response back to the gateway — same `Task` payload as **1.6** but routed to a gateway instead of a peer agent. |

---

### 1.9 Direct-to-client variants (clients without a gateway)

When SAM is used without a gateway (e.g. a CLI or SDK client subscribes directly
to the broker), agents publish on **client** topics instead of gateway ones.

| Pattern | Purpose |
|---|---|
| `{namespace}/a2a/v1/client/response/{client_id}` | Final response to a specific client |
| `{namespace}/a2a/v1/client/status/{client_id}/{task_id}` | Streaming status to a specific client + task |
| `{namespace}/a2a/v1/client/status/{client_id}/>` | Subscription pattern a client uses |

Payloads are identical to the gateway/peer variants — only the routing differs.

---

### 1.10 Trust cards (security)

| | |
|---|---|
| **Publish topic** | `{namespace}/a2a/v1/trust/{component_type}/{component_id}` |
| **Example** | `default_namespace/a2a/v1/trust/agent/wedding-venue-agent-app` |
| **Publishers** | every agent and gateway, on startup and periodically |
| **Subscribers** | components that verify peers — typically the Platform service and any agent enabling trust checks |
| **Subscription pattern** | `{namespace}/a2a/v1/trust/*/*` (all) or `{namespace}/a2a/v1/trust/{component_type}/*` (filtered) |
| **Critical invariant** | `component_id` **must equal the broker client-username** the component authenticates with — i.e. `broker_username` in YAML. Using a different value (like `agent_name`) breaks the trust model. |
| **Purpose** | Lets peers cryptographically verify that the agent publishing on a topic is who its agent-card claims to be. |

Payload is a signed trust-card document (component identity + signature + public
key references); see `get_trust_card_topic` docstring at
`common/a2a/protocol.py:218`.

---

### 1.11 SAM system events — session lifecycle

Distinct topic tree (`/sam/events/...` not `/a2a/v1/...`):

| Topic | Direction | Purpose |
|---|---|---|
| `{namespace}/sam/events/session/deleted`           | Gateway → broker → all interested agents | A user session was deleted in the WebUI; agents drop server-side state for it. |
| `{namespace}/sam/events/session/compact_request`   | Gateway → agent                          | Ask an agent to summarise/compact a long conversation to save tokens. |
| `{namespace}/sam/events/session/compact_response`  | Agent → gateway                          | Result of a compact-request (summary + token usage). |
| `{namespace}/sam/events/session/>`                 | Subscription                             | All session events. Used by `OrchestratorAgent` (`agent/sac/app.py:612`). |

**Payload — `SamEvent` envelope** (from `common/sam_events/event_service.py`):

```jsonc
{
  "event_type":       "session.deleted",        // "{category}.{action}"
  "event_id":         "9c2f...e8",
  "timestamp":        "2026-09-14T10:50:00.000+00:00",
  "source_component": "webui-7f3a",
  "namespace":        "default_namespace/",
  "data": {
    "session_id": "sess-...",
    "user_id":    "sarah@example.com",
    "agent_id":   "OrchestratorAgent",
    "gateway_id": "webui-7f3a"
  }
}
```

Per-action `data` shapes:

| Action | `data` fields |
|---|---|
| `session.deleted`           | `session_id`, `user_id`, `agent_id`, `gateway_id` |
| `session.compact_request`   | `session_id`, `user_id`, `agent_id`, `gateway_id`, `correlation_id`, `compaction_percentage` |
| `session.compact_response`  | `correlation_id`, `success`, `events_compacted`, `summary`, `remaining_events`, `remaining_tokens`, `compaction_prompt_tokens`, `compaction_completion_tokens`, `error_message` |

User-properties on the message: `eventType`, `eventId`.

---

### 1.12 SAM system events — deep research

| Topic | Purpose |
|---|---|
| `{namespace}/sam/events/deep_research/plan_response` | Response leg of the deep-research workflow (planning result from agent → gateway). |
| `{namespace}/sam/events/deep_research/>`             | Subscription used by agents (`agent/sac/app.py:613`). |

Same `SamEvent` envelope as above; `data` carries the workflow-specific fields.

---

### 1.13 User feedback

| | |
|---|---|
| **Publish topic** | `{namespace}/sam/v1/feedback/submit` |
| **Example** | `default_namespace/sam/v1/feedback/submit` |
| **Publishers** | Gateway (only when `frontend_collect_feedback: true`; this repo has it set to `false`) |
| **Subscribers** | Platform service / analytics consumers |
| **Purpose** | A user gave a thumbs-up/down on a response in the WebUI. |

**Payload — `FeedbackEvent`** (`common/a2a_spec/schemas/feedback_event.json`):

```jsonc
{
  "id":           "fb-...",                    // string, required
  "session_id":   "sess-...",                  // required
  "task_id":      "task-0a4...",               // required
  "user_id":      "sarah@example.com",         // required
  "rating":       "up",                        // "up" | "down", required
  "comment":      "Great match!",              // string | null
  "created_time": "2026-09-14T10:51:00Z",      // ISO-8601 UTC, required
  "gateway_id":   "webui-7f3a"                 // required
}
```

---

### 1.14 Agent deregistration event (legacy path)

| | |
|---|---|
| **Publish topic** | `{namespace}/a2a/events/agent/deregistered` |
| **Example** | `default_namespace/a2a/events/agent/deregistered` |
| **Publishers** | An agent that just removed a peer from its registry because the peer's health-check failed (`agent/sac/component.py:4052`). |
| **Subscribers** | Other agents / monitoring consumers. |
| **Note** | This topic uses the older `/a2a/events/...` form — **not** `/a2a/v1/sam/events/...` — and is the only legacy survivor in this layout. |

**Payload**

```jsonc
{
  "event_type": "agent.deregistered",
  "agent_name": "PhotoAgent",
  "reason":     "health_check_failure",
  "metadata": {
    "timestamp":      1726305600.123,
    "deregistered_by": "OrchestratorAgent"
  }
}
```

---

### 1.15 Scheduler (background tasks)

The WebUI gateway runs a scheduler service for background/cron-style tasks:

| Topic | Purpose |
|---|---|
| `{namespace}a2a/v1/scheduler/response/{instance_id}` | Final result of a scheduled task back to the scheduler service. |
| `{namespace}a2a/v1/scheduler/status/{instance_id}`   | Streaming status of a scheduled task. |

Source: `gateway/http_sse/services/scheduler/scheduler_service.py:940-941`.
Used only when `background_tasks` is enabled in the gateway config (it is, in
this project).

---

### 1.16 Dynamic model provider (LLM bootstrap)

For dynamically-configurable LLM model providers (advanced):

| Topic | Direction | Purpose |
|---|---|---|
| `{namespace}configuration/model/bootstrap/>` | Subscription | Agent listens for model-bootstrap requests. |
| `{namespace}configuration/model/response/{model_id}/{component_id}` | Publish | Bootstrap response back to the requester. |

Source: `agent/adk/models/dynamic_model_provider_topics.py`. Not exercised by
the wedding-planning agents in this repo, but the topics exist on the wire.

---

## 2. Signal data parts (status-update payloads)

Inside a `TaskStatusUpdateEvent` (topics **1.5**, **1.7**), the agent can attach
structured signals via a `DataPart`. The five signal schemas live in
`common/a2a_spec/schemas/`:

### 2.1 `agent_progress_update`

```json
{
  "type": "agent_progress_update",
  "status_text": "Analyzing the report..."
}
```

Purpose: human-readable progress line (the "status_update" embed directive
agents are instructed to send before every tool call).

### 2.2 `tool_invocation_start`

```json
{
  "type": "tool_invocation_start",
  "tool_name": "search_venues",
  "tool_args": { "guests": 120, "city": "London", "date": "2026-09-14" },
  "function_call_id": "fc-abc..."
}
```

Purpose: emitted just before a tool runs — drives the live tool-call indicator
in the WebUI.

### 2.3 `tool_result`

```json
{
  "type": "tool_result",
  "tool_name": "search_venues",
  "result_data": [ /* whatever the tool returned */ ],
  "function_call_id": "fc-abc...",
  "llm_usage": {
    "input_tokens": 482,
    "output_tokens": 31,
    "cached_input_tokens": 0,
    "model": "claude-opus-4-6"
  }
}
```

Purpose: emitted after a tool returns. `llm_usage` is present only if the tool
internally called an LLM.

### 2.4 `llm_invocation`

```json
{
  "type": "llm_invocation",
  "request": { /* sanitized LlmRequest — system prompt, tool defs, message list */ },
  "usage": {
    "input_tokens": 1240,
    "output_tokens": 87,
    "cached_input_tokens": 1100,
    "model": "claude-opus-4-6"
  }
}
```

Purpose: emitted around an LLM call. The `request` field is sanitized — secrets
are stripped — and is logged to `task_logging` in the gateway if enabled.

### 2.5 `artifact_creation_progress`

```json
{
  "type": "artifact_creation_progress",
  "filename": "catering_quote.txt",
  "description": "Itemised quote for Bombay Brasserie",
  "status": "in-progress",          // "in-progress" | "completed" | "failed"
  "bytes_transferred": 4096,
  "artifact_chunk": "...base64 chunk... (only when in-progress)",
  "mime_type": "text/plain",        // only when completed
  "version": 1
}
```

Purpose: incremental progress while an artifact is being built and saved to the
artifact store (`/tmp/samv2` for this project).

---

## 3. Who subscribes to what

Each component's effective subscription set (excluding scheduler/dynamic-model
topics, which are conditional):

### Agent (e.g. `WeddingVenueAgent`)

```
default_namespace/a2a/v1/agent/request/WeddingVenueAgent           # 1.4 — my requests
default_namespace/a2a/v1/agent/response/WeddingVenueAgent/>        # 1.6 — responses to my delegations
default_namespace/a2a/v1/agent/status/WeddingVenueAgent/>          # 1.5 — status from my delegations
default_namespace/a2a/v1/discovery/>                               # 1.3 — peer + gateway cards
default_namespace/sam/events/session/>                             # 1.11 — session lifecycle
default_namespace/sam/events/deep_research/>                       # 1.12 — research workflow
```

`inter_agent_communication.allow_list` in the YAML restricts which agents this
one is *permitted* to send requests to — it is enforced when the agent decides
to publish on **1.4**, not by what it subscribes to.

### WebUI gateway

```
default_namespace/a2a/v1/discovery/>                                # 1.3 — agents + gateways
default_namespace/a2a/v1/gateway/response/{webui_gateway_id}/>      # 1.8 — responses to me
default_namespace/a2a/v1/gateway/status/{webui_gateway_id}/>        # 1.7 — status to me
default_namespace/sam/events/session/compact_response               # 1.11 — compact replies
```

### Platform service

```
default_namespace/a2a/v1/discovery/>                                # 1.3 — agents + gateways
default_namespace/a2a/v1/trust/*/*                                  # 1.10 — trust cards
default_namespace/sam/v1/feedback/submit                            # 1.13 — feedback events (if enabled)
```

### Event Mesh Gateway (`event-mesh-gw-01`)

```
wedding/alerts/>                                                    # 1.17.1 — S3 connector events
default_namespace/a2a/v1/discovery/>                                # 1.3 — agents + gateways
default_namespace/a2a/v1/gateway/response/event-mesh-gw-01/>       # 1.8 — agent final responses
default_namespace/a2a/v1/gateway/status/event-mesh-gw-01/>         # 1.7 — agent streaming status
```

Publishes outbound on (data plane — no SAM namespace):
```
event_mesh/responses/{correlation_id}                               # 1.17.2 — success
event_mesh/errors/{correlation_id}                                  # 1.17.2 — error
```

### Firehose / debug

The WebUI exposes a visualization router (`gateway/http_sse/routers/visualization.py`)
that subscribes to `default_namespace/a2a/>` — every A2A message — for live
debugging in the UI. Useful when demoing; do not enable in production.

---

### Event Mesh Gateway (`configs/gateways/event_mesh_gateway.yaml`)

The Event Mesh Gateway is a second gateway that bridges **external Solace topics** (the
"data plane") into the SAM control plane. Unlike the WebUI gateway, it never interacts
with a human — it watches application topics and converts events into A2A requests that
the OrchestratorAgent handles.

In this project its data-plane broker connection uses the same `SOLACE_BROKER_URL` env
variable (`ws://localhost:9009`), but the topics it subscribes to and publishes on are
**outside the SAM namespace** — they are plain Solace topics agreed upon between the
Connector and your application code.

#### 1.17.1 Inbound subscription — S3 Micro Integration Connector

| | |
|---|---|
| **Topic** | `wedding/alerts/>` |
| **Example** | `wedding/alerts/booking-update`, `wedding/alerts/s3-event` |
| **Publisher** | **Solace S3 Micro Integration Connector** — watches an S3 bucket and publishes a notification to a configurable Solace topic whenever an S3 object event occurs (upload, delete, etc.). |
| **Subscriber** | Event Mesh Gateway (`event_handlers[].subscriptions[].topic: "wedding/alerts/"`) |
| **QoS** | 1 (at-least-once delivery, configured in `event_handlers.subscriptions.qos`) |
| **Purpose** | Triggers the wedding-alert notification flow. The gateway reads this event, wraps it in a prompt, and delegates to the OrchestratorAgent. |

**Payload (published by the S3 connector, JSON)**:
```jsonc
{
  "bucket":         "wedding-docs",
  "key":            "signed-contract.pdf",
  "event":          "ObjectCreated",
  "correlation_id": "abc-123"           // used to correlate the response topic
}
```

**Gateway transformation** (from `event_handlers[].input_expression`):
```yaml
input_expression: >
  "A wedding alert was received, please notify the guests on LINE:
   {{json://input.payload}}"
target_agent_name: "OrchestratorAgent"
```

The gateway renders this template with the raw JSON payload and sends an A2A
`message/send` request to
`default_namespace/a2a/v1/agent/request/OrchestratorAgent`.
From there the standard A2A flow takes over (§1.4 → §1.7/1.8).

#### 1.17.2 Outbound response topics

After the OrchestratorAgent replies, the gateway publishes the result on:

| Topic | Handler | Payload | Purpose |
|---|---|---|---|
| `event_mesh/responses/{correlation_id}` | `success_response_handler` | Plain text (the agent's reply text) | Successful outcome — forwarded to whoever published the original alert |
| `event_mesh/errors/{correlation_id}` | `error_response_handler` | JSON (A2A error object) | Propagates agent failures back to the publisher |

`{correlation_id}` is forwarded from the inbound message's **user property**
`correlation_id` via the gateway's `forward_context` config. If the publisher does not
set this user property, the `{{text://user_data.forward_context:correlation_id}}`
expression evaluates to an empty string and the response topic becomes
`event_mesh/responses/` (no suffix).

**Success payload**: plain UTF-8 text (e.g. `"LINE notification sent: venue booking confirmed."`).

**Error payload**:
```jsonc
{
  "type": "error",
  "error": {
    "type": "internal_error",
    "message": "..."
  }
}
```

#### 1.17.3 How it uses the SAM control plane internally

The Event Mesh Gateway is still a SAM gateway internally — it uses the same A2A topics
as the WebUI gateway to communicate with agents:

- Publishes the agent request on `default_namespace/a2a/v1/agent/request/OrchestratorAgent` (§1.4)
- Receives streaming status on `default_namespace/a2a/v1/gateway/status/event-mesh-gw-01/>` (§1.7)
- Receives the final response on `default_namespace/a2a/v1/gateway/response/event-mesh-gw-01/{task_id}` (§1.8)

Its gateway ID is `event-mesh-gw-01` (set in `app_config.gateway_id`).

---

## 4. Full topic map (one-line summary)

```
wedding/                                 ← data-plane (no SAM namespace prefix)
├── alerts/>                             (1.17.1) S3 Micro Integration Connector publishes here
│
event_mesh/                              ← data-plane response topics
├── responses/{correlation_id}           (1.17.2) gateway success response → plain text
└── errors/{correlation_id}              (1.17.2) gateway error response → A2A error JSON

default_namespace/
├── a2a/
│   ├── v1/
│   │   ├── discovery/
│   │   │   ├── agentcards                            (1.1)  agent self-advert
│   │   │   └── gatewaycards                          (1.2)  gateway self-advert
│   │   ├── agent/
│   │   │   ├── request/{agent_name}                  (1.4)  delegate IN to agent
│   │   │   ├── response/{delegator}/{sub_task_id}    (1.6)  final result back to delegator
│   │   │   └── status/{delegator}/{sub_task_id}      (1.5)  streaming status back to delegator
│   │   ├── gateway/
│   │   │   ├── response/{gateway_id}/{task_id}       (1.8)  final result to gateway/user
│   │   │   └── status/{gateway_id}/{task_id}         (1.7)  streaming status to gateway
│   │   ├── client/
│   │   │   ├── response/{client_id}                  (1.9)  no-gateway client variant
│   │   │   └── status/{client_id}/{task_id}          (1.9)  no-gateway client variant
│   │   ├── trust/{component_type}/{component_id}     (1.10) signed identity card
│   │   └── scheduler/
│   │       ├── response/{instance_id}                (1.15) background task result
│   │       └── status/{instance_id}                  (1.15) background task progress
│   └── events/
│       └── agent/deregistered                        (1.14) legacy de-registration
├── sam/
│   ├── events/
│   │   ├── session/deleted                           (1.11)
│   │   ├── session/compact_request                   (1.11)
│   │   ├── session/compact_response                  (1.11)
│   │   └── deep_research/plan_response               (1.12)
│   └── v1/
│       └── feedback/submit                           (1.13) user thumbs-up/down
└── configuration/
    └── model/
        ├── bootstrap/>                               (1.16) dynamic model provider
        └── response/{model_id}/{component_id}        (1.16)
```

---

## 5. References

- Topic builders: `solace_agent_mesh/common/a2a/protocol.py`
- Event envelopes: `solace_agent_mesh/common/a2a/events.py`, `common/sam_events/event_service.py`
- A2A type schema: `a2a/types.py` (the `a2a_sdk` package, v0.3.7)
- Signal-data JSON Schemas: `solace_agent_mesh/common/a2a_spec/schemas/`
- Wildcard semantics: see `subscription_to_regex()` in `protocol.py:301`
- Event Mesh Gateway config: `configs/gateways/event_mesh_gateway.yaml`
- Orchestrator config (LINE tool, event monitoring): `configs/agents/main_orchestrator.yaml`
