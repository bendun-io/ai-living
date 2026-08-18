from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class AgentMetadata(BaseModel):
    tenant: str | None = None
    language: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class AgentRunRequest(BaseModel):
    conversationId: str
    user: str | None = None
    message: str
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    metadata: AgentMetadata = Field(default_factory=AgentMetadata)


class ToolSchema(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any] = Field(default_factory=dict)


class ToolInvocation(BaseModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    call_id: str | None = None


class ToolResult(BaseModel):
    name: str
    ok: bool
    output: Any = None
    error: str | None = None


class ToolExecutionRecord(BaseModel):
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    result: ToolResult


class LLMPlan(BaseModel):
    kind: Literal["final", "tool_calls"]
    final_answer: str | None = None
    tool_calls: list[ToolInvocation] = Field(default_factory=list)
    response_id: str | None = None


class AgentRunResponse(BaseModel):
    conversationId: str
    result: str
    toolLog: list[ToolExecutionRecord] = Field(default_factory=list)
    metadata: AgentMetadata = Field(default_factory=AgentMetadata)


class CallbackPayload(BaseModel):
    conversationId: str
    result: str
    toolLog: list[ToolExecutionRecord] = Field(default_factory=list)
    metadata: AgentMetadata = Field(default_factory=AgentMetadata)
