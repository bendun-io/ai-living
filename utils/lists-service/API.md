# Utils Lists API

Base URL: http://localhost:8010

This service exposes tool-style action endpoints for list and list-item lifecycle management, with audit logging and single-operation revert.

## Agent Tool Definitions

- GET /agent/tool-definitions
- Returns machine-readable tool metadata for agent integration.

## Health

- GET /health
- Returns service status and available tool names.

## Lists

- POST /lists/get
- Description: Get one list by id.
- Input: id, include_deleted

- POST /lists/search
- Description: Search lists by name or description.
- Input: query, include_deleted, limit, offset

- POST /lists/create
- Description: Create a list.
- Input: name, description, actor

- POST /lists/update
- Description: Update list attributes.
- Input: id, name, description, actor

- POST /lists/delete
- Description: Soft-delete a list.
- Input: id, actor

## Items

- POST /items/get
- Description: Get one item by id.
- Input: id, include_deleted

- POST /items/search
- Description: Search items by title, notes, or status.
- Input: query, include_deleted, limit, offset

- POST /items/create
- Description: Create a list item.
- Input: list_id, title, notes, status, actor

- POST /items/update
- Description: Update item attributes.
- Input: id, title, notes, status, actor

- POST /items/delete
- Description: Soft-delete an item.
- Input: id, actor

## Audit

- POST /audit/get
- Description: Get one audit row by id.
- Input: id

- POST /audit/search
- Description: Search audit rows with optional filters.
- Input: target_type, target_id, operation, limit, offset

- POST /audit/revert
- Description: Revert exactly one supported mutation operation by audit id.
- Input: audit_id, actor

## Revert Rules

- Supported original operations: lists.create, lists.update, lists.delete, items.create, items.update, items.delete.
- A source audit entry can only be reverted once.
- Revert writes a new audit row with operation audit.revert and links to the original entry.
