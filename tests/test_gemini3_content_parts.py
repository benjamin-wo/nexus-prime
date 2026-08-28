"""Gemini 3.x returns message content as a LIST OF TYPED PARTS, not a string.

Live incident (2026-08-28 13:17-13:34): switching GEMINI_MODEL to
gemini-3.7-flash broke every LLM-backed extraction in the app at once.
Production logged, every ~20 seconds:

    [EXPENSES] JSON parse failed: Expecting property name enclosed in
    double quotes: line 1 column 3 (char 2)

That error is the signature of json.loads() being handed the *repr of a
list*: char 0 is '[', char 1 is '{', and char 2 is a single quote where a
double quote was required. Eight call sites did

    raw = str(getattr(ai_message, "content", "") or "").strip()

which is correct for Gemini 2.5 (content is a str) and silently produces
"[{'type': 'text', 'text': '...'}]" for Gemini 3.x. core/llm.py has carried
extract_llm_text for exactly this since before the switch -- its docstring
names the failure -- and none of these sites used it.

The knock-on was worse than the parse failures: each failed extraction fell
through to a second LLM call, the 10-minute email sweep began overlapping
itself ("maximum number of running instances reached"), and the resulting
call volume produced 504 DEADLINE_EXCEEDED -- at which point a bare "Hi"
could not get a model response inside 45s and hit the timeout from #76.
"""
import json

import pytest

from core.llm import extract_llm_text


# The exact shape Gemini 3.x hands back when thinking is enabled.
GEMINI_3_CONTENT = [
    {"type": "text", "text": '{"amount": 4.60, "currency": "SGD", "merchant": "BARCOOK BAKERY"}'}
]
GEMINI_25_CONTENT = '{"amount": 4.60, "currency": "SGD", "merchant": "BARCOOK BAKERY"}'


def test_the_old_pattern_reproduces_the_exact_production_error():
    """Pins the regression to its real signature, so a reader can match this
    test to the log line that reported it."""
    raw = str(GEMINI_3_CONTENT).strip()

    with pytest.raises(json.JSONDecodeError) as excinfo:
        json.loads(raw)

    assert "Expecting property name enclosed in double quotes" in str(excinfo.value)
    assert "line 1 column 3 (char 2)" in str(excinfo.value)


@pytest.mark.parametrize("content", [GEMINI_3_CONTENT, GEMINI_25_CONTENT])
def test_extract_llm_text_yields_parseable_json_for_both_model_generations(content):
    parsed = json.loads(extract_llm_text(content).strip())
    assert parsed["amount"] == 4.60
    assert parsed["merchant"] == "BARCOOK BAKERY"


def test_extract_llm_text_drops_thinking_parts():
    """Gemini 3.x interleaves reasoning parts with the answer; only the text
    parts may reach a JSON parser."""
    content = [
        {"type": "thinking", "thinking": "The user wants the total. Let me look..."},
        {"type": "text", "text": '{"amount": 12.5}'},
    ]
    assert json.loads(extract_llm_text(content).strip())["amount"] == 12.5


def test_no_llm_response_is_stringified_with_bare_str():
    """Guards every extraction site at once, including ones added later.

    Eight files shared this bug -- expenses, reminders, recipes, routes,
    memory, whiteboard, scheduled briefings and the dashboard -- because the
    pattern was copied. A grep-style assertion is the cheapest thing that
    catches the ninth copy.
    """
    import pathlib

    offenders = []
    for path in pathlib.Path(".").glob("**/*.py"):
        if any(part in path.parts for part in (".venv", "__pycache__", "tests")):
            continue
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            if 'str(getattr(ai_message, "content"' in line:
                offenders.append(f"{path}:{lineno}")

    assert not offenders, (
        "these stringify an LLM response instead of using extract_llm_text, "
        f"which breaks on Gemini 3.x list content: {offenders}"
    )


@pytest.mark.asyncio
async def test_expense_extraction_survives_gemini_3_content(monkeypatch):
    """End-to-end on the path that actually failed in production."""
    from langchain_core.messages import AIMessage

    import capabilities.expenses.tools as et

    class _Gemini3LLM:
        async def ainvoke(self, messages):
            return AIMessage(content=[{
                "type": "text",
                "text": '{"amount": 8.40, "currency": "SGD", "merchant": "COFFEE HIVE ADELPHI",'
                        ' "category": "Dining", "date_iso": "", "confidence": 0.95,'
                        ' "needs_clarification": false}',
            }])

    monkeypatch.setattr(et, "get_agent_llm", lambda *a, **k: _Gemini3LLM())

    result = await et.extract_expense_from_text.ainvoke(
        {"user_text": "coffee at hive adelphi 8.40"}
    )

    assert result["amount"] == 8.40
    assert result["merchant"] == "COFFEE HIVE ADELPHI"
