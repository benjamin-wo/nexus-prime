"""Health copy never uses the banned wording (report, Product rules: Wording).

Scans the health UI (``web/src/health``), every skill sheet, the fixed referral texts and any
web file named for health or gym. Tests and generated paths are skipped.

A legitimate use is allowed in one of two ways:
- put ``wording-ok`` on the same line (for a comment or a quoted rule, say), or
- add the file and phrase to ``ALLOWLIST`` below, with a reason.
"""

from pathlib import Path

from nexus.domain import health_texts
from nexus.domain.health_safety import BANNED_PHRASES, banned_phrases_in

ROOT = Path(__file__).resolve().parents[2]
MARKER = "wording-ok"
TEXT_SUFFIXES = {".ts", ".tsx", ".css", ".md", ".json", ".py", ".html"}

# (path relative to the repo root, phrase) -> why it is fine there. Finance and travel files are
# out of scope: only the health paths below are scanned, so "earnings" and the like never land
# here.
ALLOWLIST: dict[tuple[str, str], str] = {}


def health_files() -> list[Path]:
    found: set[Path] = set()
    for path in (ROOT / "web/src/health").rglob("*"):
        found.add(path)
    for path in (ROOT / "web/src").rglob("*"):
        if "health" in path.name.lower() or "gym" in path.name.lower():
            found.add(path)
    found.update((ROOT / "src/nexus/skills").glob("**/SKILL.md"))
    found.add(ROOT / "src/nexus/domain/health_texts.py")
    return sorted(
        p
        for p in found
        if p.is_file()
        and p.suffix in TEXT_SUFFIXES
        and ".test." not in p.name
        and "node_modules" not in p.parts
    )


def violations(path: Path) -> list[str]:
    relative = str(path.relative_to(ROOT))
    found = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if MARKER in line:
            continue
        for phrase in banned_phrases_in(line):
            if (relative, phrase) not in ALLOWLIST:
                found.append(f"{relative}:{number}: {phrase!r}")
    return found


def test_health_copy_avoids_banned_phrases() -> None:
    files = health_files()
    assert any(p.name == "health_texts.py" for p in files)
    assert any(p.name == "SKILL.md" for p in files)
    problems = [v for path in files for v in violations(path)]
    assert not problems, "banned wording in health copy:\n" + "\n".join(problems)


def test_the_referral_texts_are_clean() -> None:
    for name in dir(health_texts):
        value = getattr(health_texts, name)
        if name.startswith("TEXT_"):
            assert banned_phrases_in(value) == [], name


def test_marker_and_allowlist_work(tmp_path: Path) -> None:
    sample = tmp_path / "copy.md"
    sample.write_text("no junk here\nquote of a rule: junk  wording-ok\n", encoding="utf-8")
    flagged = [
        n
        for n, line in enumerate(sample.read_text().splitlines(), 1)
        if MARKER not in line and banned_phrases_in(line)
    ]
    assert flagged == [1]
    assert "junk" in BANNED_PHRASES
