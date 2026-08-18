from src.models import AgentRunRequest, ToolSchema


def build_system_prompt() -> str:
    return (
        "You are an orchestration agent. Use tools when needed. "
        "Return a concise final answer when the task is complete."
    )


def build_user_prompt(request: AgentRunRequest) -> str:
    return request.message.strip()


def build_tool_context(tools: list[ToolSchema]) -> str:
    if not tools:
        return "No tools are available."
    lines = ["Available tools:"]
    for tool in tools:
        lines.append(f"- {tool.name}: {tool.description}")
    return "\n".join(lines)
