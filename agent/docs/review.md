# Agent Code Review

A review of the `agent` service as of commit `63bd7a2`. Findings are grouped by severity, each
with the concrete failure it causes and a suggested fix. Where a claim was verified by executing
the code, it is marked **verified**.

Findings that have since been fixed are marked ✅ and kept in place rather than deleted, so the
list stays readable as a record of what was addressed and what still stands.

## Verdict

The skeleton is genuinely good. The four abstractions the spec asked for — `LLMClient`,
`ToolRegistry`, `Memory`, `Callback` — are real, small, and honoured; `AgentService.run` doesn't
know where a tool comes from; and the REST discovery adapter means a new backing service costs
zero agent code. That is the hard part, and it is done.

What's missing is everything between "the happy path works" and "I can leave this running":
no authentication in front of destructive tools, several correctness bugs in the loop that only
surface on multi-step runs, and an offline planner that silently misroutes mutations.

**Blocking for anything beyond local use:** [S1](#s1), [S2](#s2), [C1](#c1), [C2](#c2).

---

## Priority summary

| # | Finding | Severity | Effort |
| --- | --- | --- | --- |
| [S1](#s1) | No authentication on `/agent/run`, which can mutate and delete data | Critical | S |
| [S2](#s2) | Destructive tools (`*_delete`, `audit_revert`) exposed with no guard | Critical | S |
| [C1](#c1) | Offline planner misroutes item operations to list operations — **verified** | Critical | M |
| [C2](#c2) | Unknown tool name raises `KeyError` → 500, no callback | High | XS |
| [C3](#c3) | Malformed tool-call arguments corrupt the transcript — **verified** | High | XS |
| [C4](#c4) | `tool_call.id` dropped; parallel calls to one tool collide | High | XS |
| [C5](#c5) | Loop exhaustion silently returns the user's own message | High | XS |
| [R1](#r1) | Any run exception 500s with no callback — the caller hangs | High | S |
| [R2](#r2) | Tool discovery is startup-only with no retry | Medium | S |
| [R3](#r3) | Memory is in-process, unbounded, and `MEMORY_PROVIDER` is ignored | Medium | M |
| [R4](#r4) | No timeout, retry, or cost cap on OpenAI calls | Medium | S |
| [R5](#r5) | Result delivered twice (response + callback) | Medium | XS |
| [O1](#o1) | Callback has no retry, no signature, no dead-letter | Medium | M |
| [O2](#o2) | Silent degradation to the offline planner is invisible in `/health` | Medium | XS |
| [O3](#o3) | Almost no observability: no correlation id, no timings, no LLM logging | Medium | S |
| [O4](#o4) | Raw tool arguments leak into callbacks and logs | Medium | S |
| [O5](#o5) | Container runs as root, no `HEALTHCHECK` | Medium | XS |
| [Q1](#q1) | Tests aren't discoverable by pytest and aren't in CI | Medium | S |
| [Q2](#q2) | ✅ **Fixed** — `debug.skillsRead` reported every skill, not the ones used | Low | XS |
| [Q3](#q3) | `tool_context` is built and thrown away | Low | XS |
| [Q4](#q4) | `OpenAIResponsesClient` doesn't use the Responses API | Low | XS |
| [Q5](#q5) | MCP adapter is a stub that fails open | Low | S |
| [Q6](#q6) | Registry allows silent name collisions | Low | XS |
| [Q7](#q7) | Deprecated `@app.on_event`; racy lazy `initialize()` | Low | XS |
| [Q8](#q8) | New `httpx.AsyncClient` per call | Low | XS |
| [Q9](#q9) | `AGENT_HOST` / `AGENT_PORT` are read but have no effect | Low | XS |
| [Q10](#q10) | Loose typing at the seams (`llm_client: Any`, untyped `run`) | Low | S |

---

## Security

### <a id="s1"></a>S1 — No authentication on `/agent/run` · Critical

[`routes/run.py`](../src/routes/run.py) mounts the endpoint with no auth dependency, and
[`docker-compose.yml`](../docker-compose.yml) publishes `8000:8000` to the host. Anyone who can
reach the port can make the agent create, update and delete list data, spend OpenAI tokens, and
POST arbitrary results into the n8n callback workflow.

The `user` and `metadata.tenant` fields are accepted but used purely as decoration — no code
consults them for authorisation.

**Fix:** add a shared-secret header dependency (`X-Agent-Token`, compared with
`hmac.compare_digest`) as a minimum, and stop publishing the port to the host once n8n reaches the
agent over the `ai-living` Docker network. Longer term, derive tool scope from `metadata.tenant`
so a tenant can only touch its own data.

### <a id="s2"></a>S2 — Destructive tools exposed with no guard · Critical

All 13 discovered tools are registered with equal standing, including `lists_delete`,
`items_delete` and `audit_revert`. A model hallucination, a prompt injection in a list name that
comes back through `lists_search`, or a misrouted intent ([C1](#c1)) all lead directly to a
mutation with no confirmation step.

Note the injection path is real: tool output is fed straight back into `messages` as content the
model reads, and list/item names are user-controlled.

**Fix, cheapest first:**
1. Config-driven allow-list of tool names (`AGENT_ALLOWED_TOOLS`), default read-only.
2. Mark destructive tools in the discovery contract (`"destructive": true`) and require an
   explicit `metadata.extra.allow_mutations` flag on the request to register them.
3. For irreversible operations, return a confirmation token the caller must echo back.

### <a id="o4"></a>O4 — Raw tool arguments leak into callbacks and logs · Medium

`toolLog[].arguments` and `debug.toolsUsed[].arguments` carry the model's arguments verbatim, and
the whole envelope is POSTed to the callback URL — typically an n8n webhook that persists it. Any
PII in a list title or note ends up in n8n's execution log.

**Fix:** add a redaction pass before building `CallbackPayload`, keyed off field names, and/or a
`DEBUG_TRACE_ENABLED` flag that strips `debug` outside development.

---

## Correctness

### <a id="c1"></a>C1 — Offline planner misroutes item operations to list operations · Critical · **verified**

`_is_create_list_intent` in [`llm/openai_client.py:154`](../src/llm/openai_client.py) is
`"list" in text and any(token in text for token in ["create", "new", "add"])`, and it is checked
**before** `_is_add_item_intent`. Any "add item … to list …" phrasing matches it first.

Verified against the full 15-tool registry:

```
'add item "Milk" to list 1111…'            → lists_create {"name": "Milk", "actor": "agent"}
'delete item 1111… from the list'          → lists_delete {"id": "1111…", "actor": "agent"}
```

The first creates a junk list instead of an item. The second issues a **delete against the wrong
entity type** using an item id — harmless only because that id won't match a list. Phrase it with
a real list id in scope and it deletes the list.

The existing test suite misses this because
[`local_planner_lists_smoke.py`](../tests/local_planner_lists_smoke.py) registers only
`("echo", "items_create")`, so `lists_create` isn't available to shadow the item intent. The tests
pass; production would not.

**Fix:** check item intents before list intents, and require the entity word to be the *object* of
the verb rather than merely present — e.g. match `(add|create|new)\s+item` before any `list`
branch. Then add regression cases that register the **full** tool set, since restricted registries
hide precedence bugs.

### <a id="c2"></a>C2 — Unknown tool name raises `KeyError` → 500 · High

[`tools/executor.py:14`](../src/tools/executor.py):

```python
tool = self.registry.get(invocation.name)   # ← outside the try
try:
    output = await tool.execute(invocation.arguments)
```

`ToolRegistry.get` is a bare `dict[...]` lookup. A hallucinated or renamed tool name raises
`KeyError`, escapes `AgentService.run`, escapes the route, and returns a 500 — killing the whole
run and skipping the callback. `has_tool()` exists but is never called.

**Fix:** move the lookup inside the `try`, or check `has_tool` first and return
`ToolResult(ok=False, error=f"Unknown tool: {name}")`. Returning the error to the model lets it
self-correct on the next iteration, which is the desired behaviour.

### <a id="c3"></a>C3 — Malformed tool-call arguments corrupt the transcript · High · **verified**

[`agent/executor.py:103`](../src/agent/executor.py) builds the synthetic assistant message with:

```python
"arguments": invocation.model_dump_json(exclude={"call_id"})
```

That serialises the **whole invocation**, not its arguments. Verified output:

```json
{"name":"lists_search","arguments":{"query":"x"}}
```

where OpenAI expects `{"query":"x"}`. So from iteration 2 onward the model sees its own past calls
double-wrapped. Symptoms are subtle rather than fatal — degraded multi-step reasoning, repeated
tool calls, occasional argument mimicry of the wrong shape — which makes it easy to misdiagnose as
"the model is bad at this".

**Fix:** `"arguments": json.dumps(invocation.arguments)`.

### <a id="c4"></a>C4 — `tool_call.id` is dropped · High

`OpenAIResponsesClient.plan` constructs `ToolInvocation(name=…, arguments=…)` without
`call_id=tool_call.id` ([`openai_client.py:341`](../src/llm/openai_client.py)). The loop then falls
back to `invocation.call_id or invocation.name` for the correlation id in both the assistant
message and the tool result message.

When the model emits two parallel calls to the same tool — normal for a search fan-out — both get
the id `"lists_search"`, and the two tool results become indistinguishable. Providers reject or
mis-associate duplicate `tool_call_id`s.

**Fix:** carry the id through: `ToolInvocation(name=…, arguments=…, call_id=tool_call.id)`. The
field already exists on the model.

### <a id="c5"></a>C5 — Loop exhaustion silently returns the user's message · High

`result_text` is initialised to `request.message` and only overwritten by a `final` plan. If the
planner still wants tools after `max_iterations` (5), the `for` loop ends normally and the agent
returns the caller's own input as the answer — HTTP 200, no error field, callback fired as if it
succeeded.

**Fix:** track whether a final answer was produced; on exhaustion either (a) make one last LLM call
with `tool_choice="none"` to force a summary, or (b) return an explicit
`"Stopped after N steps without a final answer"` plus a machine-readable flag on the response. Also
make `max_iterations` configurable — it's currently a hardcoded field default.

### <a id="q2"></a>Q2 — `debug.skillsRead` listed every skill · Low · ✅ Fixed

**Was:** `skills_read = self.skill_library.skill_names()` returned the entire catalogue regardless
of what the run touched. The field name promised provenance and delivered a constant, which was
actively misleading when debugging why an answer came out the way it did.

**Now:** [`AgentService.run`](../src/agent/executor.py) accumulates `skills_read` inside the loop.
After each tool execution, `_record_consulted_skills` inspects the result and — for successful
`search_skills` calls — appends the `name` of every match, preserving first-seen order and skipping
duplicates. A run that never looks a skill up now reports `[]` instead of the full catalogue.

Two design notes:

- The always-on summaries that `brief_context()` injects into the system prompt are deliberately
  **not** counted. They are the catalogue, identical on every run; counting them would make the
  field constant again, which is the bug. `skillsRead` means "explicitly pulled up", and the API
  doc says so.
- The tracking list is local to `run()`, not state on the shared `SkillSearchTool` instance, so
  concurrent requests cannot contaminate each other's traces.

The tool name is matched against `SKILL_SEARCH_TOOL_NAME` in
[`adapters/local.py`](../src/tools/adapters/local.py), which also supplies the tool's default
name — one source of truth rather than a duplicated string literal.

Covered by three cases in [`tests/debug_trace_smoke.py`](../tests/debug_trace_smoke.py): the empty
case, the single-lookup case (asserting the result is a strict subset of the catalogue), and
de-duplication across repeated lookups in different iterations. The last two use a scripted stub
LLM client, since the offline `LocalLLMClient` only ever routes to `echo`.

### <a id="q3"></a>Q3 — `tool_context` is computed and discarded · Low

`build_prompt_bundle` produces `tool_context`, and nothing ever reads it — tool awareness reaches
the model only through the native `tools` parameter. `build_tool_context` also has an unreachable
branch: `lines` always starts with `"Available tools:"`, so the `else "No tools are available."`
can never fire.

**Fix:** delete `tool_context` (the native parameter is the right mechanism), or deliberately
append it for providers without native tool calling. Don't leave it ambiguous.

---

## Reliability

### <a id="r1"></a>R1 — Any exception 500s with no callback · High

The route is a bare `return await runtime.run(request)`. Every failure mode — [C2](#c2), OpenAI
auth/rate-limit/network errors, invalid JSON in tool arguments — becomes an unhandled 500. Because
the callback is the last statement in `run`, it never fires. An n8n flow built around the callback
(the pattern `Spec.md` recommends) simply waits forever.

**Fix:** wrap the run in a try/except that builds an error `AgentRunResponse`, sends the callback
with an explicit error marker, and returns a structured error body. Failures should be *reported*
through the same channel as successes.

### <a id="r2"></a>R2 — Tool discovery is startup-only · Medium

REST discovery runs once in `initialize()`. If `utils-lists` is slow to start — likely, since both
come up together via Compose with no `depends_on` or healthcheck ordering — the agent boots with
zero list tools, reports `status: "ok"`, and stays useless until manually restarted.

**Fix:** retry discovery with backoff in a background task, re-attempt lazily when a run finds no
tools registered, and expose `POST /admin/refresh-tools`. Also add a `depends_on` + `healthcheck`
pair in Compose.

### <a id="r3"></a>R3 — Memory is in-process, unbounded, and the setting is ignored · Medium

`MemoryStore` is a bare dict ([`memory/memory.py`](../src/memory/memory.py)). Consequences:

- History dies on restart or redeploy.
- Two replicas (or `uvicorn --workers 2`) give a conversation two divergent histories.
- No cap: a long-lived `conversationId` grows until every turn's prompt hits the context limit,
  then fails.
- `MEMORY_PROVIDER` is parsed in `Settings` and never read — the config implies a choice that
  doesn't exist.
- `load()` returns the live internal list rather than a copy.

**Fix:** define a `MemoryStore` protocol, add a Postgres or Redis implementation selected by
`MEMORY_PROVIDER`, cap history (last N turns or a token budget with summarisation), and return a
copy from `load()`.

### <a id="r4"></a>R4 — No timeout, retry, or cost cap on OpenAI calls · Medium

`AsyncOpenAI` is constructed with only an API key. No `timeout`, no `max_retries` override, no
budget guard. A hung call holds the request open indefinitely — and since the caller is n8n
waiting synchronously, it holds that workflow too. Five iterations × unbounded context also means
per-request cost is unbounded.

**Fix:** `AsyncOpenAI(api_key=…, timeout=30.0, max_retries=2)`, plus a token-usage counter from
`response.usage` accumulated per run and logged; abort past a configured ceiling.

### <a id="r5"></a>R5 — The result is delivered twice · Medium

`AgentService.run` awaits the callback *and* returns the full response. The spec's design is
callback-only ("the agent never needs to know where the result ultimately goes"); the current
behaviour both doubles delivery and adds callback latency to the synchronous response.

**Fix:** pick one. Either fire the callback via `asyncio.create_task`/`BackgroundTasks` and return
`202 Accepted` with just the `conversationId`, or keep the synchronous response and make the
callback opt-in per request.

### <a id="o1"></a>O1 — Callback has no retry, signature, or dead-letter · Medium

[`callbacks/callback.py`](../src/callbacks/callback.py) catches every exception and logs a warning.
If n8n is restarting, the result is gone — the run reports success, the downstream workflow never
runs, and nothing records the loss. The POST is also unauthenticated, so anything that can reach
the n8n webhook can forge agent results.

**Fix:** retry with exponential backoff; persist failures to a durable outbox; add an HMAC
signature header derived from a shared secret.

### <a id="o5"></a>O5 — Container hardening · Medium

[`Dockerfile`](../Dockerfile) runs uvicorn as root, has no `HEALTHCHECK`, and pins no base image
digest. Compose has no `restart` policy and no resource limits.

**Fix:** add a non-root `USER`, a `HEALTHCHECK` hitting `/health`, and `restart: unless-stopped`.

---

## Observability

### <a id="o2"></a>O2 — Silent degradation to the offline planner · Medium

A missing or typo'd `OPENAI_API_KEY` swaps in `LocalLLMClient` with no warning log and no signal in
`/health`. The service looks healthy, answers requests, and quietly runs a regex matcher — with
[C1](#c1) live. This is the single most likely way to be badly surprised in production.

**Fix:** log at WARNING on fallback, add `"planner": "openai" | "local"` to the health snapshot,
and support a `REQUIRE_LLM=true` mode that refuses to start without a key.

### <a id="o3"></a>O3 — Effectively no observability · Medium

[`observability/trace.py`](../src/observability/trace.py) is a five-line `basicConfig` wrapper.
There is no correlation id in log records, no per-iteration timing, no logging of the plan the LLM
returned, no token counts, no metrics endpoint. `Spec.md` calls for OpenTelemetry or Langfuse;
neither is present. Debugging a bad run today means re-reading `toolLog` and guessing.

**Fix:** bind `conversationId` into a `contextvars` log filter; log one structured line per
iteration (`plan.kind`, tool names, duration, token usage); emit Prometheus counters for runs,
iterations, tool calls and failures.

---

## Code quality and testing

### <a id="q1"></a>Q1 — Tests aren't discoverable and aren't in CI · Medium

The four files under [`tests/`](../tests) use the `*_smoke.py` suffix, which matches neither
pytest default pattern (`test_*.py`, `*_test.py`), so a plain `pytest` run collects **nothing**.
`pytest` isn't in [`requirements.txt`](../requirements.txt) either, and there's no CI config. The
suite also mixes two styles: three files of pytest-style asserts and `callback_smoke.py`, which is
a `__main__` script that boots Docker Compose.

Coverage gaps beyond that: nothing tests `AgentService`'s multi-iteration path, the tool executor's
error handling, REST discovery parsing, or `_chat_safe_memory`.

**Fix:** rename to `test_*.py`, add `pytest` + `pytest-asyncio` to a `requirements-dev.txt`, move
`callback_smoke.py` behind a `-m e2e` marker, and add unit tests for the loop with a fake LLM
client — that's where [C3](#c3), [C4](#c4) and [C5](#c5) all live.

### <a id="q4"></a>Q4 — `OpenAIResponsesClient` doesn't use the Responses API · Low

The class name says Responses API; the implementation calls `chat.completions.create` with the
legacy nested `{"type": "function", "function": {…}}` tool shape. The name will mislead the next
person who touches it.

**Fix:** rename to `OpenAIChatClient`, or migrate to the Responses API — which would also give
server-side conversation state via `previous_response_id`, making the unused `LLMPlan.response_id`
field meaningful and reducing the memory problem in [R3](#r3).

### <a id="q5"></a>Q5 — MCP adapter fails open · Low

`ENABLE_MCP=true` produces no tools and no warning. Worse, `MCPToolAdapter.execute` returns
`{"status": "not_implemented"}` as a **successful** `ToolResult` — a model receiving that has no
way to know the call did nothing.

**Fix:** until it's implemented, raise `NotImplementedError` from `execute` (the executor already
converts that to `ok=False`) and log a warning when `ENABLE_MCP` is set.

### <a id="q6"></a>Q6 — Registry allows silent name collisions · Low

`register()` is `self._tools[tool.name] = tool`. A discovered REST tool named `echo` would
silently replace the local one. Discovery is remote input, so this is a small trust issue as well
as a correctness one.

**Fix:** raise or log on overwrite; consider namespacing discovered tools by source.

### <a id="q7"></a>Q7 — Deprecated startup hook; racy lazy init · Low

`@app.on_event("startup")` is deprecated in FastAPI 0.115 in favour of the `lifespan` context
manager. Separately, `AgentRuntime.run` re-invokes `initialize()` when `agent_service is None` —
under concurrent first requests this can run discovery several times and race on assignment.

**Fix:** move wiring into a `lifespan` handler; guard the lazy path with an `asyncio.Lock` or drop
it and have tests call `initialize()` explicitly.

### <a id="q8"></a>Q8 — New `httpx.AsyncClient` per call · Low

Both [`rest.py`](../src/tools/adapters/rest.py) and [`callback.py`](../src/callbacks/callback.py)
open a client per invocation, discarding connection pooling and paying TLS setup every time.

**Fix:** create one shared `AsyncClient` at startup and close it in the lifespan shutdown.

### <a id="q9"></a>Q9 — `AGENT_HOST` / `AGENT_PORT` have no effect · Low

Both are parsed into `Settings` and never used; the Dockerfile hardcodes
`--host 0.0.0.0 --port 8000`. Setting `AGENT_PORT=9000` changes nothing, which is the worst kind
of config: it looks like it works.

**Fix:** either drive uvicorn from them via a `__main__` entrypoint, or delete them from `Settings`
and the docs.

### <a id="q10"></a>Q10 — Loose typing at the seams · Low

`AgentService.llm_client: Any` and `AgentRuntime.run(self, request)` (no annotations, no return
type) defeat type checking exactly where the plug-in contracts live. `LLMPlan` would benefit from
being a discriminated union rather than a single class with optional fields.

**Fix:** define an `LLMClient` `Protocol` mirroring `ToolProtocol`, annotate `run`, and add mypy or
pyright to the dev requirements.

---

## Suggested sequence

1. **Stop the bleeding** — [C2](#c2), [C3](#c3), [C4](#c4) are three-line fixes with outsized
   impact on multi-step runs. Do them first.
2. **Close the front door** — [S1](#s1), [S2](#s2). Shared-secret auth and a tool allow-list.
3. **Fix the offline planner or retire it** — [C1](#c1). Given that it silently mutates data,
   consider making it explicitly opt-in (`ENABLE_LOCAL_PLANNER=true`) and read-only by default,
   rather than the automatic fallback it is today.
4. **Make failures visible** — [R1](#r1), [C5](#c5), [O2](#o2), [O3](#o3). Errors should reach the
   callback, and `/health` should say which planner is running.
5. **Make it survivable** — [R2](#r2), [R3](#r3), [R4](#r4), [O1](#o1). Discovery retry, persistent
   memory, LLM timeouts, callback retry.
6. **Lock in the fixes** — [Q1](#q1). Rename the tests, get them running in CI with the full tool
   registry, and add loop-level unit tests. The scripted-stub LLM client added for [Q2](#q2) in
   [`tests/debug_trace_smoke.py`](../tests/debug_trace_smoke.py) is the seam for this: it drives
   the loop deterministically, which is exactly what [C3](#c3), [C4](#c4) and [C5](#c5) need.

Items in §1–2 are what stand between this and a service that can be exposed to anything other
than localhost. Everything from §5 onward is what stands between it and one you don't have to
watch.
