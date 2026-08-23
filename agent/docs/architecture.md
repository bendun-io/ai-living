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
 (in-process)  utils-lists     (stub)
                   │
                   ▼
            utils/lists-service
            (lists, items, audit)

   Agent ──► POST $CALLBACK_URL ──► n8n callback workflow
```

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
  ├─ if ENABLE_MCP:  register MCP tools     # currently discovers nothing (stub)
  ├─ if ENABLE_UTILS_LISTS_TOOLS:
  │     fetch_rest_tool_definitions(base)   # GET /agent/tool-definitions
  │     register each as a RestTool         # failure is caught + recorded, not fatal
  ├─ choose LLM client
  │     OPENAI_API_KEY set  → OpenAIResponsesClient
  │     otherwise           → LocalLLMClient (rule-based fallback)
  └─ AgentService(llm, registry, executor, memory, callback, skills)
```

Two consequences worth knowing:

- **Tool discovery happens once, at startup.** If `utils-lists` is unavailable at that moment,
  the agent starts healthy but with no list tools until it is restarted. The failure is surfaced
  through `utilsListsDiscoveryError` in `/health`.
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
        ├─ 4. loop, at most max_iterations (5):
        │        plan = llm_client.plan(messages, registry.definitions())
        │        if plan.kind == "final":  result_text = plan.final_answer; break
        │        append synthetic assistant message carrying the tool calls
        │        for each tool call:
        │            record trace  →  ToolExecutor.execute  →  append {"role":"tool", ...}
        │            if it was search_skills: record the skill names it returned
        │
        ├─ 5. debug = DebugTrace(skillsRead=skills consulted, toolsUsed=[...])
        ├─ 6. build AgentRunResponse
        ├─ 7. memory.append(user prompt); memory.append(final answer)
        ├─ 8. callback_client.send(CallbackPayload(**response))   # awaited inline
        └─ 9. return the response body to the caller
```

Notes on the loop as implemented:

- `result_text` is initialised to `request.message`. If the loop exhausts all five iterations
  without the model producing a final answer, the agent returns the **user's own message** as the
  result, with no error marker.
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

`ToolRegistry` is a name-keyed dict with `register`, `get`, `has_tool`, `tool_names` and
`definitions()` (which projects tools into `ToolSchema` objects for the LLM). Registration is
last-write-wins: a discovered tool can silently shadow a local tool with the same name.

`ToolExecutor` wraps invocation so a failing tool becomes a structured
`ToolResult(ok=False, error=...)` rather than an exception — **except** for the registry lookup
itself, which happens outside the `try` block.

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

Entries missing `name` or `endpoint` are skipped. Each `execute` opens a fresh
`httpx.AsyncClient` with a 30 s timeout, POSTs the arguments as JSON, raises for non-2xx, and
returns parsed JSON (or `{"text": ...}` for non-JSON responses).

The counterpart service, [`utils/lists-service`](../../utils/lists-service), currently publishes
13 tools: `lists_get|search|create|update|delete`, `items_get|search|create|update|delete`, and
`audit_get|search|revert`.

This is the key extensibility seam: **a new backing service needs no agent code change**, only a
`/agent/tool-definitions` endpoint and an environment variable.

### 5.3 MCP adapter — [`adapters/mcp.py`](../src/tools/adapters/mcp.py)

A placeholder. `discover_tools()` returns an empty list and `execute()` returns
`{"status": "not_implemented", ...}`. Setting `ENABLE_MCP=true` therefore registers nothing.
`_DynamicTool` in [`agent.py`](../src/agent/agent.py) is the wrapper that would adapt discovered
MCP tool dicts to `ToolProtocol` once discovery is real.

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

1. `$SKILLS_DIR` (mounted at `/app/skills` by Docker Compose)
2. `<repo root>/skills`
3. any `skills/` folder in the first six parent directories
4. otherwise an in-code fallback catalog of two skills

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

## 8. Memory

`MemoryStore` is a plain in-process `dict[str, list[dict]]` keyed by `conversationId`. It has no
eviction, no size cap, no persistence, and no locking. `MEMORY_PROVIDER` is read into `Settings`
but never consulted — there is no Postgres/Redis path yet.

Practical implications: conversation history is lost on restart, is not shared between replicas or
uvicorn workers, and grows unboundedly for long-lived conversation ids.

---

## 9. Callbacks

`CallbackClient` POSTs the `CallbackPayload` to `CALLBACK_URL` if configured, with a 30 s timeout.
Any exception is caught and logged at WARNING — a failed callback never fails the run. There is no
retry, no dead-letter, and no signing/authentication of the outbound request.

The abstraction is thin enough that a Kafka or queue-based implementation could be dropped in
behind the same `send(payload)` signature, as `Spec.md` anticipates.

---

## 10. Configuration

All configuration is environment-driven through the frozen-ish `Settings` dataclass:

| Variable | Default | Effect |
| --- | --- | --- |
| `AGENT_HOST` | `0.0.0.0` | Read into settings; the Dockerfile hardcodes uvicorn's bind |
| `AGENT_PORT` | `8000` | Same as above |
| `OPENAI_API_KEY` | — | Selects `OpenAIResponsesClient` vs `LocalLLMClient` |
| `OPENAI_MODEL` | `gpt-4.1-mini` | Model id for chat completions |
| `CALLBACK_URL` | — | Result delivery target; unset disables callbacks |
| `ENABLE_MCP` | `false` | Enables the (stub) MCP discovery path |
| `MCP_SERVERS` | — | Comma-separated server URLs |
| `MEMORY_PROVIDER` | `memory` | Parsed but unused |
| `LOG_LEVEL` | `info` | Root log level |
| `ENABLE_UTILS_LISTS_TOOLS` | `false` | Enables REST tool discovery |
| `UTILS_LISTS_BASE_URL` | `http://utils-lists:8010` | Discovery + execution base URL |
| `SKILLS_DIR` | — | Overrides skill catalog location |

