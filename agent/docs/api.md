# Agent API & External Interfaces

Everything that crosses the agent's process boundary — inbound HTTP, outbound HTTP, and the
contracts that govern each.

There are four external interfaces:

| # | Interface | Direction | Peer |
| --- | --- | --- | --- |
| 1 | `GET /health`, `POST /agent/run` | inbound | n8n trigger workflow, ops probes |
| 2 | Tool discovery + tool execution | outbound | `utils-lists` (and any REST tool service) |
| 3 | Chat completions | outbound | OpenAI |
| 4 | Result callback | outbound | n8n callback workflow |

> [`agent/API.md`](../API.md) is the short reference at the repo level. This document is the
> complete version: it adds error semantics, the discovery contract, and the outbound calls.

---

## 1. Inbound HTTP API

Base URL in local Docker Compose: `http://localhost:8000`.
There is **no authentication on any endpoint** — see [review.md](./review.md#s1).

FastAPI also serves the generated `GET /openapi.json`, `GET /docs`, and `GET /redoc`.

### 1.1 `GET /health`

Liveness plus a snapshot of what the runtime discovered at startup.

**Response `200`**

```json
{
  "status": "ok",
  "mcpEnabled": false,
  "mcpServersFile": "/app/config/mcp-servers.json",
  "mcpRefreshIntervalSeconds": 3600,
  "mcpConfigError": null,
  "mcpServers": [],
  "utilsListsToolsEnabled": true,
  "utilsListsBaseUrl": "http://utils-lists:8010",
  "utilsListsDiscoveredTools": 12,
  "utilsListsDiscoveryError": null,
  "tools": ["audit_get", "audit_search", "echo", "items_create", "..."],
  "toolNameCollisions": []
}
```

| Field | Type | Meaning |
| --- | --- | --- |
| `status` | string | Always `"ok"` when the process is serving |
| `mcpEnabled` | bool | Value of `ENABLE_MCP` |
| `mcpServersFile` | string | Path of the MCP server config file |
| `mcpRefreshIntervalSeconds` | int | Rediscovery interval; `0` means startup only |
| `mcpConfigError` | string \| null | Last error from reading that file |
| `mcpServers` | object[] | Per-server status: `{"name", "url", "prefix", "tools", "error", "lastSuccessAt", "lastAttemptAt"}` |
| `utilsListsToolsEnabled` | bool | Value of `ENABLE_UTILS_LISTS_TOOLS` |
| `utilsListsBaseUrl` | string | Base URL used for discovery and execution |
| `utilsListsDiscoveredTools` | int | Count of REST tools registered at startup |
| `utilsListsDiscoveryError` | string \| null | Last discovery error, if discovery failed |
| `tools` | string[] | All registered tool names, sorted |
| `toolNameCollisions` | object[] | One entry per name clash seen during registration: `{"name", "replaced", "replacedBy"}`, the tool name plus the class names of the loser and winner. `[]` normally |

Behavioural notes:

- `status` is `"ok"` even when discovery failed — check `utilsListsDiscoveryError` and
  `utilsListsDiscoveredTools`, not just `status`, in a readiness gate.
- Discovery runs **once at startup**. These values never change until the process restarts.
- The payload does **not** reveal whether the OpenAI planner or the offline `LocalLLMClient` is
  active.
- If a request arrives before the startup event completes, `tools` is `[]`.
- A non-empty `toolNameCollisions` means two sources registered the same tool name and the later
  registration won. The agent keeps running; treat it as a misconfiguration to investigate, since a
  discovered remote tool may have shadowed a local one.

### 1.2 `POST /agent/run`

Executes one agent turn for one conversation message. Synchronous: the response returns only
after the reasoning loop finishes *and* the callback POST has been attempted.

**Request body** — `AgentRunRequest`

```json
{
  "conversationId": "smoke-test-1",
  "user": "tester",
  "message": "search lists for \"groceries\"",
  "attachments": [],
  "metadata": {
    "tenant": "local",
    "language": "en",
    "extra": {}
  }
}
```

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `conversationId` | string | **yes** | Memory key. Reusing it replays prior turns into the prompt. |
| `message` | string | **yes** | The user turn. Whitespace is stripped. |
| `user` | string \| null | no | Passed for context only; not used for authorisation. |
| `attachments` | object[] | no | **Accepted and then ignored** — nothing reads this field. |
| `metadata.tenant` | string \| null | no | Echoed back. Not used for tool scoping. |
| `metadata.language` | string \| null | no | Echoed back. Not injected into the prompt. |
| `metadata.extra` | object | no | Free-form; echoed back verbatim. |

Unknown top-level fields are accepted and dropped (default Pydantic behaviour).

**Response `200`** — `AgentRunResponse`

```json
{
  "conversationId": "smoke-test-1",
  "result": "I found 2 lists matching \"groceries\".",
  "toolLog": [
    {
      "tool": "lists_search",
      "arguments": { "query": "groceries", "include_deleted": false, "limit": 20, "offset": 0 },
      "result": {
        "name": "lists_search",
        "ok": true,
        "output": { "lists": [{ "id": "…", "name": "Groceries" }], "total": 1 },
        "error": null
      }
    }
  ],
  "debug": {
    "skillsRead": [],
    "toolsUsed": [{ "tool": "lists_search", "arguments": { "query": "groceries" } }]
  },
  "metadata": { "tenant": "local", "language": "en", "extra": {} }
}
```

| Field | Type | Meaning |
| --- | --- | --- |
| `conversationId` | string | Echoed from the request |
| `result` | string | Final answer text |
| `toolLog` | object[] | Every tool execution, in order, with full arguments and result |
| `toolLog[].result.ok` | bool | `false` when the tool raised; `error` then holds `str(exception)` |
| `debug.skillsRead` | string[] | Skills this run actually consulted — the matches returned by its `search_skills` calls, in first-seen order, de-duplicated. `[]` when no lookup happened |
| `debug.toolsUsed` | object[] | Tools the planner requested, in order (arguments only) |
| `metadata` | object | Echoed from the request |

**Result semantics — read this before building on `result`:**

- Normal path: `result` is the model's final answer.
- Loop exhaustion: if the planner still wants tools after 5 iterations, the loop ends and `result`
  falls back to **the caller's own `message`**, with `toolLog` populated but no error signal.
  Detect it by comparing `result` to the request `message` while `toolLog` is non-empty.
- Tool failure: a failing tool does **not** fail the request. It appears as
  `toolLog[].result.ok == false` and the model gets the error text as tool output.
- Unknown tool: a name the registry does not know is handled the same way, with
  `error: "Unknown tool 'x'. Available tools: …"`. The planner receives the list of real names and
  can retry within the same run.

**Error responses**

| Status | When | Body |
| --- | --- | --- |
| `422` | Missing/invalid `conversationId` or `message` | FastAPI validation error |
| `500` | Unhandled exception in the run (see below) | `{"detail": "Internal Server Error"}` |

The route has no exception handling of its own, so these propagate as bare 500s **and no callback
is sent**. Known triggers:

- The OpenAI call fails (auth, rate limit, network, timeout).
- The model returns tool-call arguments that are not valid JSON.

An unregistered tool name is *not* in this list any more — it is returned as a failed `ToolResult`
and the run continues.

A caller waiting on the callback rather than the response will hang in these cases.

### 1.3 Worked example

```bash
curl -s -X POST http://localhost:8000/agent/run \
  -H 'Content-Type: application/json' \
  -d '{
        "conversationId": "demo-1",
        "user": "fabian",
        "message": "create list \"Groceries\"",
        "attachments": [],
        "metadata": {"tenant": "local", "language": "en", "extra": {}}
      }'
```

PowerShell equivalent, plus a health wait loop, is scripted in [`test.ps1`](../test.ps1).

---

## 2. Outbound — REST tool discovery & execution

Enabled by `ENABLE_UTILS_LISTS_TOOLS=true`. This is how the agent gains real capabilities.

### 2.1 Discovery (startup, once)

```
GET {UTILS_LISTS_BASE_URL}/agent/tool-definitions
```

**Expected response**

```json
{
  "tools": [
    {
      "name": "lists_search",
      "description": "Search lists by name and description with pagination.",
      "endpoint": "/lists/search",
      "method": "POST",
      "input_schema": {
        "type": "object",
        "properties": {
          "query": { "type": "string" },
          "include_deleted": { "type": "boolean" },
          "limit": { "type": "integer" },
          "offset": { "type": "integer" }
        }
      }
    }
  ]
}
```

Contract as implemented in [`adapters/rest.py`](../src/tools/adapters/rest.py):

| Field | Required | Handling |
| --- | --- | --- |
| `name` | **yes** | Becomes the tool name shown to the LLM. Entry skipped if blank. |
| `endpoint` | **yes** | Absolute `http(s)://…` used as-is; otherwise joined onto the base URL. Entry skipped if blank. |
| `method` | no | Uppercased; defaults to `POST` |
| `description` | no | Passed to the LLM verbatim |
| `input_schema` | no | Must be an object; anything else is replaced with `{}` |

A publishing service may withhold tools from agents while keeping their HTTP endpoints live: keep
the definition out of this response and it is never discovered. `utils-lists` does this for
`audit_revert` via `AGENT_EXCLUDED_TOOLS`.

Discovery uses a 30 s timeout and raises for non-2xx. A failure is caught by the runtime, recorded
in `utilsListsDiscoveryError`, and the agent starts **without** those tools. There is no retry and
no re-discovery endpoint — recovery requires a restart.

Any service implementing this endpoint can supply tools; nothing is specific to `utils-lists`.

### 2.2 Execution (per tool call)

```
{method} {endpoint}
Content-Type: application/json
<the model's tool arguments, verbatim>
```

Calls reuse the `AgentRuntime`'s shared `httpx.AsyncClient` (30 s timeout, opened at startup and
closed at shutdown). Non-2xx raises, and the exception text is captured into `ToolResult.error`.
JSON responses are parsed; anything else is wrapped as `{"text": "<body>"}`.

