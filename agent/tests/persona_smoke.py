import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.agent.prompts import _FALLBACK_PERSONA, _default_persona_file, build_system_prompt, load_persona


def test_default_persona_file_resolves_to_the_repo_persona() -> None:
    persona_file = _default_persona_file()

    assert persona_file.is_file()
    assert persona_file.name == "persona.md"


def test_persona_is_loaded_into_the_system_prompt() -> None:
    prompt = build_system_prompt()

    assert "Jarvis" in prompt


def test_missing_persona_file_falls_back_instead_of_crashing() -> None:
    with tempfile.TemporaryDirectory() as empty_dir:
        text = load_persona(Path(empty_dir) / "does-not-exist.md")

    assert text == _FALLBACK_PERSONA


def test_empty_persona_file_falls_back_instead_of_returning_blank() -> None:
    with tempfile.TemporaryDirectory() as empty_dir:
        blank_file = Path(empty_dir) / "persona.md"
        blank_file.write_text("   \n", encoding="utf-8")

        text = load_persona(blank_file)

    assert text == _FALLBACK_PERSONA
