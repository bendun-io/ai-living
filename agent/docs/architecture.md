# Agent Architecture

This document describes how the `agent` service in this repository is built: its layers, the
request lifecycle, the pluggable abstractions, and the runtime/deployment shape.

It reflects the code as it exists in [`agent/src`](../src), not the aspirational design in
[`Spec.md`](../Spec.md). Where the two differ, this document notes it.

---

## 1. Purpose and position in the system

The agent is the **reasoning layer** of the `ai-living` stack. It is deliberately *not* the
orchestration layer — n8n owns triggers, scheduling, retries, integrations and delivery.

```
   n8n trigger workflow
            │  POST /agent/run
            ▼
   ┌────────────────────────┐
   │     Agent Service      │   ← this repo folder
   │  FastAPI + reasoning   │
   └───────┬────────────────┘
           │ tool calls
   ┌───────┴───────┬──────────────┬───────────────┐
   ▼               ▼              ▼               ▼
 Local tools   REST adapter   MCP adapter     (future)
 (in-process)  utils-lists   (mcp SDK client)
                   │
                   ▼
            utils/lists-service
            (lists, items, audit —
             revert withheld)

   Agent ──► POST $CALLBACK_URL ──► n8n callback workflow
```

The MCP adapter is a real client (§5.3), not a stub — it connects to remote MCP servers over
`streamable_http` or `sse` using the official `mcp` SDK.

The agent returns its result **twice**: synchronously in the HTTP response *and* asynchronously
to the configured callback URL. See §4.

---

## 2. Layer map

| Layer | Module | Responsibility |
| --- | --- | --- |
| HTTP app | [`src/app.py`](../src/app.py) | FastAPI instance, `/health`, startup hook, router mounting |
| Routing | [`src/routes/run.py`](../src/routes/run.py) | `POST /agent/run` → runtime |
| Composition root | [`src/agent/agent.py`](../src/agent/agent.py) | `AgentRuntime`: wiring, tool discovery, health snapshot |
| Reasoning loop | [`src/agent/executor.py`](../src/agent/executor.py) | `AgentService.run` — the plan/execute loop |
| Prompting | [`src/agent/planner.py`](../src/agent/planner.py), [`src/agent/prompts.py`](../src/agent/prompts.py) | Builds system/user/tool prompt strings |
| LLM | [`src/llm/openai_client.py`](../src/llm/openai_client.py) | `OpenAIResponsesClient`, `LocalLLMClient` |
| Tools | [`src/tools/registry.py`](../src/tools/registry.py), [`src/tools/executor.py`](../src/tools/executor.py) | Uniform tool registry + safe invocation |
| Tool adapters | [`src/tools/adapters/`](../src/tools/adapters/) | `local.py`, `rest.py`, `mcp.py` |
| Skills | [`src/skills/library.py`](../src/skills/library.py) | Loads the shared `skills/` catalog |
| Memory | [`src/memory/memory.py`](../src/memory/memory.py) | Per-conversation message history |
| Callback | [`src/callbacks/callback.py`](../src/callbacks/callback.py) | Fire-and-forget POST of the result |
| Config | [`src/config.py`](../src/config.py) | `Settings.from_env()` |
| Contracts | [`src/models.py`](../src/models.py) | Pydantic request/response/tool models |
| Logging | [`src/observability/trace.py`](../src/observability/trace.py) | `logging.basicConfig` wrapper |

The package layout mirrors the structure proposed in `Spec.md`, with `logging/` renamed to
`observability/` and an added `skills/` package.

---

## 3. Startup and composition

`src/app.py` performs work at **import time**, not inside a factory:

1. `Settings.from_env()` reads all configuration from environment variables.
2. `configure_logging(settings.log_level)` installs a root logging config.
3. `AgentRuntime(settings=...)` is constructed (cheap — no I/O).
4. `FastAPI(...)` is created and the run router is mounted.
5. On the FastAPI `startup` event, `runtime.initialize()` runs the I/O-bound wiring.

`AgentRuntime.initialize()` is the single composition root:

