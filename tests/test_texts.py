"""Checks of app/texts.toml and of ui_text.t(), the lookup that reads it.

The file is edited by people who don't program, so each failure message says
what is wrong in the file and how to fix it.
"""

import ast
import re
import subprocess
import sys
import tomllib
import types
from pathlib import Path

import pytest

import ui_text

REPO = Path(__file__).resolve().parents[1]
TEXTS_FILE = REPO / "app" / "texts.toml"
SECTIONS = {
    "app", "startup", "nav", "header", "overview", "lookup", "ifk", "ifk_area", "expert",
    "raster", "job", "overlay", "derivate", "legend", "server", "anriss", "gs", "area", "upload",
    "variable", "unit", "map", "footer", "download_gate",
}  # fmt: skip
# <section>.<name>, or <section>.<name>.<code key> for a text per value of a code dict.
KEY = re.compile(r"[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*(\.[a-z0-9_]+)?")
FIELDS = {"de", "fr", "note"}
FIX_PLACEHOLDERS = "Keep the placeholders exactly as in German."


def _entries(table: dict, prefix: str = "") -> list[tuple[str, dict]]:
    """Every entry with its dotted key. A table that holds a text is an entry."""
    if not table or any(not isinstance(value, dict) for value in table.values()):
        return [(prefix, table)]
    found = []
    for name, value in table.items():
        found += _entries(value, f"{prefix}.{name}" if prefix else name)
    return found


def _read_file() -> dict:
    # A file that isn't valid TOML already stopped `import ui_text` above, with the line.
    with TEXTS_FILE.open("rb") as file:
        return tomllib.load(file)


def _placeholders(text: str) -> set[str]:
    return set(ui_text.PLACEHOLDER.findall(text))


def _shown(names: set[str]) -> str:
    return ", ".join(f"{{{name}}}" for name in sorted(names)) or "no placeholder"


def _fail_on(problems: list[str]) -> None:
    if problems:
        pytest.fail("\n".join(problems), pytrace=False)


ENTRIES = _entries(_read_file())


def test_the_file_reads_and_has_texts():
    assert len(ENTRIES) > 100


def _entry_problems(key: str, entry: dict) -> list[str]:
    problems = []
    if extra := set(entry) - FIELDS:
        names = ", ".join(sorted(extra))
        problems.append(f'"{key}" has {names}; an entry has only de, fr and note.')
    if missing := {"de", "fr"} - set(entry):
        names = " and ".join(sorted(missing))
        problems.append(f'"{key}" has no {names} line. Add it, e.g. fr = "".')
    if any(isinstance(value, dict) for value in entry.values()):
        problems.append(f'"{key}" contains another entry. Give each text its own key.')
    for field in FIELDS & set(entry):
        if not isinstance(entry[field], str):
            problems.append(f'{field} of "{key}" is not a text in quotes.')
    if not entry.get("de"):
        problems.append(f'de of "{key}" is empty. Every text needs its German.')
    return problems


def test_every_entry_has_german_french_and_at_most_a_note():
    _fail_on([problem for key, entry in ENTRIES for problem in _entry_problems(key, entry)])


def test_keys_follow_the_naming_scheme():
    problems = [
        f'"{key}" is not a valid key: use section.name in lower case, letters, digits and _, '
        f"with a section from {sorted(SECTIONS)}."
        for key, _ in ENTRIES
        if not KEY.fullmatch(key) or key.split(".")[0] not in SECTIONS
    ]
    _fail_on(problems)


def test_french_uses_the_german_placeholders():
    problems = []
    for key, entry in ENTRIES:
        german, french = _placeholders(entry["de"]), _placeholders(entry.get("fr", ""))
        if entry.get("fr") and german != french:
            problems.append(
                f'`fr` of "{key}" uses {_shown(french)}, but the German uses {_shown(german)}. '
                f"{FIX_PLACEHOLDERS}"
            )
    _fail_on(problems)


# ── Keys used by the code ────────────────────────────────────────────────────


# The lookups that take a key: t(), and template() for the map texts (map_labels.py).
LOOKUPS = {"t", "template"}


