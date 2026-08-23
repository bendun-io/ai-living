from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.skills.library import SkillLibrary


SKILL_SEARCH_TOOL_NAME = "search_skills"


@dataclass(slots=True)
class EchoTool:
    name: str = "echo"
    description: str = "Return the provided arguments for local testing."
    input_schema: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
        }
    )

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {"received": arguments}


@dataclass(slots=True)
class SkillSearchTool:
    library: SkillLibrary
    name: str = SKILL_SEARCH_TOOL_NAME
    description: str = "Search the agent skill library by keyword and return brief summaries or detailed descriptions."
    input_schema: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search keywords for the skill library."},
                "include_details": {
                    "type": "boolean",
                    "description": "If true, return fuller descriptions and keyword tags. Defaults to false.",
                },
            },
            "required": ["query"],
        }
    )

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        query = str(arguments.get("query", "")).strip()
        include_details = bool(arguments.get("include_details", False))
        matches = self.library.search(query)

        if include_details:
            return {
                "matches": [
                    {
                        "name": skill.name,
                        "summary": skill.summary,
                        "description": skill.description,
                        "keywords": skill.keywords,
                    }
                    for skill in matches
                ]
            }

        return {
            "matches": [
                {"name": skill.name, "summary": skill.summary}
                for skill in matches
            ]
        }


def build_local_tools(skill_library: SkillLibrary | None = None) -> list[EchoTool | SkillSearchTool]:
    library = skill_library or SkillLibrary.default()
    return [EchoTool(), SkillSearchTool(library=library)]
