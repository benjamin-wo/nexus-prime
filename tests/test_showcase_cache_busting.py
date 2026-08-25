"""Regression (#29 reopened): a merged CSS fix didn't actually reach phones.

PR #33 fixed the mobile ``.task-card-item`` selector bug in
``showcase/styles.css``, deployed to production, and the owner still saw
the broken layout minutes later. Root cause (confirmed against Railway
deploy history: commit c55ade2 was live well before the "still there"
report): ``showcase/index.html`` cache-busts ``styles.css`` with a manual
``?v=N`` query param (see git history -- every prior CSS-affecting change
bumped it), but PR #33 edited ``styles.css`` without bumping it. Mobile
Safari kept serving its already-cached, pre-fix copy of the stylesheet
from the same URL indefinitely.

Fix: make the query param a content hash instead of a manually-tracked
counter, so it is *impossible* to ship a stylesheet change without also
changing the URL clients fetch it from -- closing this whole bug class
rather than just this one instance of it.
"""
import hashlib
import re
from pathlib import Path

SHOWCASE_DIR = Path(__file__).resolve().parent.parent / "showcase"
HASH_LEN = 10


def _read(name: str) -> str:
    return (SHOWCASE_DIR / name).read_text()


def _content_hash(name: str) -> str:
    return hashlib.sha256((SHOWCASE_DIR / name).read_bytes()).hexdigest()[:HASH_LEN]


def test_styles_css_cache_bust_matches_file_content():
    """index.html's styles.css query param must equal a hash of the file's
    actual current content, so any future edit to styles.css necessarily
    changes the URL and can't be served stale from a client cache."""
    index_html = _read("index.html")
    match = re.search(r'href="styles\.css\?v=([^"]+)"', index_html)
    assert match is not None, "index.html should link styles.css with a ?v= cache-busting param"

    expected = _content_hash("styles.css")
    assert match.group(1) == expected, (
        "showcase/index.html references styles.css with a stale cache-busting "
        f"value ({match.group(1)!r}); it must be the file's current content "
        f"hash ({expected!r}) or clients with a cached copy will never see "
        "the new stylesheet (this is exactly how #29 stayed broken after "
        "PR #33 merged and deployed)"
    )