def _is_t_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name):
        return func.id in LOOKUPS
    return (
        isinstance(func, ast.Attribute)
        and func.attr in LOOKUPS
        and isinstance(func.value, ast.Name)
        and func.value.id == "ui_text"
    )


def _prefix(arg: ast.AST) -> str | None:
    """'gs.reach.' for f"gs.reach.{reach}"; None for any other f-string."""
    if not isinstance(arg, ast.JoinedStr) or len(arg.values) != 2:
        return None
    head, tail = arg.values
    if isinstance(head, ast.Constant) and isinstance(tail, ast.FormattedValue):
        if head.value.endswith("."):
            return head.value
    return None


def _code_keys() -> tuple[set[tuple[str, str]], set[tuple[str, str]], list[str]]:
    """The keys passed to t() in app/: literal keys, f-string prefixes, and other forms."""
    keys, prefixes, other = set(), set(), []
    for path in sorted((REPO / "app").rglob("*.py")):
        where = path.relative_to(REPO)
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not _is_t_call(node):
                continue
            arg = node.args[0] if node.args else None
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                keys.add((arg.value, f"{where}:{node.lineno}"))
            elif prefix := _prefix(arg):
                prefixes.add((prefix, f"{where}:{node.lineno}"))
            else:
                other.append(f"{where}:{node.lineno}")
    return keys, prefixes, other


CODE_KEYS, CODE_PREFIXES, OTHER_CALLS = _code_keys()
FILE_KEYS = {key for key, _ in ENTRIES}


def test_code_calls_t_with_a_written_out_key():
    assert CODE_KEYS
    problems = [
        f'{where}: t() needs its key written out, e.g. t("ifk.no_data"), or '
        f't(f"gs.reach.{{reach}}") for a text per code value.'
        for where in OTHER_CALLS
    ]
    _fail_on(problems)


def test_every_key_the_code_uses_is_in_the_file():
    problems = [
        f'{where} uses "{key}", which is not in app/texts.toml. Add the entry, or fix the key.'
        for key, where in sorted(CODE_KEYS)
        if key not in FILE_KEYS
    ]
    problems += [
        f'{where} uses keys starting with "{prefix}", but app/texts.toml has none.'
        for prefix, where in sorted(CODE_PREFIXES)
        if not any(key.startswith(prefix) for key in FILE_KEYS)
    ]
    _fail_on(problems)


def test_every_key_in_the_file_is_used():
    used = {key for key, _ in CODE_KEYS}
    prefixes = tuple(prefix for prefix, _ in CODE_PREFIXES)
    problems = [
        f'"{key}" is in app/texts.toml but the app never shows it. Remove it, or ask the maintainers to use it.'
        for key in sorted(FILE_KEYS)
        if key not in used and not key.startswith(prefixes)
    ]
    _fail_on(problems)


# ── t() ──────────────────────────────────────────────────────────────────────

FIXTURE = """
[test.plain]
note = "A text without placeholders."
de = "Gebiet"
fr = "Zone"

[test.untranslated]
de = "Nur Deutsch"
fr = ""

[test.counted]
de = "{n} von {total} Kacheln"
fr = "{n} tuiles sur {total}"

[test.braces]
de = "$P = 1 - e^{-80\\\\,\\\\lambda}$ bei {n}"
fr = ""

[test.code.a]
de = "A"
fr = ""
"""


@pytest.fixture
def texts(tmp_path, monkeypatch):
    """t() reads the small fixture file; set_language picks the session's language."""
    path = tmp_path / "texts.toml"
    path.write_text(FIXTURE, encoding="utf-8")
    monkeypatch.setattr(ui_text, "_TEXTS", ui_text.load_texts(path))

    def set_language(lang: str) -> None:
        monkeypatch.setattr(ui_text, "language", lambda: lang)

    return set_language


def test_load_texts_names_the_broken_line(tmp_path):
    path = tmp_path / "texts.toml"
    path.write_text('[nav.ifk]\nde = "IFK-Berechnung\nfr = ""\n', encoding="utf-8")
    with pytest.raises(ValueError, match=r"texts.toml can't be read: .*line 2.*quote"):
        ui_text.load_texts(path)


