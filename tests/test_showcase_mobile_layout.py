"""Regression (#29): the mobile stylesheet for the Tasks & Reminders Cockpit
never actually applied.

``showcase/app.js`` renders each task as ``<div class="task-card-item ...">``
(see ``renderTasksList`` / the template around ``task-card-item``), but the
mobile media query in ``showcase/styles.css`` targeted a nonexistent
``.task-item-card`` selector (word order reversed). With no mobile override,
the card kept its desktop row layout on phones: the fixed-width actions
column (Test Alert / Edit / delete) squeezed the title column down to
~60-90px, and ``.task-title-text``'s ``word-break: break-word`` chopped every
word in the task title onto its own line (reported on an iPhone 17 Pro,
issue #29).

These are lightweight structural checks on the stylesheet/markup text rather
than a rendered-DOM test, since this is a static asset with no JS test
runner in this repo -- but they pin down the exact regression: the class
names actually agree, and the mobile rule no longer just tweaks padding, it
also stops the actions column from squeezing the title.
"""
import re
from pathlib import Path

SHOWCASE_DIR = Path(__file__).resolve().parent.parent / "showcase"


def _read(name: str) -> str:
    return (SHOWCASE_DIR / name).read_text()


def _mobile_media_block(css: str) -> str:
    """Return the body of the `@media (max-width: 900px)` block that houses
    the Tasks & Reminders Cockpit rules (the second such block in the file --
    the first is a smaller dashboard-grid-only block)."""
    blocks = re.findall(r"@media \(max-width: 900px\) \{(.*?)\n\}\n", css, re.DOTALL)
    for block in blocks:
        if ".task-stat-card" in block:
            return block
    raise AssertionError("could not find the Tasks & Reminders Cockpit mobile media block")


def test_task_card_class_names_agree_between_js_and_css():
    """The class app.js actually renders must be the one styles.css targets."""
    app_js = _read("app.js")
    css = _read("styles.css")

    assert '"task-card-item ' in app_js, "app.js should render task cards as task-card-item"
    assert ".task-item-card" not in css, (
        "styles.css still references the nonexistent '.task-item-card' class "
        "(should be '.task-card-item', matching the markup app.js renders)"
    )


def test_mobile_task_card_wraps_actions_below_title():
    """On narrow viewports the actions column must drop to its own row
    instead of squeezing the title column down to a sliver."""
    mobile_css = _mobile_media_block(_read("styles.css"))

    task_card_rule = re.search(r"\.task-card-item\s*\{([^}]*)\}", mobile_css)
    assert task_card_rule is not None, "no mobile .task-card-item rule found"
    assert "flex-wrap" in task_card_rule.group(1), (
        ".task-card-item must wrap on mobile so the actions column can drop "
        "to a second row instead of squeezing the title"
    )

    actions_col_rule = re.search(r"\.task-actions-col\s*\{([^}]*)\}", mobile_css)
    assert actions_col_rule is not None, "no mobile .task-actions-col rule found"
    assert "100%" in actions_col_rule.group(1), (
        ".task-actions-col must take the full card width on mobile so it "
        "wraps to its own row rather than sitting beside the title"
    )