Booleans accept `1/true/yes/on`. Lists are comma-separated with whitespace trimmed.

---

## 11. Deployment

[`Dockerfile`](../Dockerfile): `python:3.11-slim`, installs
[`requirements.txt`](../requirements.txt) (FastAPI 0.115.6, uvicorn 0.34.0, httpx 0.28.1,
openai 1.59.7, PyYAML 6.0.2), copies only `src/`, exposes 8000, runs
`uvicorn src.app:app --host 0.0.0.0 --port 8000` as root. There is no `HEALTHCHECK` and no
non-root user.

[`docker-compose.yml`](../docker-compose.yml): one `agent` service on the shared external-style
`ai-living` network, host port `8000:8000`, `../skills` mounted read-only at `/app/skills`, and
`host.docker.internal` mapped to the host gateway so the default `CALLBACK_URL` can reach an n8n
webhook on the host.

Because tool discovery and memory both live in the process, the service is currently
**single-instance by design**. Horizontal scaling requires externalising memory first.

---

## 12. Tests

Four scripts under [`tests/`](../tests):

- `skill_library_smoke.py`, `local_planner_lists_smoke.py`, `debug_trace_smoke.py` — pytest-style
  assert functions, runnable in-process.
- `callback_smoke.py` — a full end-to-end harness that boots Docker Compose, starts a local HTTP
  listener as the callback target, exercises `/health` and `/agent/run`, and asserts the callback
  envelope.

The `*_smoke.py` naming does not match pytest's default discovery patterns (`test_*.py` /
`*_test.py`), and `pytest` is not in `requirements.txt`.

---

## 13. Extension points, ranked by cost

| I want to… | Change needed |
| --- | --- |
| Add a backing service as tools | Publish `/agent/tool-definitions`, set an env var. **No agent code.** |
| Add an in-process tool | Add a dataclass to `adapters/local.py`, list it in `build_local_tools` |
| Add a skill | Add an entry to `skills/catalog.yml` and a `Skill.md` |
| Swap the LLM provider | New class with `.plan(messages, tools)`, one branch in `initialize()` |
| Swap result delivery | New class with `.send(payload)` |
| Persist memory | Implement the `load`/`append` pair over Postgres/Redis and honour `MEMORY_PROVIDER` |
| Real MCP support | Implement `discover_tools`/`execute` in `adapters/mcp.py`; `_DynamicTool` already fits |

The reasoning loop in `AgentService.run` should not need to change for any of these — which is the
core property the architecture is aiming for.