Arguments are **not validated against `input_schema`** before dispatch — the backing service is
the only validator.

### 2.3 Tools currently published by `utils-lists`

Base URL `http://utils-lists:8010` in-network, `http://localhost:8010` from the host.

**12 of its 13 tools are advertised to agents.**

| Tool | Endpoint | Effect |
| --- | --- | --- |
| `lists_get` | `POST /lists/get` | Fetch one list by id |
| `lists_search` | `POST /lists/search` | Search lists by name/description, paginated |
| `lists_create` | `POST /lists/create` | Create a list |
| `lists_update` | `POST /lists/update` | Update list fields |
| `lists_delete` | `POST /lists/delete` | Soft-delete a list |
| `items_get` | `POST /items/get` | Fetch one item by id |
| `items_search` | `POST /items/search` | Search items by title/notes/status, paginated |
| `items_create` | `POST /items/create` | Create an item in a list |
| `items_update` | `POST /items/update` | Update item fields |
| `items_delete` | `POST /items/delete` | Soft-delete an item |
| `audit_get` | `POST /audit/get` | Fetch one audit entry |
| `audit_search` | `POST /audit/search` | Filter audit entries by operation/target |
| ~~`audit_revert`~~ | `POST /audit/revert` | **Withheld from agents.** Endpoint stays live for the web UI and operators; the tool is filtered out of `/agent/tool-definitions` by `AGENT_EXCLUDED_TOOLS`, so no agent can discover or call it |