```
initialize()
  ├─ SkillLibrary.default()                 # loads skills/catalog.yml (or fallback)
  ├─ ToolRegistry()
  ├─ register local tools                   # echo, search_skills
  ├─ if ENABLE_MCP:
  │     load_mcp_server_configs(file)       # config/mcp-servers.json
  │     refresh_mcp_tools()                 # list_tools per server, prefixed
  │     start the hourly refresh task       # MCP_REFRESH_INTERVAL_SECONDS
  ├─ if ENABLE_UTILS_LISTS_TOOLS:
  │     fetch_rest_tool_definitions(base)   # GET /agent/tool-definitions
  │     register each as a RestTool         # failure is caught + recorded, not fatal
  ├─ choose LLM client
  │     OPENAI_API_KEY set  → OpenAIResponsesClient
  │     otherwise           → LocalLLMClient (rule-based fallback)
  └─ AgentService(llm, registry, executor, memory, callback, skills)
```

Two consequences worth knowing:

- **REST tool discovery happens once, at startup.** If `utils-lists` is unavailable at that
  moment, the agent starts healthy but with no list tools until it is restarted. The failure is
  surfaced through `utilsListsDiscoveryError` in `/health`. MCP discovery does not share this
  limitation — it re-runs on a timer (§5.3).
- **The LLM choice is implicit.** A missing `OPENAI_API_KEY` silently degrades the service to the
  regex-based `LocalLLMClient`; `/health` does not report which planner is active.

`AgentRuntime.run()` also lazily calls `initialize()` if the service is still `None`, which is the
path used by tests that bypass the FastAPI startup event.

---

## 4. Request lifecycle

```
POST /agent/run  (AgentRunRequest)
        │
        ▼
AgentRuntime.run ──► AgentService.run
        │
        ├─ 1. memory_store.load(conversationId)
        │      └─ _chat_safe_memory(): keep only system/user/assistant string messages
        │
        ├─ 2. build_prompt_bundle(request, registry.definitions(), skills)
        │      system_prompt = base instruction + skill brief context
        │      user_prompt   = request.message.strip()
        │      tool_context  = rendered tool list  (built but not sent — see note)
        │
        ├─ 3. messages = [system, *memory, user]
        │
        ├─ 4. loop, at most max_iterations (10):
        │        plan = llm_client.plan(messages, registry.definitions())
        │        if plan.kind == "final":  result_text = plan.final_answer; break
        │        append synthetic assistant message carrying the tool calls
        │        for each tool call:
        │            record trace  →  ToolExecutor.execute  →  append {"role":"tool", ...}
        │            if it was search_skills: record the skill names it returned
        │
        │      if the loop exhausted max_iterations without a "final" plan:
        │        result_text = LOOP_EXHAUSTED_MESSAGE.format(max_iterations)
        │
        ├─ 5. debug = DebugTrace(skillsRead=skills consulted, toolsUsed=[...])
        ├─ 6. build AgentRunResponse
        ├─ 7. memory.append(user prompt); memory.append(final answer)
        ├─ 8. callback_client.send(CallbackPayload(**response))   # awaited inline
        └─ 9. return the response body to the caller
```

Notes on the loop as implemented:

