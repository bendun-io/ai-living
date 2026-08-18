from src.models import AgentRunRequest, ToolSchema
from src.skills.library import SkillLibrary


def build_system_prompt(skill_library: SkillLibrary | None = None) -> str:
    base = (
        "You are an orchestration agent. Use tools when needed. "
        "Return a concise final answer when the task is complete."
    )
    if skill_library is None:
        return base
    return f"{base} {skill_library.brief_context()}"


def build_user_prompt(request: AgentRunRequest) -> str:
    return request.message.strip()


def build_tool_context(tools: list[ToolSchema], skill_library: SkillLibrary | None = None) -> str:
    lines = ["Available tools:"]
    for tool in tools:
        lines.append(f"- {tool.name}: {tool.description}")

    if skill_library is not None:
        lines.append("")
        lines.append(skill_library.brief_context())

    return "\n".join(lines) if lines else "No tools are available."
