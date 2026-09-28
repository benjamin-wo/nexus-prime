"""Errors raised by use cases. Channels map these to user-facing replies."""

from uuid import UUID


class NexusError(Exception):
    """Base class for expected, user-explainable failures."""


class InvalidInput(NexusError, ValueError):
    """The request is malformed or breaks a domain rule."""


class NotFound(NexusError):
    """The thing does not exist for this user.

    Also raised for another user's data, so existence is never leaked.
    """


class Forbidden(NexusError):
    """The actor may not do this."""


class Conflict(NexusError):
    """The request clashes with existing state."""


class DuplicateSource(Conflict):
    """This external item was already ingested, even if since deleted."""

    def __init__(self, source: str, external_id: str, transaction_id: UUID | None) -> None:
        super().__init__(f"{source} item {external_id!r} was already recorded")
        self.source = source
        self.external_id = external_id
        self.transaction_id = transaction_id


class NothingToUndo(NexusError):
    pass