- `result_text` is initialised to `request.message`, but that is only a placeholder now: if the
  loop exhausts `max_iterations` without the model producing a `"final"` plan,
  `result_text` is overwritten with a fixed message — `"The agent's reasoning loop has been
  exhausted after N step(s) without reaching a final answer. No solution was found."` — instead of
  echoing the caller's own input back. This is still a plain `200` response with no error marker or
  machine-readable flag; callers detect it by matching the fixed string (see
  [`review.md#c5`](./review.md#c5)).
- `prompt_bundle.tool_context` is computed but never added to `messages`. Tool awareness reaches
  the model exclusively through the native `tools` parameter of the OpenAI call, so the string is
  currently dead weight.
- `skillsRead` is accumulated during the loop rather than read off the library at the end: each
  successful `search_skills` result contributes the names it matched, in first-seen order, with
  duplicates dropped. A run that never calls the tool reports an empty list.
- Only the user prompt and the final answer are persisted to memory. Intermediate assistant
  tool-call messages and tool results are discarded once the run ends, so a follow-up turn has no
  record of what tools were used.
- The callback is awaited **before** the HTTP response is returned, so callback latency is added
  to the caller's latency. Delivery errors are swallowed and logged.

---

## 5. The tool abstraction

Everything the model can call satisfies one structural protocol
([`registry.py`](../src/tools/registry.py)):

```python
class ToolProtocol(Protocol):
    name: str
    description: str
    input_schema: dict[str, Any]
    async def execute(self, arguments: dict[str, Any]) -> Any: ...
```

`ToolRegistry` is a name-keyed dict with `register`, `get`, `find`, `has_tool`, `tool_names`,
`collisions()` and `definitions()` (which projects tools into `ToolSchema` objects for the LLM).

Registration is last-write-wins, but not silent: if a name is already taken, the clash is appended
to a collision list as `{"name", "replaced", "replacedBy"}` (the tool name plus both class names)
and logged at WARNING. `collisions()` returns a copy of that list, and it is surfaced as
`toolNameCollisions` in `GET /health`. The replacement still happens — refusing it would make the
winner depend on discovery order, which is what made the original behaviour hard to reason about —
so the design goal is visibility, not prevention.

`get()` raises `KeyError` for callers wanting a strict lookup; `find()` returns `None` instead.

`ToolExecutor` wraps invocation so every outcome becomes a structured `ToolResult`:

| Outcome | Result |
| --- | --- |
| Success | `ok=True`, `output=<tool return value>` |
| Tool raised | `ok=False`, `error=str(exception)` |
| Name not registered | `ok=False`, `error="Unknown tool 'x'. Available tools: …"` |

The unknown-tool case uses `find()` and never raises, so a hallucinated or stale tool name is a
recoverable step rather than a failed run. The error text lists the registered tool names and is
fed back to the planner as tool output, giving it what it needs to retry with a real name.

### 5.1 Local adapter — [`adapters/local.py`](../src/tools/adapters/local.py)

Two in-process tools, always registered:

- `echo` — returns its arguments. Used by smoke tests and by the `LocalLLMClient` fallback.
- `search_skills` — keyword search over the `SkillLibrary`, with an `include_details` flag that
  switches between summaries and full skill descriptions.

### 5.2 REST adapter — [`adapters/rest.py`](../src/tools/adapters/rest.py)

The production tool source. At startup it performs
`GET {UTILS_LISTS_BASE_URL}/agent/tool-definitions` and maps each entry to a `RestTool`:

| Discovery field | Use |
| --- | --- |
| `name` | Tool name exposed to the LLM (required) |
| `endpoint` | Absolute URL, or a path joined onto the base URL (required) |
| `method` | HTTP verb, uppercased, default `POST` |
| `description` | Passed to the LLM |
| `input_schema` | Passed to the LLM as JSON-Schema parameters |

Entries missing `name` or `endpoint` are skipped. Each `execute` reuses the `AgentRuntime`'s
shared `httpx.AsyncClient` (30 s timeout, opened at startup and closed at shutdown), POSTs the
arguments as JSON, raises for non-2xx, and returns parsed JSON (or `{"text": ...}` for non-JSON
responses).

The counterpart service, [`utils/lists-service`](../../utils/lists-service), defines 13 tools but
publishes only 12 to agents: `lists_get|search|create|update|delete`,
`items_get|search|create|update|delete`, and `audit_get|search`.

`audit_revert` is deliberately withheld. `AGENT_EXCLUDED_TOOLS` in the service's `core.py` filters
`TOOL_DEFINITIONS` into `AGENT_TOOL_DEFINITIONS`, and only the latter is served from
`/agent/tool-definitions` — so the agent never discovers it and cannot register or call it.
Reverting a mutation is irreversible and stays a human action, available over HTTP to the web UI
and operators. The exclusion lives in the service that owns the capability rather than in an agent
allow-list, so a new agent gets the safe catalogue by default.

This is the key extensibility seam: **a new backing service needs no agent code change**, only a
`/agent/tool-definitions` endpoint and an environment variable.

### 5.3 MCP adapter — [`adapters/mcp.py`](../src/tools/adapters/mcp.py)

The second live tool source. `ENABLE_MCP=true` makes the runtime read `MCP_SERVERS_FILE`
(default [`config/mcp-servers.json`](../config/mcp-servers.json)) and connect to each server
listed there with the official `mcp` client SDK.

```json
{
  "servers": [
    {
      "name": "homeassistant",
      "url": "http://homeassistant.local:8123/api/mcp",
      "enabled": true,
      "prefix": "ha_",
      "transport": "streamable_http",
      "tokenEnv": "HOMEASSISTANT_TOKEN",
      "timeoutSeconds": 30
    }
  ]
}
```

| Field | Default | Use |
| --- | --- | --- |
| `name` | — | Identifies the server in logs and `/health` (required) |
| `url` | — | MCP endpoint (required) |
| `enabled` | `true` | `false` skips the entry without deleting it |
| `prefix` | `<name>_` | Prepended to every tool name; `""` opts out |
| `transport` | `streamable_http` | Or `sse` for servers that only speak the older transport |
| `tokenEnv` / `token` | — | Bearer token; `tokenEnv` names an env var |
| `headers` | `{}` | Extra request headers |
| `timeoutSeconds` | `30` | Per-request HTTP timeout |

`url`, `token` and header values expand `${VAR}` from the environment, so the file carries
configuration and the environment carries secrets — which is what lets the file be committed.
Entries missing `name` or `url` are skipped with a warning rather than failing the whole file; a
missing or malformed file is recorded as `mcpConfigError` in `/health` and leaves the agent
running with its other tools.

**Why prefixes are on by default.** MCP servers name their own tools with no knowledge of each
other, so two servers can both publish `GetLiveContext`. The registry's last-write-wins rule
would silently resolve that in discovery order. Prefixing makes the collision impossible rather
than merely visible; `MCPTool` keeps the un-prefixed `remote_name` and calls the server with that,
so the namespacing stays purely local.

**Sessions are per call.** `MCPToolAdapter` opens a session for each `list_tools`/`call_tool` and
closes it again. Streamable HTTP is stateless, so a dropped connection or a server restart costs
one failed call instead of leaving a long-lived session wedged. The price is an `initialize`
handshake per tool call.

A tool that reports `isError` is re-raised as a `RuntimeError`, so `ToolExecutor` records it as a
failed `ToolResult` carrying the server's message — the same shape a local tool raising produces,
and recoverable by the planner on the next iteration.

**Discovery repeats.** `AgentRuntime` re-runs discovery every `MCP_REFRESH_INTERVAL_SECONDS`
(default 3600, `0` disables the timer) in a background task cancelled on FastAPI shutdown. Each
refresh unregisters that server's previous tool names and registers the new listing, so a tool the
server has withdrawn stops being callable. A server that fails discovery **keeps its previous
tools** and records the error in `/health`: a network blip should not silently shrink what the
planner can do. A refresh that lands mid-run can remove a tool the planner is about to call, which
surfaces as the ordinary unknown-tool `ToolResult` rather than as a crash.

`/health` reports one `mcpServers` entry per configured server with its prefix, tool count, last
error, and last attempt/success timestamps.

---

## 6. The LLM abstraction

`AgentService` depends on a duck-typed client exposing:

```python
async def plan(messages: list[dict], tools: list[ToolSchema]) -> LLMPlan
```

`LLMPlan` is a small union: `kind="final"` with `final_answer`, or `kind="tool_calls"` with a list
of `ToolInvocation`.

### 6.1 `OpenAIResponsesClient`

Despite the name, it calls **Chat Completions** (`client.chat.completions.create`), not the
Responses API. It converts `ToolSchema` into the `{"type": "function", "function": {...}}` payload
shape, sets `tool_choice="auto"` when tools exist, and maps the reply back into an `LLMPlan`.
`tool_call.id` from the provider is not carried into `ToolInvocation.call_id`.

### 6.2 `LocalLLMClient`

A deterministic, no-network fallback used whenever `OPENAI_API_KEY` is unset. It is a
hand-written intent router of roughly 280 lines:

- `_plan_list_tool_call` matches keyword intents (`create`/`search`/`get`/`update`/`delete` ×
  `list`/`item`) in a fixed if-chain, extracts arguments with regexes (quoted strings, UUID
  pattern, `name`/`description`/`status`/`notes` key-value scraping), and emits a single tool call.
- It can chain one step: `_list_id_from_latest_search` re-reads the most recent `lists_search`
  tool result out of `messages` to resolve a list name into an id.
- If no list intent matches and `echo` is available, it echoes; otherwise it returns the user
  message as the final answer.

This makes the service demoable and testable offline, but it is a keyword matcher, not a planner —
its intent precedence is order-sensitive (see the review doc).

---

## 7. Skills

`SkillLibrary` ([`skills/library.py`](../src/skills/library.py)) loads the repo-level
[`skills/`](../../skills) directory — `catalog.yml` for `name`/`summary`/`keywords`, and
`<name>/Skill.md` for the long description. Resolution order for the directory:

1. `$SKILLS_DIR` if it exists (mounted at `/app/skills` by Docker Compose)
2. otherwise the nearest ancestor directory containing a `skills/catalog.yml`
3. otherwise an in-code fallback catalog of two skills

Step 2 walks `Path(__file__).resolve().parents` to its natural end rather than a fixed depth, and
tests for `catalog.yml` rather than for a directory called `skills`. Both details matter: a fixed
range raised `IndexError` in the container, where the module has only four parents, and a bare
existence check matches `agent/src/skills` — this package's own directory — before the repo-root
catalogue.

Skills are injected in two ways: every skill's one-line summary is appended to the system prompt
via `brief_context()`, and the `search_skills` tool lets the model pull full descriptions on
demand. This is a deliberate two-tier design — cheap always-on hints, expensive detail by request.

`DebugTrace.skillsRead` reports the second tier only. `AgentService._record_consulted_skills`
inspects each tool result, and for successful `search_skills` calls appends the `name` of every
match to a per-run list, preserving first-seen order and skipping duplicates. So the field answers
"which skills did this run actually pull up?" — not "what is in the catalogue?", which `/health`
and `brief_context()` already cover. The always-on summaries are deliberately excluded: they are
the catalogue, identical on every run, and counting them would make the field constant again.

The tracking is run-scoped state inside `run()`, not state on the shared `SkillSearchTool`
instance, so concurrent requests cannot contaminate each other's traces. The tool name is matched
against the `SKILL_SEARCH_TOOL_NAME` constant exported by
[`adapters/local.py`](../src/tools/adapters/local.py), which is also the tool's own default name.

---

## 8. Persona

The system prompt's identity, tone, and boundaries live in
[`config/persona.md`](../config/persona.md), a plain-markdown file loaded by
`load_persona()` in [`prompts.py`](../src/agent/prompts.py) — not hardcoded in Python.
Resolution order mirrors `SkillLibrary._default_skills_dir()` (§7):

1. `$PERSONA_FILE` if it points at an existing file
2. otherwise the nearest ancestor directory containing `config/persona.md`
3. otherwise an in-code fallback one-liner (`_FALLBACK_PERSONA`)

`config/` is baked into the Docker image and bind-mounted read-only by Compose (same treatment as
`mcp-servers.json`), so editing `agent/config/persona.md` and restarting the agent is enough to
change identity, tone, or behavioral boundaries — no code change or rebuild required. `SkillLibrary
.brief_context()` is appended after the persona text, so the persona always precedes the
always-on skill summaries in the final system prompt (`build_system_prompt`).

---

## 9. Memory

`MemoryStore` is a plain in-process `dict[str, list[dict]]` keyed by `conversationId`. It has no
eviction, no size cap, no persistence, and no locking. `MEMORY_PROVIDER` is read into `Settings`
but never consulted — there is no Postgres/Redis path yet.

Practical implications: conversation history is lost on restart, is not shared between replicas or
uvicorn workers, and grows unboundedly for long-lived conversation ids.

---

## 10. Callbacks

`CallbackClient` POSTs the `CallbackPayload` to `CALLBACK_URL` if configured, over the
`AgentRuntime`'s shared `httpx.AsyncClient` (30 s timeout). Any exception is caught and logged at
WARNING — a failed callback never fails the run. There is no retry, no dead-letter, and no
signing/authentication of the outbound request.

The abstraction is thin enough that a Kafka or queue-based implementation could be dropped in
behind the same `send(payload)` signature, as `Spec.md` anticipates.

---

## 11. Configuration

All configuration is environment-driven through the frozen-ish `Settings` dataclass:

| Variable | Default | Effect |
| --- | --- | --- |
| `OPENAI_API_KEY` | — | Selects `OpenAIResponsesClient` vs `LocalLLMClient` |
| `OPENAI_MODEL` | `gpt-4.1-mini` | Model id for chat completions |
| `CALLBACK_URL` | — | Result delivery target; unset disables callbacks |
| `ENABLE_MCP` | `false` | Enables MCP discovery |
| `MCP_SERVERS_FILE` | `config/mcp-servers.json` | Per-server MCP config (§5.3) |
| `MCP_REFRESH_INTERVAL_SECONDS` | `3600` | Rediscovery interval; `0` disables it |
| `MEMORY_PROVIDER` | `memory` | Parsed but unused |
| `LOG_LEVEL` | `info` | Root log level |
| `ENABLE_UTILS_LISTS_TOOLS` | `false` | Enables REST tool discovery |
| `UTILS_LISTS_BASE_URL` | `http://utils-lists:8010` | Discovery + execution base URL |
| `SKILLS_DIR` | — | Overrides skill catalog location |
| `PERSONA_FILE` | — | Overrides persona/system-prompt file location (§8) |

Note `SKILLS_DIR` and `PERSONA_FILE` are read directly by `SkillLibrary` and `load_persona()`
respectively, not through `Settings` — they follow the same env-var-first, walk-to-ancestor
resolution but aren't part of the dataclass.

Booleans accept `1/true/yes/on`. `MCP_SERVERS_FILE` may be absolute or relative; a relative
path is resolved against the working directory first, then against the `agent/` project root.

---

## 12. Deployment

[`Dockerfile`](../Dockerfile): `python:3.11-slim`, installs
[`requirements.txt`](../requirements.txt) (FastAPI 0.115.6, uvicorn 0.34.0, httpx 0.28.1,
openai 1.59.7, PyYAML 6.0.2, mcp 1.29.0), copies `src/` and `config/`, exposes 8000, and runs
`uvicorn src.app:app --host 0.0.0.0 --port 8000`.

It runs as the unprivileged `agent` account (uid pinned to 10001, so bind-mounted files keep a
predictable owner across rebuilds) and carries a `HEALTHCHECK` that polls `/health` every 15s with
a 20s start period. The probe uses `python -c` with `urllib` rather than `curl`, which the slim
base does not ship; `urlopen` raises on a non-2xx status, so a process that is up but answering
with an error reports unhealthy.

Note this is liveness, not readiness: `/health` returns `status: "ok"` even when tool discovery
failed, so a container can be `healthy` with no tools registered.

[`docker-compose.yml`](../docker-compose.yml): one `agent` service on the shared external-style
`ai-living` network, host port `8000:8000`, `../skills` mounted read-only at `/app/skills`,
`./config` mounted read-only at `/app/config` so MCP servers can be re-pointed without a
rebuild, and `host.docker.internal` mapped to the host gateway so the default `CALLBACK_URL`
can reach an n8n webhook on the host.

Because tool discovery and memory both live in the process, the service is currently
**single-instance by design**. Horizontal scaling requires externalising memory first.

---

## 13. Tests

Seven scripts under [`tests/`](../tests):

- `skill_library_smoke.py`, `persona_smoke.py`, `local_planner_lists_smoke.py`,
  `debug_trace_smoke.py`, `tool_registry_smoke.py`, `mcp_adapter_smoke.py` — pytest-style assert
  functions, runnable in-process. `mcp_adapter_smoke.py` covers config parsing, prefixing, the
  refresh swap and the keep-previous-tools-on-failure rule against a fake adapter, so it needs no
  MCP server.
- `callback_smoke.py` — a full end-to-end harness that boots Docker Compose, starts a local HTTP
  listener as the callback target, exercises `/health` and `/agent/run`, and asserts the callback
  envelope.

The `*_smoke.py` naming does not match pytest's default discovery patterns (`test_*.py` /
`*_test.py`), and `pytest` is not in `requirements.txt`.

---

## 14. Extension points, ranked by cost

| I want to… | Change needed |
| --- | --- |
| Add a backing service as tools | Publish `/agent/tool-definitions`, set an env var. **No agent code.** |
| Withhold a tool from agents | Add its name to that service's `AGENT_EXCLUDED_TOOLS`. **No agent code.** |
| Add an in-process tool | Add a dataclass to `adapters/local.py`, list it in `build_local_tools` |
| Add a skill | Add an entry to `skills/catalog.yml` and a `Skill.md` |
| Change identity, tone, or boundaries | Edit `config/persona.md`, restart. **No agent code.** |
| Swap the LLM provider | New class with `.plan(messages, tools)`, one branch in `initialize()` |
| Swap result delivery | New class with `.send(payload)` |
| Persist memory | Implement the `load`/`append` pair over Postgres/Redis and honour `MEMORY_PROVIDER` |
| Add an MCP server | Add an entry to `config/mcp-servers.json`. **No agent code.** |

The reasoning loop in `AgentService.run` should not need to change for any of these — which is the
core property the architecture is aiming for.