Mutating tools take an `actor` field; the agent's offline planner always sends `"agent"`.

The 12 advertised tools are exposed to the model with equal standing, **including `lists_delete`
and `items_delete`**. There is still no allow-list, confirmation step, or per-tenant scoping — only
`audit_revert` is withheld, because it is the one irreversible operation. The deletes are
soft-deletes and themselves revertible by a human.

The lists service's own `GET /health` reports both sides of this: `tools` lists what agents can
see, `agentExcludedTools` lists what is deliberately withheld.

### 2.4 MCP servers

`ENABLE_MCP=true` makes the runtime read `MCP_SERVERS_FILE` (default
[`config/mcp-servers.json`](../config/mcp-servers.json)) and connect to each server with the
official `mcp` client SDK over Streamable HTTP (or SSE, per entry). Every discovered tool is
registered under `<prefix><remote name>` — `ha_HassTurnOn` for the Home Assistant example — and
called on the server under its un-prefixed name.

Home Assistant needs no add-on for this: enable its built-in **Model Context Protocol Server**
integration, expose the entities the agent may touch under Settings → Voice assistants → Expose,
and point an entry at `http://<ha-host>:8123/api/mcp` with a long-lived access token in the env
var named by `tokenEnv`. What the agent can reach is decided on the Home Assistant side, the same
way `audit_revert` is withheld by the lists service rather than by an agent allow-list.

Discovery runs at startup and then every `MCP_REFRESH_INTERVAL_SECONDS` (default 3600). A refresh
replaces that server's tools; a server that fails discovery keeps the tools it published last time
and reports the error under `mcpServers[].error` in `/health`. A tool that returns an MCP error is
recorded as a **failed** `ToolResult` carrying the server's message, not as a successful one.

See [architecture.md §5.3](architecture.md) for the config schema and the design rationale.

---

## 3. Outbound — OpenAI

Used only when `OPENAI_API_KEY` is set.

- Endpoint: `POST https://api.openai.com/v1/chat/completions` via the `openai` SDK
  (`AsyncOpenAI.chat.completions.create`). Note the class is named `OpenAIResponsesClient` but does
  not use the Responses API.
- Model: `OPENAI_MODEL`, default `gpt-4.1-mini`.
- Tools are sent in the legacy nested shape
  `{"type": "function", "function": {"name", "description", "parameters"}}`, with
  `tool_choice: "auto"` when at least one tool is registered.
- Called up to 10 times per `/agent/run` (`AgentService.max_iterations`).
- No explicit request timeout, no retry policy, no token/cost cap, no streaming.
- The full conversation — system prompt, memory, user message, tool arguments and tool results —
  is sent to OpenAI on every iteration.

