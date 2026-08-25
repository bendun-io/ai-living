import os
from pathlib import Path

from src.models import AgentRunRequest, ToolSchema
from src.skills.library import SkillLibrary


_FALLBACK_PERSONA = (
    "You are an orchestration agent. Use tools when needed. "
    "Return a concise final answer when the task is complete."
)


def _default_persona_file() -> Path:
    env_file = os.getenv("PERSONA_FILE")
    if env_file:
        candidate = Path(env_file).expanduser().resolve()
        if candidate.is_file():
            return candidate

    # Same walk-to-nearest-ancestor approach as SkillLibrary._default_skills_dir: no fixed
    # parents[] depth, so it can't IndexError in a shallower container layout, and it checks
    # for the file itself rather than a directory name that this package could also have.
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "config" / "persona.md"
        if candidate.is_file():
            return candidate

    return here.parents[min(3, len(here.parents) - 1)] / "config" / "persona.md"


def load_persona(persona_file: Path | None = None) -> str:
    path = persona_file or _default_persona_file()
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return _FALLBACK_PERSONA
    return text or _FALLBACK_PERSONA


def build_system_prompt(skill_library: SkillLibrary | None = None) -> str:
    base = load_persona()
    if skill_library is None:
        return base
    return f"{base}\n\n{skill_library.brief_context()}"


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
