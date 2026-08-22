# Agent API

This document describes the HTTP surface of the agent service in `agent/src`.

## Base URL

When running locally through Docker Compose, the service listens on port `8000`.

## `GET /health`

Returns a lightweight status payload that can be used for liveness checks.

### Response

```json
{
  "status": "ok",
  "mcpEnabled": false,
  "utilsListsToolsEnabled": true,
  "utilsListsBaseUrl": "http://utils-lists:8010",
  "utilsListsDiscoveredTools": 13,
  "utilsListsDiscoveryError": null,
  "tools": ["echo"]
}
```

### Fields

- `status`: Always `ok` when the service is reachable.
- `mcpEnabled`: Boolean flag showing whether MCP tool discovery is enabled.
- `utilsListsToolsEnabled`: Boolean flag showing whether external list tooling discovery is enabled.
- `utilsListsBaseUrl`: Base URL used for list tool discovery and execution.
- `utilsListsDiscoveredTools`: Number of discovered list tools currently registered.
- `utilsListsDiscoveryError`: Last discovery error string if discovery failed, otherwise `null`.
- `tools`: List of registered tool names currently loaded by the runtime.

## `POST /agent/run`

Starts a single agent run for one conversation message.

### Request body

```json
{
  "conversationId": "smoke-test-1",
  "user": "tester",
  "message": "echo hello",
  "attachments": [],
  "metadata": {
    "tenant": "local",
    "language": "en",
    "extra": {}
  }
}
```

### Request fields

- `conversationId`: Stable identifier for the conversation or job.
- `user`: Optional user identifier.
- `message`: The input message for the agent.
- `attachments`: Optional attachment list.
- `metadata`: Optional structured context.
  - `tenant`: Optional tenant identifier.
  - `language`: Optional language hint.
  - `extra`: Free-form metadata object.

### Response body

```json
{
  "conversationId": "smoke-test-1",
  "result": "echo hello",
  "toolLog": [],
  "debug": {
    "skillsRead": ["document_search", "calendar_lookup", "joke_teller"],
    "toolsUsed": [
      {
        "tool": "echo",
        "arguments": {
          "message": "echo hello"
        }
      }
    ]
  },
  "metadata": {
    "tenant": "local",
    "language": "en",
    "extra": {}
  }
}
```

### Response fields

- `conversationId`: Echoed conversation identifier.
- `result`: Final answer produced by the agent.
- `toolLog`: Ordered list of tool executions.
- `debug`: Trace details for client-side debugging.
  - `skillsRead`: Ordered list of skill names loaded for this run.
  - `toolsUsed`: Ordered list of tools invoked, each with JSON arguments.
- `metadata`: Echoed metadata object.

## Callback contract

The agent sends the same response envelope to the configured callback URL after a run completes.

### Callback body

```json
{
  "conversationId": "smoke-test-1",
  "result": "echo hello",
  "toolLog": [],
  "debug": {
    "skillsRead": ["document_search", "calendar_lookup", "joke_teller"],
    "toolsUsed": [
      {
        "tool": "echo",
        "arguments": {
          "message": "echo hello"
        }
      }
    ]
  },
  "metadata": {
    "tenant": "local",
    "language": "en",
    "extra": {}
  }
}
```

### Default callback target

The Docker Compose setup points `CALLBACK_URL` to a host-side listener via `host.docker.internal` during local development and testing.

## Environment variables

These are the key variables read by the service:

- `AGENT_HOST`
- `AGENT_PORT`
- `OPENAI_API_KEY`
- `OPENAI_MODEL`
- `CALLBACK_URL`
- `ENABLE_MCP`
- `MCP_SERVERS`
- `MEMORY_PROVIDER`
- `LOG_LEVEL`
- `ENABLE_UTILS_LISTS_TOOLS`
- `UTILS_LISTS_BASE_URL`

Defaults in Docker Compose use service-name routing inside the shared Docker network:

- `UTILS_LISTS_BASE_URL=http://utils-lists:8010`

For host-routed development, override it with:

- `UTILS_LISTS_BASE_URL=http://host.docker.internal:8010`

## External Utils Lists Tooling Endpoints

The agent can call the dedicated utils-lists service for list lifecycle tooling.

Base URL example:

- `http://localhost:8010`

### Discovery

- `GET /agent/tool-definitions`
  - Returns machine-readable tool definitions with `name`, `description`, `endpoint`, and `input_schema`.

### List operations

- `POST /lists/get`
  - Description: fetch one list by id.
- `POST /lists/search`
  - Description: search lists by `name` and `description` with pagination.
- `POST /lists/create`
  - Description: create a new list.
- `POST /lists/update`
  - Description: update list fields.
- `POST /lists/delete`
  - Description: soft-delete a list.

### Item operations

- `POST /items/get`
  - Description: fetch one item by id.
- `POST /items/search`
  - Description: search items by `title`, `notes`, and `status` with pagination.
- `POST /items/create`
  - Description: create an item in a list.
- `POST /items/update`
  - Description: update item fields.
- `POST /items/delete`
  - Description: soft-delete an item.

### Audit and revert

- `POST /audit/get`
  - Description: fetch one audit entry by id.
- `POST /audit/search`
  - Description: filter audit entries by operation and target.
- `POST /audit/revert`
  - Description: revert exactly one mutation by audit id. A source operation can only be reverted once.
