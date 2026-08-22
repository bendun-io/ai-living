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

## Health

- `GET /health`

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
- `POST /audit/revert`

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
