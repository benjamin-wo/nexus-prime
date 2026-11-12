"""The labels a chat turn shows while it works."""

import re

from nexus.agent.progress import GENERIC, LABELS, label_for
from nexus.agent.skills import SkillLibrary
from nexus.agent.tools import build_tools


def test_common_tools_have_plain_labels() -> None:
    assert label_for("log_expense") == "Logging the expense"
    assert label_for("web_search") == "Looking that up on the web"
    assert label_for("split_bill") == "Splitting the bill"
    assert label_for("list_budgets") == "Checking your budgets"


def test_an_unlabelled_tool_gets_the_generic_words_never_its_name() -> None:
    assert label_for("some_new_tool") == GENERIC == "Working on it"


def test_labels_are_plain_sentences_with_no_internal_names_or_ids() -> None:
    for tool, label in LABELS.items():
        assert label[0].isupper() and not label.endswith("."), label
        assert not re.search(r"[_\d{}<>:/]", label), label
        assert tool not in label


def test_every_label_is_for_a_real_tool() -> None:
    tools = set(build_tools(SkillLibrary.load().body))
    assert set(LABELS) <= tools
