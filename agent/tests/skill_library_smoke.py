import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.skills.library import SkillLibrary


def test_skill_search_returns_matches_and_summary_is_brief() -> None:
    library = SkillLibrary.default()

    matches = library.search("document")

    assert any(skill.name == "document_search" for skill in matches)
    assert matches[0].summary
    assert len(matches[0].summary.split()) <= 12


def test_skill_details_are_available_for_deeper_context() -> None:
    library = SkillLibrary.default()

    details = library.search("calendar")

    assert any(skill.name == "calendar_lookup" for skill in details)
    assert any("calendar" in skill.description.lower() for skill in details)
    assert "calendar" in library.brief_context().lower()
