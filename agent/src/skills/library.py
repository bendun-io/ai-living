from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - optional dependency for file-based loading
    yaml = None


@dataclass(slots=True)
class Skill:
    name: str
    summary: str
    description: str
    keywords: list[str] = field(default_factory=list)
    source_path: str | None = None

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
    def default(cls, base_dir: Path | None = None) -> "SkillLibrary":
        skills_dir = base_dir or cls._default_skills_dir()
        if skills_dir.exists():
            catalog = cls._load_from_disk(skills_dir)
            if catalog:
                return cls(_skills=catalog)
        return cls(_skills=cls._fallback_skills())

    @staticmethod
    def _default_skills_dir() -> Path:
        env_dir = os.getenv("SKILLS_DIR")
        if env_dir:
            candidate = Path(env_dir).expanduser().resolve()
            if candidate.exists():
                return candidate

        here = Path(__file__).resolve()

        # Walk every ancestor rather than a fixed depth: indexing a fixed range raises
        # IndexError when the tree is shallower than expected -- inside the container this
        # module sits at /app/src/skills/library.py with only four parents -- and that
        # crash pre-empted the fallback catalogue this method exists to fall back to.
        #
        # Require catalog.yml rather than mere existence, so the walk identifies a real
        # catalogue and cannot match this package's own src/skills/ directory, which would
        # otherwise shadow the repo-root one because it is nearer.
        for parent in here.parents:
            candidate = parent / "skills"
            if (candidate / "catalog.yml").is_file():
                return candidate

        return here.parents[min(3, len(here.parents) - 1)] / "skills"

    @staticmethod
    def _fallback_skills() -> list[Skill]:
        return [
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

    @staticmethod
    def _load_from_disk(skills_dir: Path) -> list[Skill]:
        if yaml is None:
            return []

        catalog_file = skills_dir / "catalog.yml"
        if not catalog_file.exists():
            return []

        try:
            raw = yaml.safe_load(catalog_file.read_text(encoding="utf-8")) or []
        except (yaml.YAMLError, OSError):
            return []

        entries = raw if isinstance(raw, list) else raw.get("skills", []) if isinstance(raw, dict) else []
        if not isinstance(entries, list):
            return []

        skills: list[Skill] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue

            name = str(entry.get("name", "")).strip()
            if not name:
                continue

            skill_dir = skills_dir / name
            description_file = skill_dir / "Skill.md"
            description = description_file.read_text(encoding="utf-8").strip() if description_file.exists() else str(entry.get("summary", ""))
            skills.append(
                Skill(
                    name=name,
                    summary=str(entry.get("summary", "")).strip(),
                    description=description,
                    keywords=[str(item).strip() for item in entry.get("keywords", []) if str(item).strip()],
                    source_path=str(description_file) if description_file.exists() else None,
                )
            )
        return skills

    def add(self, skill: Skill) -> None:
        self._skills.append(skill)

    def search(self, query: str) -> list[Skill]:
        if not query:
            return list(self._skills)
        return [skill for skill in self._skills if skill.matches(query)]

    def skill_names(self) -> list[str]:
        return [skill.name for skill in self._skills]

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
