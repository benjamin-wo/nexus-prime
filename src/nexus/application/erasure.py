"""Delete all of one user's data.

The database rows go in one transaction (see ``nexus.infra.db.user_data`` for the order). Only
after it commits are the things outside the database dealt with, each best effort and logged:
the stored files, the Gmail grant and the forwarding inbox. A failure there never undoes the
deletion; the rows that named those things are already gone, so there is nothing left to retry
from.
"""

import logging
from collections.abc import Callable

from nexus.application import email as email_cases
from nexus.application import ops
from nexus.application.email import EmailRuntime
from nexus.application.ports import ReceiptStore, UnitOfWork
from nexus.domain.ledger import User

log = logging.getLogger(__name__)

type UowFactory = Callable[[], UnitOfWork]


async def delete_user_data(
    uow: UowFactory,
    user: User,
    *,
    chat_thread: str,
    store: ReceiptStore | None,
    email: EmailRuntime | None,
) -> None:
    async with uow() as tx:
        # What lives outside the database, read before the rows that name it are gone.
        keys = [str(r["object_key"]) for r in await tx.user_data.rows(user.id, "receipts")]
        connections = await tx.email.list_connections(user.id)
        await tx.user_data.erase(user.id, chat_thread=chat_thread)
        await tx.commit()
    ref = ops.user_ref(user.id)
    log.info("user data deleted (user %s)", ref)

    unfinished = 0
    if store is not None:
        for key in keys:
            try:
                await store.delete(key)
            except Exception as exc:
                unfinished += 1
                log.warning("could not delete a stored file (%s)", type(exc).__name__)
    elif keys:
        unfinished += len(keys)
    if email is not None:
        for connection in connections:
            await email_cases.revoke_access(email, connection)
    if unfinished:
        log.warning("user %s: %d stored files were not deleted", ref, unfinished)
