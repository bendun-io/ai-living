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
  "tools": ["echo"]
}
```

### Fields

- `status`: Always `ok` when the service is reachable.
- `mcpEnabled`: Boolean flag showing whether MCP tool discovery is enabled.
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
- `metadata`: Echoed metadata object.

## Callback contract

The agent sends the same response envelope to the configured callback URL after a run completes.

### Callback body

```json
{
  "conversationId": "smoke-test-1",
  "result": "echo hello",
  "toolLog": [],
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