When `OPENAI_API_KEY` is absent, no outbound LLM call happens at all; `LocalLLMClient` routes
requests with regex intent matching. The API surface is identical, so callers cannot tell the
difference from the response alone.

---

## 4. Outbound — result callback

If `CALLBACK_URL` is set, the agent POSTs the run result there after the loop completes and before
returning the HTTP response.

```
POST {CALLBACK_URL}
Content-Type: application/json
```

**Body** — `CallbackPayload`, structurally identical to `AgentRunResponse`:

```json
{
  "conversationId": "smoke-test-1",
  "result": "…",
  "toolLog": [ … ],
  "debug": { "skillsRead": [ … ], "toolsUsed": [ … ] },
  "metadata": { "tenant": "local", "language": "en", "extra": {} }
}
```

Delivery semantics:

| Property | Behaviour |
| --- | --- |
| Trigger | Every successful run, exactly once |
| On agent exception | **Not sent** — the run 500s before reaching the callback |
| Timeout | 30 s |
| Failure handling | Caught, logged at WARNING, run still succeeds |
| Retries | None |
| Ordering | Callback completes before the caller's response returns |
| Authentication | None — no signature, token, or shared secret |
| Idempotency | No delivery id; consumers should dedupe on `conversationId` + their own turn tracking |

Default target in Compose:
`http://host.docker.internal:5678/webhook/agentFinished` (an n8n webhook on the host).

Because the result is delivered **both** in the HTTP response and via the callback, an n8n flow
that consumes both will process the same turn twice. Pick one.

⚠️ `toolLog` and `debug.toolsUsed` carry raw tool arguments. Whatever the user typed — and whatever
the model inferred — lands in the callback consumer's logs.

---

## 5. Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `OPENAI_API_KEY` | — | Set → OpenAI planner; unset → offline `LocalLLMClient` |
| `OPENAI_MODEL` | `gpt-4.1-mini` | Chat completions model id |
| `CALLBACK_URL` | — | Result delivery target; unset disables callbacks |
| `ENABLE_MCP` | `false` | Enables MCP tool discovery |
| `MCP_SERVERS_FILE` | `config/mcp-servers.json` | JSON file listing the MCP servers |
| `MCP_REFRESH_INTERVAL_SECONDS` | `3600` | Rediscovery interval; `0` disables the timer |
| `MEMORY_PROVIDER` | `memory` | Parsed but **unused**; memory is always in-process |
| `LOG_LEVEL` | `info` | Root log level |
| `ENABLE_UTILS_LISTS_TOOLS` | `false` | Enables REST tool discovery |
| `UTILS_LISTS_BASE_URL` | `http://utils-lists:8010` | Discovery + execution base URL |
| `SKILLS_DIR` | — | Overrides skill catalog location (`/app/skills` in Compose) |

Booleans accept `1`, `true`, `yes`, `on` (case-insensitive). Lists are comma-separated.

For host-routed development use `UTILS_LISTS_BASE_URL=http://host.docker.internal:8010`.

---

## 6. Integration checklist for an n8n workflow

1. **Trigger workflow** — POST the `AgentRunRequest` envelope to `/agent/run`. Keep business logic
   out of it; pass a stable `conversationId`.
2. **Choose one delivery path.** Either read the synchronous response *or* consume the callback
   webhook — not both.
3. **Set the HTTP timeout generously.** Up to 5 LLM round-trips plus tool calls plus a 30 s
   callback attempt all happen before the response returns.
4. **Treat a 500 as a lost turn.** No callback fires, so a callback-only flow needs its own
   timeout.
5. **Guard against loop exhaustion** — a `result` matching the fixed string "The agent's reasoning
   loop has been exhausted after N step(s) without reaching a final answer. No solution was found."
   means the agent ran out of iterations without the model producing a final answer. It is still a
   `200` with a normal callback, not an error status — there is no machine-readable flag yet, so
   matching on the message text (or checking for a non-trivial `toolLog` alongside a suspiciously
   generic result) is the only detection available today.
6. **`debug.skillsRead` reflects explicit lookups only.** It lists the skills the run pulled up
   via `search_skills`; an empty list means none were consulted, not that none exist. Every
   skill's one-line summary is always in the system prompt regardless — use `GET /health` and the
   `skills/` catalogue to see what was available.
7. **Restart the agent after `utils-lists` restarts** if discovery may have raced — check
   `/health.utilsListsDiscoveredTools`.
8. **Alert on a non-empty `/health.toolNameCollisions`.** It means one tool name was registered
   twice and the later source won, which can silently change what a tool does.
9. **Do not build a revert flow through the agent.** `audit_revert` is withheld by design; call
   `POST /audit/{id}/revert` on the lists service from an n8n step with a human in the loop.
