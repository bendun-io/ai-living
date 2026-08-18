from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Skill:
    name: str
    summary: str
    description: str
    keywords: list[str] = field(default_factory=list)

    def matches(self, query: str) -> bool:
        query_l = query.lower().strip()
        if not query_l:
            return True
        haystack = " ".join([self.name, self.summary, self.description, " ".join(self.keywords)]).lower()
        return query_l in haystack

    def brief_context(self) -> str:
        return f"- {self.name}: {self.summary}"


@dataclass(slots=True)
class SkillLibrary:
    _skills: list[Skill] = field(default_factory=list)

    @classmethod
    def default(cls) -> "SkillLibrary":
        return cls(
            _skills=[
                Skill(
                    name="document_search",
                    summary="Search project docs for answers.",
                    description=(
                        "Use this skill when the user asks for information that should be found in project docs, "
                        "README files, or internal notes. It searches the documentation library for matching terms "
                        "and returns the relevant passages for a grounded answer."
                    ),
                    keywords=["docs", "documentation", "readme", "knowledge", "search", "project"],
                ),
                Skill(
                    name="calendar_lookup",
                    summary="Check availability and schedule items.",
                    description=(
                        "Use this skill when the user asks about meeting times, schedule availability, or upcoming "
                        "calendar events. It provides a concise summary of relevant calendar items and helps identify "
                        "the best slot for follow-up conversations or appointments."
                    ),
                    keywords=["calendar", "schedule", "availability", "meeting", "events", "time"],
                ),
            ]
        )

    def add(self, skill: Skill) -> None:
        self._skills.append(skill)

    def search(self, query: str) -> list[Skill]:
        if not query:
            return list(self._skills)
        return [skill for skill in self._skills if skill.matches(query)]

    def brief_context(self) -> str:
        if not self._skills:
            return "No skills are available."
        return "Available skills:\n" + "\n".join(skill.brief_context() for skill in self._skills)

    def detailed_context(self, query: str | None = None) -> str:
        matches = self.search(query) if query else list(self._skills)
        if not matches:
            return "No matching skills found."
        lines = ["Skills:"]
        for skill in matches:
            lines.append(f"- {skill.name}: {skill.summary}")
            lines.append(f"  Details: {skill.description}")
            if skill.keywords:
                lines.append(f"  Keywords: {', '.join(skill.keywords)}")
        return "\n".join(lines)
