"""Structured answers from a model, forgiving of one slip models make now and then:
wrapping the object they were asked for in a list (``[{...}]``). The reply is asked
for with its raw message kept, so such a reply is read from the raw text instead of
failing."""

import json
import re
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable
from pydantic import BaseModel, ValidationError

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")


def structured[M: BaseModel](model: BaseChatModel, schema: type[M]) -> Runnable[Any, Any]:
    """``model`` asked for ``schema``, keeping the raw reply for ``parse_reply``."""
    return model.with_structured_output(schema, include_raw=True)


def parse_reply[M: BaseModel](reply: Any, schema: type[M]) -> M:
    """The ``schema`` object in a reply from ``structured``; raises when there's none."""
    if isinstance(reply, schema):
        return reply
    if not isinstance(reply, dict) or "raw" not in reply:
        return schema.model_validate(reply)
    parsed = reply.get("parsed")
    if parsed is not None:
        return parsed if isinstance(parsed, schema) else schema.model_validate(parsed)
    data = _raw_data(reply.get("raw"))
    if isinstance(data, list):
        for item in data:  # the object wrapped in a list
            if isinstance(item, dict):
                try:
                    return schema.model_validate(item)
                except ValidationError:
                    continue
    if isinstance(data, dict):
        return schema.model_validate(data)
    raise ValueError(f"no {schema.__name__} in the reply: {reply.get('parsing_error')}")


def _raw_data(raw: Any) -> Any:
    if not isinstance(raw, AIMessage):
        return None
    for call in raw.tool_calls:
        return call.get("args")
    for bad in raw.invalid_tool_calls:
        return _loads(bad.get("args"))
    content = raw.content
    if isinstance(content, list):
        content = "".join(
            part.get("text", "") if isinstance(part, dict) else str(part) for part in content
        )
    return _loads(content)


def _loads(text: Any) -> Any:
    if not isinstance(text, str):
        return None
    try:
        return json.loads(_FENCE.sub("", text.strip()))
    except ValueError:
        return None
