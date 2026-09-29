"""PostgreSQL storage for connected mailboxes. Every query filters on user_id,
except the sweep's list of mailboxes to visit."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Row, delete, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from nexus.domain.email import (
    ConnectionStatus,
    EmailConnection,
    EmailStatus,
    InboundEmail,
    Provider,
)
from nexus.domain.ledger import UserId
from nexus.infra.db.tables import email_connections, email_links, inbound_emails


def _connection(row: Row[Any]) -> EmailConnection:
    return EmailConnection(
        id=row.id,
        user_id=UserId(row.user_id),
        provider=Provider(row.provider),
        address=row.address,
        token=bytes(row.token),
        status=ConnectionStatus(row.status),
        synced_until=row.synced_until,
        created_at=row.created_at,
        updated_at=row.updated_at,
        last_error=row.last_error,
    )


def _inbound(row: Row[Any]) -> InboundEmail:
    return InboundEmail(
        id=row.id,
        user_id=UserId(row.user_id),
        connection_id=row.connection_id,
        provider_message_id=row.provider_message_id,
        received_at=row.received_at,
        sender=row.sender,
        subject=row.subject,
        status=EmailStatus(row.status),
        reason=row.reason,
        draft=row.draft,
        transaction_id=row.transaction_id,
        created_at=row.created_at,
    )


class SqlEmailRepository:
    def __init__(self, connection: AsyncConnection) -> None:
        self._db = connection

    # --- connect links ------------------------------------------------------------

    async def insert_link(
        self, user_id: UserId, token_hash: str, *, expires_at: datetime, now: datetime
    ) -> None:
        await self._db.execute(
            insert(email_links).values(
                id=uuid4(),
                user_id=user_id,
                token_hash=token_hash,
                expires_at=expires_at,
                created_at=now,
            )
        )

    async def link_owner(self, token_hash: str, now: datetime) -> UserId | None:
        """Whose link this is, while it's unused and unexpired."""
        found = await self._db.scalar(
            select(email_links.c.user_id).where(
                email_links.c.token_hash == token_hash,
                email_links.c.used_at.is_(None),
                email_links.c.expires_at > now,
            )
        )
        return UserId(found) if found else None

    async def use_link(self, token_hash: str, now: datetime) -> UserId | None:
        """Spend a link. Only the first caller gets its owner back."""
        found = await self._db.scalar(
            update(email_links)
            .where(
                email_links.c.token_hash == token_hash,
                email_links.c.used_at.is_(None),
                email_links.c.expires_at > now,
            )
            .values(used_at=now)
            .returning(email_links.c.user_id)
        )
        return UserId(found) if found else None

    # --- connections ----------------------------------------------------------------

    async def save_connection(self, connection: EmailConnection) -> EmailConnection:
        """Add a mailbox, or refresh the token of one already connected."""
        c = email_connections.c
        stmt = (
            pg_insert(email_connections)
            .values(
                id=connection.id,
                user_id=connection.user_id,
                provider=connection.provider.value,
                address=connection.address,
                token=connection.token,
                status=connection.status.value,
                synced_until=connection.synced_until,
                created_at=connection.created_at,
                updated_at=connection.updated_at,
            )
            .on_conflict_do_update(
                index_elements=[c.user_id, c.provider, c.address],
                set_={
                    "token": connection.token,
                    "status": ConnectionStatus.ACTIVE.value,
                    "last_error": None,
                    "updated_at": connection.updated_at,
                },
            )
            .returning(email_connections)
        )
        row = (await self._db.execute(stmt)).one()
        return _connection(row)

    async def get_connection(
        self, user_id: UserId, connection_id: UUID, *, for_update: bool = False
    ) -> EmailConnection | None:
        stmt = select(email_connections).where(
            email_connections.c.user_id == user_id, email_connections.c.id == connection_id
        )
        if for_update:
            stmt = stmt.with_for_update()
        row = (await self._db.execute(stmt)).first()
        return _connection(row) if row else None

    async def list_connections(self, user_id: UserId) -> list[EmailConnection]:
        rows = await self._db.execute(
            select(email_connections)
            .where(email_connections.c.user_id == user_id)
            .order_by(email_connections.c.created_at)
        )
        return [_connection(r) for r in rows]

    async def connections_to_sweep(self) -> list[EmailConnection]:
        """Across all users: every working mailbox."""
        rows = await self._db.execute(
            select(email_connections)
            .where(email_connections.c.status == ConnectionStatus.ACTIVE.value)
            .order_by(email_connections.c.created_at)
        )
        return [_connection(r) for r in rows]

    async def update_connection(self, connection: EmailConnection) -> None:
        await self._db.execute(
            update(email_connections)
            .where(
                email_connections.c.user_id == connection.user_id,
                email_connections.c.id == connection.id,
            )
            .values(
                token=connection.token,
                status=connection.status.value,
                synced_until=connection.synced_until,
                last_error=connection.last_error,
                updated_at=connection.updated_at,
            )
        )

    async def delete_connection(self, user_id: UserId, connection_id: UUID) -> None:
        """Forget a mailbox and its email log (the ledger's dedupe keys stay)."""
        await self._db.execute(
            delete(email_connections).where(
                email_connections.c.user_id == user_id, email_connections.c.id == connection_id
            )
        )

    # --- inbound emails -----------------------------------------------------------

    async def seen_message_ids(self, connection_id: UUID, ids: list[str]) -> set[str]:
        if not ids:
            return set()
        rows = await self._db.execute(
            select(inbound_emails.c.provider_message_id).where(
                inbound_emails.c.connection_id == connection_id,
                inbound_emails.c.provider_message_id.in_(ids),
            )
        )
        return {r[0] for r in rows}

    async def insert_inbound(self, email: InboundEmail) -> bool:
        """False if this mailbox message was already recorded."""
        result = await self._db.execute(
            pg_insert(inbound_emails)
            .values(
                id=email.id,
                user_id=email.user_id,
                connection_id=email.connection_id,
                provider_message_id=email.provider_message_id,
                received_at=email.received_at,
                sender=email.sender,
                subject=email.subject,
                status=email.status.value,
                reason=email.reason,
                draft=email.draft,
                transaction_id=email.transaction_id,
                created_at=email.created_at,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    inbound_emails.c.connection_id,
                    inbound_emails.c.provider_message_id,
                ]
            )
        )
        return bool(result.rowcount)

    async def get_inbound(
        self, user_id: UserId, email_id: UUID, *, for_update: bool = False
    ) -> InboundEmail | None:
        stmt = select(inbound_emails).where(
            inbound_emails.c.user_id == user_id, inbound_emails.c.id == email_id
        )
        if for_update:
            stmt = stmt.with_for_update()
        row = (await self._db.execute(stmt)).first()
        return _inbound(row) if row else None

    async def update_inbound(self, email: InboundEmail) -> None:
        await self._db.execute(
            update(inbound_emails)
            .where(inbound_emails.c.user_id == email.user_id, inbound_emails.c.id == email.id)
            .values(
                status=email.status.value,
                reason=email.reason,
                draft=email.draft,
                transaction_id=email.transaction_id,
            )
        )

    async def list_inbound(
        self, user_id: UserId, *, since: datetime, limit: int
    ) -> list[InboundEmail]:
        rows = await self._db.execute(
            select(inbound_emails)
            .where(inbound_emails.c.user_id == user_id, inbound_emails.c.received_at >= since)
            .order_by(inbound_emails.c.received_at.desc())
            .limit(limit)
        )
        return [_inbound(r) for r in rows]
