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

**Blocking for anything beyond local use:** [S1](#s1), [C1](#c1). [S2](#s2) is partly addressed
and [C2](#c2) is closed.

---

## Priority summary

| # | Finding | Severity | Effort |
| --- | --- | --- | --- |
| [S1](#s1) | No authentication on `/agent/run`, which can mutate and delete data | Critical | S |
| [S2](#s2) | ⚠️ **Partly fixed** — `audit_revert` withheld; `*_delete` still unguarded | Critical | S |
| [C1](#c1) | Offline planner misroutes item operations to list operations — **verified** | Critical | M |
| [C2](#c2) | ✅ **Fixed** — unknown tool name raised `KeyError` → 500, no callback | High | XS |
| [C6](#c6) | ✅ **Fixed** — startup crashed when the skills catalogue was not found | High | XS |
| [C3](#c3) | ✅ **Fixed** — malformed tool-call arguments corrupted the transcript | High | XS |
| [C4](#c4) | `tool_call.id` dropped; parallel calls to one tool collide | High | XS |
| [C5](#c5) | ✅ **Fixed** — loop exhaustion silently returned the user's own message | High | XS |
| [R1](#r1) | Any run exception 500s with no callback — the caller hangs | High | S |
| [R2](#r2) | Tool discovery is startup-only with no retry | Medium | S |
| [R3](#r3) | Memory is in-process, unbounded, and `MEMORY_PROVIDER` is ignored | Medium | M |
| [R4](#r4) | No timeout, retry, or cost cap on OpenAI calls | Medium | S |
| [R5](#r5) | Result delivered twice (response + callback) | Medium | XS |
| [O1](#o1) | Callback has no retry, no signature, no dead-letter | Medium | M |
| [O2](#o2) | Silent degradation to the offline planner is invisible in `/health` | Medium | XS |
| [O3](#o3) | Almost no observability: no correlation id, no timings, no LLM logging | Medium | S |
| [O4](#o4) | Raw tool arguments leak into callbacks and logs | Medium | S |
| [O5](#o5) | ✅ **Fixed** — container ran as root with no `HEALTHCHECK` | Medium | XS |
| [Q1](#q1) | Tests aren't discoverable by pytest and aren't in CI | Medium | S |
| [Q2](#q2) | ✅ **Fixed** — `debug.skillsRead` reported every skill, not the ones used | Low | XS |
| [Q3](#q3) | `tool_context` is built and thrown away | Low | XS |
| [Q4](#q4) | `OpenAIResponsesClient` doesn't use the Responses API | Low | XS |
| [Q5](#q5) | ✅ **Fixed** — MCP adapter is now a real client, not a stub | Low | S |
| [Q6](#q6) | ✅ **Fixed** — registry allowed *silent* name collisions | Low | XS |
| [Q7](#q7) | ✅ **Fixed** — deprecated `@app.on_event`; racy lazy `initialize()` | Low | XS |
| [Q8](#q8) | ✅ **Fixed** — new `httpx.AsyncClient` per call | Low | XS |
| [Q9](#q9) | ✅ **Fixed** — `AGENT_HOST` / `AGENT_PORT` were read but had no effect; now removed | Low | XS |
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

### <a id="s2"></a>S2 — Destructive tools exposed with no guard · Critical · ⚠️ Partly fixed

**Was:** all 13 discovered tools were registered with equal standing, including `lists_delete`,
`items_delete` and `audit_revert`. A model hallucination, a prompt injection in a list name that
comes back through `lists_search`, or a misrouted intent ([C1](#c1)) all led straight to a
mutation with no confirmation step.

The injection path is real and still is: tool output is fed back into `messages` as content the
model reads, and list/item names are user-controlled.

**Now:** the irreversible one is gone. `audit_revert` is withheld at the source, so the service
that owns the capability decides who may see it rather than the agent filtering after the fact:

```python
# utils/lists-service/app/core.py
AGENT_EXCLUDED_TOOLS = {"audit_revert"}
AGENT_TOOL_DEFINITIONS = [t for t in TOOL_DEFINITIONS if t["name"] not in AGENT_EXCLUDED_TOOLS]
```

`GET /agent/tool-definitions` now serves `AGENT_TOOL_DEFINITIONS` — 12 tools instead of 13 — so the
agent cannot discover, register, or call revert. The lists service's `GET /health` reports the
agent-visible names plus an explicit `agentExcludedTools` array, so the exclusion is auditable
rather than an unexplained gap in a list.

Reverting stays a human action over two still-live routes: `POST /audit/{id}/revert` (used by the
web UI) and `POST /audit/revert` (the agent-shaped endpoint, exercised by
`brunoCollection/utils-lists/Audit - Revert.bru` — left in place so that collection keeps working).

**Read this before calling it done:** neither revert route is authenticated. Withholding the tool
stops the agent *choosing* revert; it does not stop anything that can reach the port from calling
it. That is [S1](#s1)'s job and [S1](#s1) is still open.

**Still open:**
1. `lists_delete` and `items_delete` remain freely callable by the agent. They are soft-deletes and
   themselves revertible, which is why they rank below revert — but they are unguarded.
2. No agent-side allow-list (`AGENT_ALLOWED_TOOLS`). This exclusion works only because the single
   tool source cooperates; a second REST provider could still hand the agent anything.
3. No `"destructive": true` marker in the discovery contract, and no confirmation-token flow.

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

### <a id="c2"></a>C2 — Unknown tool name raised `KeyError` → 500 · High · ✅ Fixed

**Was:** the registry lookup sat outside the `try` block, so a hallucinated or renamed tool name
raised `KeyError`, escaped `AgentService.run`, escaped the route, and returned a 500 — killing the
run and skipping the callback.

**Now:** [`ToolExecutor.execute`](../src/tools/executor.py) uses a new non-raising
`ToolRegistry.find()` and turns absence into an ordinary failed result:

```python
tool = self.registry.find(invocation.name)
if tool is None:
    result = self._unknown_tool_result(invocation.name)
```

`_unknown_tool_result` logs a warning and returns
`ToolResult(ok=False, error="Unknown tool 'x'. Available tools: a, b, c.")`.

Listing the real names in the error is the substance of the fix, not decoration: that string goes
back into `messages` as tool output, so the planner sees what it *could* have called and can retry
on the next iteration. A bad tool name is now a recoverable step rather than a lost run, and the
callback still fires.

`ToolRegistry.get()` still raises, for callers that want a strict lookup; `find()` is the tolerant
path. Covered by `test_unknown_tool_becomes_a_failed_result_not_an_exception` and
`test_find_returns_none_instead_of_raising` in
[`tests/tool_registry_smoke.py`](../tests/tool_registry_smoke.py).

This narrows [R1](#r1) but does not close it — OpenAI errors and malformed tool-call JSON still
produce bare 500s with no callback.

### <a id="c3"></a>C3 — Malformed tool-call arguments corrupted the transcript · High · ✅ Fixed

**Was:** [`agent/executor.py:103`](../src/agent/executor.py) built the synthetic assistant message
with:

```python
"arguments": invocation.model_dump_json(exclude={"call_id"})
```

That serialises the **whole invocation**, not its arguments. Verified output:

```json
{"name":"lists_search","arguments":{"query":"x"}}
```

where OpenAI expects `{"query":"x"}`. So from iteration 2 onward the model saw its own past calls
double-wrapped. Symptoms were subtle rather than fatal — degraded multi-step reasoning, repeated
tool calls, occasional argument mimicry of the wrong shape — which made it easy to misdiagnose as
"the model is bad at this".

**Now:** [`_build_assistant_tool_message`](../src/agent/executor.py) serialises just the arguments:
`"arguments": json.dumps(invocation.arguments)`. Covered by
`test_synthetic_tool_call_arguments_are_not_double_wrapped` in
[`tests/debug_trace_smoke.py`](../tests/debug_trace_smoke.py), which scripts a two-iteration run and
asserts the assistant message the model sees on iteration 2 carries the tool's raw arguments rather
than a `{"name", "arguments"}` envelope.

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

### <a id="c6"></a>C6 — Startup crashed when the skills catalogue was not found · High · ✅ Fixed

Found while verifying [O5](#o5): the container built fine and then exited 3 on boot.

`SkillLibrary._default_skills_dir` walked ancestors with a hardcoded range:

```python
for parent in [Path(__file__).resolve().parents[i] for i in range(0, 6)]:
```

In the image the module sits at `/app/src/skills/library.py`, which has **four** parents, so
`parents[4]` raised `IndexError` — during `initialize()`, inside the FastAPI startup event, so
uvicorn aborted with `Application startup failed`. The `_fallback_skills()` catalogue that exists
precisely for "no catalogue found" was unreachable, because the search for it crashed first.

Compose hid this by setting `SKILLS_DIR=/app/skills` and bind-mounting `../skills`, which returns
from the first branch. Any run without that mount — `docker run` with no `-v`, a dev with a
different cwd, a deploy where the mount is missing — hit the crash instead of the fallback.

**Now:** [`library.py`](../src/skills/library.py) walks `here.parents` directly, which is bounded by
the real tree depth, and tests for `catalog.yml` rather than mere existence:

```python
for parent in here.parents:
    candidate = parent / "skills"
    if (candidate / "catalog.yml").is_file():
        return candidate
```

The `catalog.yml` test is load-bearing. My first attempt checked `candidate.exists()`, which
matched `agent/src/skills` — this package's own directory — because walking nearest-first reaches
it before the repo-root catalogue. That silently downgraded every run to the two-skill fallback and
was caught by the existing suite. Requiring the catalogue file identifies a real skills directory
and cannot match the package.

Verified by building and running the image with no mount: it now reaches `healthy` and serves
`tools: ["echo", "search_skills"]`. Regression tests in
[`tests/skill_library_smoke.py`](../tests/skill_library_smoke.py) cover the shallow-tree walk, that
the resolved directory contains `catalog.yml` and is not the package dir, and that a missing
catalogue yields the fallback skills instead of raising.

### <a id="c5"></a>C5 — Loop exhaustion silently returned the user's message · High · ✅ Fixed

**Was:** `result_text` was initialised to `request.message` and only overwritten by a `final` plan.
If the planner still wanted tools after `max_iterations`, the `for` loop ended normally and the
agent returned the caller's own input as the answer — HTTP 200, no error field, callback fired as
if it succeeded.

**Now:** [`AgentService.run`](../src/agent/executor.py) tracks a `reached_final_answer` flag,
set only when the loop breaks on `plan.kind == "final"`. After the loop, if that flag is still
`False`, `result_text` is overwritten with a fixed message:

```python
LOOP_EXHAUSTED_MESSAGE = (
    "The agent's reasoning loop has been exhausted after {max_iterations} step(s) "
    "without reaching a final answer. No solution was found."
)
```

So a run that never converges now reports an explicit, recognisable failure string instead of
echoing the caller's own input back at them. It is still delivered as a normal `200` response
through both the HTTP body and the callback — this fix makes exhaustion *legible*, not
machine-detectable by a status code. A caller that wants to branch on it must still match against
the fixed message text (or check `toolLog` non-empty combined with the result not matching any
sensible answer), which the API doc now calls out explicitly.

**Still open:** no machine-readable flag on `AgentRunResponse` (e.g. `finishReason:
"loop_exhausted"`), no last-ditch `tool_choice="none"` call to force a real summary of what was
tried, and `max_iterations` is still a hardcoded field default rather than driven by `Settings`.

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

### <a id="o5"></a>O5 — Container hardening · Medium · ✅ Fixed (the two that mattered)

**Was:** [`Dockerfile`](../Dockerfile) ran uvicorn as root and had no `HEALTHCHECK`.

**Now:** both are in place.

```dockerfile
RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin agent \
    && chown -R agent:agent /app
USER agent

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=3)"
```

The uid is pinned at 10001 so bind-mounted files keep a predictable owner across rebuilds. The
probe uses `urllib` rather than `curl` because the slim base has no curl, and `urlopen` raises on a
non-2xx status — so a process that is up but answering with an error is reported unhealthy rather
than passing on "it responded". `start-period=20s` covers startup tool discovery, which can spend
up to 30s timing out against an absent `utils-lists`.

Verified end to end by building the image and running it three ways: without a skills mount, with
`../skills` mounted read-only as Compose does, and while exercising `/agent/run`. In every case
`docker exec … id` reports `uid=10001(agent) gid=10001(agent)` and the container reaches `healthy`;
the non-root user reads the read-only mount without trouble. That exercise is what surfaced
[C6](#c6).

**Still open:** no pinned base-image digest, no `restart: unless-stopped` in
[`docker-compose.yml`](../docker-compose.yml), no resource limits. Note also that this is a
liveness probe, not readiness — `/health` returns `status: "ok"` even when tool discovery failed
([R2](#r2)), so a container can be `healthy` with no tools registered.

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

### <a id="q5"></a>Q5 — MCP adapter is a real client, not a stub · Low · ✅ Fixed

**Was:** `ENABLE_MCP=true` produced no tools and no warning. `MCPToolAdapter.execute` returned
`{"status": "not_implemented"}` as a **successful** `ToolResult` — a model receiving that had no
way to know the call did nothing.

**Now:** [`adapters/mcp.py`](../src/tools/adapters/mcp.py) talks to real MCP servers over the
official `mcp` SDK (`streamable_http` or `sse` transport), reading `MCP_SERVERS_FILE` (default
[`config/mcp-servers.json`](../config/mcp-servers.json)) via `load_mcp_server_configs` /
`parse_mcp_server_configs`. Per-server config supports `url`, `prefix` (auto-derived from the
server name if omitted, to avoid two servers' same-named tools colliding — see
`default_prefix`), `transport`, `token`/`tokenEnv`, `headers` (with `${VAR}` expansion so secrets
stay out of the committed file), and `timeoutSeconds`.

`AgentRuntime.initialize()` loads the config, calls `refresh_mcp_tools()` once at startup, and — if
`MCP_REFRESH_INTERVAL_SECONDS > 0` — starts a background task that rediscovers on that interval.
Each server is refreshed independently: a server that errors keeps the tools it registered last
time (`mcp_tool_names` tracks what to unregister on the *next* successful refresh) rather than
losing them on a transient blip. `MCPToolAdapter.call_tool` re-raises a tool-level MCP error as
`RuntimeError`, which `ToolExecutor` turns into an ordinary failed `ToolResult` — the
"successful no-op" failure mode above no longer exists.

Config errors, per-server tool counts, and last success/attempt timestamps are all surfaced in
`/health` (`mcpConfigError`, `mcpServers[]`), closing the "no warning" half of the original finding
too. Covered by [`tests/mcp_adapter_smoke.py`](../tests/mcp_adapter_smoke.py): config parsing,
prefix derivation, the refresh swap, and the keep-previous-tools-on-failure rule, all against a
fake adapter so the suite needs no live MCP server.

**Still open:** a session is opened fresh per `list_tools`/`call_tool` call rather than held open
(see [`adapters/mcp.py`](../src/tools/adapters/mcp.py) — a deliberate tradeoff for restart
resilience, but it costs a round trip of session setup per call); no per-server circuit breaker, so
a server that is merely slow (rather than down) still pays its full `timeoutSeconds` on every
call.

### <a id="q6"></a>Q6 — Registry allowed *silent* name collisions · Low · ✅ Fixed

**Was:** `register()` was a bare `self._tools[tool.name] = tool`. A discovered REST tool named
`echo` would replace the local one with no trace anywhere.

**Now:** [`ToolRegistry.register`](../src/tools/registry.py) detects the clash, records it, and logs
a warning:

```
Tool name collision: 'echo' registered by ShadowTool replaces the existing EchoTool
```

Each collision is stored as `{"name", "replaced", "replacedBy"}` — the tool name plus both class
names, which is what tells you *which* source won. `collisions()` returns a copy, and
`AgentRuntime.health_snapshot()` exposes the list as `toolNameCollisions` in `GET /health`, so a
clash is visible without reading container logs.

Last-write-wins is deliberately unchanged. Rejecting the second registration would make the winner
depend on discovery order just as silently as before, and failing startup outright would turn a
remote service's naming choice into an agent outage. The fix is to make it loud and let the health
endpoint drive the decision.

**Still open:** namespacing discovered tools by source (`utils_lists.echo`) would prevent collisions
rather than report them — worth doing once there is a second REST provider.

Covered by four cases in [`tests/tool_registry_smoke.py`](../tests/tool_registry_smoke.py),
including that `collisions()` returns a copy rather than the live list.

### <a id="q7"></a>Q7 — Deprecated startup hook; racy lazy init · Low · ✅ Fixed

**Was:** `@app.on_event("startup")` is deprecated in FastAPI 0.115 in favour of the `lifespan`
context manager. Separately, `AgentRuntime.run` re-invoked `initialize()` when `agent_service is
None` — under concurrent first requests this could run discovery several times and race on
assignment.

**Now:** [`app.py`](../src/app.py) wires `runtime.initialize()` / `runtime.shutdown()` through an
`@asynccontextmanager lifespan(app)` handler passed to `FastAPI(..., lifespan=lifespan)`, replacing
both `on_event` hooks. [`AgentRuntime.run`](../src/agent/agent.py) now guards the lazy path with an
`asyncio.Lock` (`_init_lock`), re-checking `agent_service is None` inside the lock so concurrent
first requests await one `initialize()` call instead of racing.

### <a id="q8"></a>Q8 — New `httpx.AsyncClient` per call · Low · ✅ Fixed

**Was:** both [`rest.py`](../src/tools/adapters/rest.py) and
[`callback.py`](../src/callbacks/callback.py) opened a client per invocation, discarding connection
pooling and paying TLS setup every time.

**Now:** [`AgentRuntime`](../src/agent/agent.py) owns one shared `httpx.AsyncClient` (30 s timeout),
created in `initialize()` and closed in `shutdown()`. It is threaded through
`fetch_rest_tool_definitions()` into every discovered `RestTool`, and into `CallbackClient`, so
`execute()` and `send()` reuse the pooled connection instead of opening a fresh one.

### <a id="q9"></a>Q9 — `AGENT_HOST` / `AGENT_PORT` had no effect · Low · ✅ Fixed

**Was:** both were parsed into `Settings` and never used; the Dockerfile hardcoded
`--host 0.0.0.0 --port 8000`. Setting `AGENT_PORT=9000` changed nothing, which is the worst kind
of config: it looked like it worked.

**Now:** taking the "delete" branch of the original fix — [`config.py`](../src/config.py) no
longer has `agent_host` / `agent_port` fields or `AGENT_HOST` / `AGENT_PORT` parsing, and the
variables are gone from [`docker-compose.yml`](../docker-compose.yml) and [`.env`](../.env). The
Dockerfile's hardcoded `--host 0.0.0.0 --port 8000` is now the only place the bind address lives,
so there is no config that silently does nothing. If the port ever needs to be configurable, that
means wiring a real `__main__` entrypoint that reads `Settings` and passes it to uvicorn — not
resurrecting the unused fields.

### <a id="q10"></a>Q10 — Loose typing at the seams · Low

`AgentService.llm_client: Any` and `AgentRuntime.run(self, request)` (no annotations, no return
type) defeat type checking exactly where the plug-in contracts live. `LLMPlan` would benefit from
being a discriminated union rather than a single class with optional fields.

**Fix:** define an `LLMClient` `Protocol` mirroring `ToolProtocol`, annotate `run`, and add mypy or
pyright to the dev requirements.

---

## Suggested sequence

1. **Stop the bleeding** — ~~[C2](#c2)~~, ~~[C3](#c3)~~ and ~~[C6](#c6)~~ done. [C4](#c4) is still
   a three-line fix with outsized impact on multi-step runs; do it next.
2. **Close the front door** — [S1](#s1) is now the binding constraint. `audit_revert` is out of the
   agent's reach ([S2](#s2)), but `/agent/run` and both revert routes are still unauthenticated.
   Shared-secret auth, then an allow-list for the remaining `*_delete` tools.
3. **Fix the offline planner or retire it** — [C1](#c1). Given that it silently mutates data,
   consider making it explicitly opt-in (`ENABLE_LOCAL_PLANNER=true`) and read-only by default,
   rather than the automatic fallback it is today.
4. **Make failures visible** — [R1](#r1), ~~[C5](#c5)~~ done, [O2](#o2), [O3](#o3). Errors should
   reach the callback, and `/health` should say which planner is running. [C5](#c5)'s fix is a
   fixed string, not a status code — a machine-readable `finishReason` is still worth adding.
5. **Make it survivable** — [R2](#r2), [R3](#r3), [R4](#r4), [O1](#o1). Discovery retry, persistent
   memory, LLM timeouts, callback retry.
6. **Lock in the fixes** — [Q1](#q1). Rename the tests, get them running in CI with the full tool
   registry, and add loop-level unit tests. The scripted-stub LLM client added for [Q2](#q2) in
   [`tests/debug_trace_smoke.py`](../tests/debug_trace_smoke.py) is the seam for this: it drives
   the loop deterministically, which is what the [C3](#c3) and [C5](#c5) regression tests already
   use, and what [C4](#c4) still needs.

Items in §1–2 are what stand between this and a service that can be exposed to anything other
than localhost. Everything from §5 onward is what stands between it and one you don't have to
watch.
