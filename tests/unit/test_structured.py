import pytest
from langchain_core.messages import AIMessage
from pydantic import BaseModel

from nexus.agent.structured import parse_reply


class Draft(BaseModel):
    is_receipt: bool
    merchant: str | None = None


def _failed(content: str) -> dict[str, object]:
    """What a structured call returns when the reply didn't fit the schema."""
    return {"raw": AIMessage(content=content), "parsed": None, "parsing_error": "bad"}


def test_a_parsed_reply_is_used_as_is() -> None:
    draft = Draft(is_receipt=True, merchant="Foodcourt ABC")
    assert parse_reply({"raw": AIMessage(content=""), "parsed": draft}, Draft) is draft
    assert parse_reply(draft, Draft) is draft


def test_an_object_wrapped_in_a_list_is_unwrapped() -> None:
    reply = _failed('[{"is_receipt": true, "merchant": "Kopi Corner"}]')
    assert parse_reply(reply, Draft) == Draft(is_receipt=True, merchant="Kopi Corner")


def test_a_fenced_reply_is_read() -> None:
    reply = _failed('```json\n[{"is_receipt": false}]\n```')
    assert parse_reply(reply, Draft) == Draft(is_receipt=False)


def test_the_first_item_that_fits_is_taken() -> None:
    reply = _failed('[{"nope": 1}, {"is_receipt": true}]')
    assert parse_reply(reply, Draft) == Draft(is_receipt=True)


def test_tool_call_arguments_are_read() -> None:
    raw = AIMessage(
        content="",
        tool_calls=[{"name": "Draft", "args": {"is_receipt": True}, "id": "call_1"}],
    )
    assert parse_reply({"raw": raw, "parsed": None}, Draft) == Draft(is_receipt=True)


@pytest.mark.parametrize("content", ["not json", "[]", "[1, 2]", '"text"'])
def test_a_reply_with_no_object_still_fails(content: str) -> None:
    with pytest.raises(ValueError):
        parse_reply(_failed(content), Draft)
