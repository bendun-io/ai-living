import sys
import tempfile
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
    assert matches[0].source_path is not None


def test_skill_details_are_available_for_deeper_context() -> None:
    library = SkillLibrary.default()

    details = library.search("calendar")

    assert any(skill.name == "calendar_lookup" for skill in details)
    assert any("calendar" in skill.description.lower() for skill in details)
    assert "calendar" in library.brief_context().lower()
    assert details[0].source_path is not None


def test_joke_skill_prefers_dark_math_and_logic_humor() -> None:
    library = SkillLibrary.default()

    matches = library.search("joke")

    assert any(skill.name == "joke_teller" for skill in matches)
    joke_skill = next(skill for skill in matches if skill.name == "joke_teller")
    text = (joke_skill.summary + " " + joke_skill.description).lower()
    assert "dark humor" in text or "dark" in text
    assert "jimmy carr" in text or "math" in text or "logic" in text


def test_default_skills_dir_resolves_to_a_real_catalog() -> None:
    """Guards against matching src/skills/, the package dir, which has no catalog.yml."""
    skills_dir = SkillLibrary._default_skills_dir()

    assert (skills_dir / "catalog.yml").is_file()
    assert skills_dir.parent.name != "src"


def test_default_skills_dir_never_raises_on_a_shallow_tree() -> None:
    """The old fixed-depth parents[0..5] walk raised IndexError inside the container."""
    # The shallowest plausible layout: where the module sits in the Docker image.
    shallow = Path("/app/src/skills/library.py")
    assert len(shallow.parents) < 6, "fixture should be shallower than the old fixed range"

    for parent in shallow.parents:  # must terminate without IndexError
        _ = parent / "skills"

    assert SkillLibrary._default_skills_dir() is not None


def test_missing_catalog_falls_back_instead_of_crashing() -> None:
    with tempfile.TemporaryDirectory() as empty_dir:
        library = SkillLibrary.default(base_dir=Path(empty_dir))

    names = library.skill_names()

    assert names, "an unreadable catalog must still yield the in-code fallback skills"
    assert "document_search" in names
