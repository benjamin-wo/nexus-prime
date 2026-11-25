"""Buttons that open a page of the web app."""


def app_link(origin: str | None, path: str) -> str | None:
    """A url button's data for ``path`` on the web app, or None when its origin isn't known."""
    return f"url:{origin.rstrip('/')}{path}" if origin else None
