"""Links to the web app that a chat reply can carry as a ``url:`` button."""


def app_link(origin: str | None, path: str) -> str | None:
    """The button data for a page of the web app; None when the web origin isn't known (the
    button is then left out)."""
    return f"url:{origin.rstrip('/')}{path}" if origin else None