def test_t_returns_german_by_default(texts):
    assert ui_text.t("test.plain") == "Gebiet"


def test_t_returns_french_in_a_french_session(texts):
    texts("fr")
    assert ui_text.t("test.plain") == "Zone"
    assert ui_text.t("test.counted", n=3, total=10) == "3 tuiles sur 10"


def test_t_falls_back_to_german_for_an_empty_translation(texts):
    texts("fr")
    assert ui_text.t("test.untranslated") == "Nur Deutsch"


def test_t_reads_a_key_below_a_code_dict(texts):
    assert ui_text.t("test.code.a") == "A"


def test_t_fills_placeholders_with_str(texts):
    assert ui_text.t("test.counted", n=3, total=None) == "3 von None Kacheln"


def test_t_keeps_braces_that_are_no_placeholder(texts):
    assert ui_text.t("test.braces", n=2) == "$P = 1 - e^{-80\\,\\lambda}$ bei 2"


def test_t_uses_a_language_given_in_place_of_the_session(texts):
    texts("fr")
    assert ui_text.t("test.plain", lang=ui_text.EXPORT_LANGUAGE) == "Gebiet"
    assert ui_text.t("test.counted", lang="de", n=3, total=10) == "3 von 10 Kacheln"
    texts("de")
    assert ui_text.t("test.plain", lang="fr") == "Zone"


def test_languages_lists_french_once_a_text_has_one(texts, monkeypatch):
    assert ui_text.languages() == ("de", "fr")
    german_only = {k: {**e, "fr": ""} for k, e in ui_text._TEXTS.items()}
    monkeypatch.setattr(ui_text, "_TEXTS", german_only)
    assert ui_text.languages() == ("de",)


def test_t_names_a_missing_key(texts):
    with pytest.raises(KeyError, match="test.nothing"):
        ui_text.t("test.nothing")


def test_t_names_a_placeholder_without_value(texts):
    with pytest.raises(KeyError, match=r"test\.counted.*'total'"):
        ui_text.t("test.counted", n=3)


def test_t_names_a_value_without_placeholder(texts):
    with pytest.raises(TypeError, match=r"test\.plain.*'n'"):
        ui_text.t("test.plain", n=3)


def _fake_streamlit(ctx, session_state: dict) -> types.ModuleType:
    module = types.ModuleType("streamlit")
    scriptrunner = types.SimpleNamespace(get_script_run_ctx=lambda suppress_warning: ctx)
    module.runtime = types.SimpleNamespace(scriptrunner=scriptrunner)
    module.session_state = session_state
    return module


def test_ui_text_does_not_import_streamlit():
    # The upload parser child and the derivate sidecar import ui_text and must stay light.
    code = "import sys, ui_text; print('streamlit' in sys.modules, ui_text.t('nav.ifk'))"
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO / "app",
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.split() == ["False", "IFK-Berechnung"]


def test_language_is_german_without_streamlit(monkeypatch):
    monkeypatch.delitem(sys.modules, "streamlit", raising=False)
    monkeypatch.delenv(ui_text.PROCESS_LANGUAGE_ENV, raising=False)
    assert ui_text.language() == "de"


def test_language_is_german_outside_a_script_run(monkeypatch):
    monkeypatch.setitem(sys.modules, "streamlit", _fake_streamlit(None, {"lang": "fr"}))
    monkeypatch.delenv(ui_text.PROCESS_LANGUAGE_ENV, raising=False)
    assert ui_text.language() == "de"


def test_language_of_a_process_without_session_comes_from_its_environment(monkeypatch):
    # How the upload parser child gets the session's language (polygon_upload).
    monkeypatch.delitem(sys.modules, "streamlit", raising=False)
    monkeypatch.setenv(ui_text.PROCESS_LANGUAGE_ENV, "fr")
    assert ui_text.language() == "fr"


@pytest.mark.parametrize(("session_state", "lang"), [({"lang": "fr"}, "fr"), ({}, "de")])
def test_language_comes_from_the_session(monkeypatch, session_state, lang):
    monkeypatch.setitem(sys.modules, "streamlit", _fake_streamlit(object(), session_state))
    assert ui_text.language() == lang
