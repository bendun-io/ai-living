# Utils Lists API

Base URL: `http://localhost:8010`

This service now exposes:
- Agent-style action endpoints (for tool consumers)
- REST-style endpoints over the same list/item/audit objects
- A web frontend served by the same FastAPI service

## Frontend

- `GET /`
- Navigation contains **Lists** and **Audit Log**.
- Lists view supports create/delete/details, item filtering, item create/update/delete.
- Audit view shows operations and supports revert.

Static assets are served from `/static/*`.

## Agent Tool Definitions

- `GET /agent/tool-definitions`
  - Returns the tool catalogue advertised to agents: `name`, `description`, `endpoint`, `method`
    and `input_schema` per tool.
  - Serves `AGENT_TOOL_DEFINITIONS`, which is `TOOL_DEFINITIONS` minus `AGENT_EXCLUDED_TOOLS`.
    12 of the 13 defined tools are advertised.

### Tools withheld from agents

`AGENT_EXCLUDED_TOOLS` in `app/core.py` names tools that exist as HTTP endpoints but are never
advertised to an agent. An agent discovers tools only through the endpoint above, so anything
listed here can never be registered or called by a planner.

| Tool | Why |
| --- | --- |
| `audit_revert` | Reverting a mutation is irreversible, so it stays a human decision. Both revert endpoints remain callable for the web UI and operators. |

To withhold another tool, add its name to `AGENT_EXCLUDED_TOOLS`. No agent-side change is needed —
the agent rediscovers the catalogue on its next startup.

Note that withholding controls *discovery*, not access: the endpoints remain unauthenticated and
reachable by anything that can reach the port.

## Health

- `GET /health`

```json
{
  "status": "ok",
  "service": "utils-lists",
  "tools": ["lists_get", "lists_search", "..."],
  "agentExcludedTools": ["audit_revert"]
}
```

- `tools`: names an agent can discover and call (the advertised catalogue).
- `agentExcludedTools`: names deliberately withheld, so the gap is auditable rather than implicit.

## Agent-style Endpoints (existing)

### Lists
- `POST /lists/get`
- `POST /lists/search`
- `POST /lists/create`
- `POST /lists/update`
- `POST /lists/delete`

### Items
- `POST /items/get`
- `POST /items/search`
- `POST /items/create`
- `POST /items/update`
- `POST /items/delete`

### Audit
- `POST /audit/get`
- `POST /audit/search`
- `POST /audit/revert` — live, but **not advertised to agents** (see `AGENT_EXCLUDED_TOOLS` above)

## REST-style Endpoints (new)

### Lists
- `GET /lists?query=&include_deleted=&limit=&offset=`
- `POST /lists`
- `GET /lists/{list_id}`
- `PATCH /lists/{list_id}`
- `DELETE /lists/{list_id}?actor=`

### Items
- `GET /lists/{list_id}/items?query=&include_deleted=&limit=&offset=`
- `POST /lists/{list_id}/items`
- `GET /items/{item_id}`
- `PATCH /items/{item_id}`
- `DELETE /items/{item_id}?actor=`

### Audit
- `GET /audit?target_type=&target_id=&operation=&limit=&offset=`
- `GET /audit/{audit_id}`
- `POST /audit/{audit_id}/revert`

## Revert Rules

- Supported original operations: `lists.create`, `lists.update`, `lists.delete`, `items.create`, `items.update`, `items.delete`.
- A source audit entry can only be reverted once.
- Revert writes a new audit row with operation `audit.revert` and links to the original entry.
