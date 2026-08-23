from typing import Optional, Dict, Any, List
from datetime import datetime
from sqlmodel import select, desc
from core.db import async_session_factory
from core.models import WhiteboardProject, WhiteboardBlock, TaskItem, ExpenseTransaction

DEFAULT_SECTION_TEMPLATES: Dict[str, List[str]] = {
    "trip": ["Before You Go", "Stays & Options", "Itinerary", "Budget", "Notes"],
    "meal": ["Recipes", "Meal Plan", "Groceries", "Notes"],
    "event": ["Venue & Options", "Checklist", "Budget", "Notes"],
    "project": ["Ideas", "Milestones", "Budget", "Notes"],
    "general": ["Ideas", "Checklist", "Notes"],
}


def _normalize_section_name(section_name: str) -> str:
    return (section_name or "").strip() or "General"


async def _sync_section_order(session, proj: WhiteboardProject, section_name: str) -> None:
    """Append section_name to proj.section_order if it is not tracked yet."""
    order = list(proj.section_order or [])
    if section_name not in order:
        order.append(section_name)
        proj.section_order = order
        session.add(proj)


async def set_last_board(user_id: int, project_id: int) -> None:
    """Persist the user's most recently touched board (survives restarts/deployments)."""
    from core.models import UserProfile

    async with async_session_factory() as session:
        profile = (await session.execute(
            select(UserProfile).where(UserProfile.user_id == user_id)
        )).scalar_one_or_none()
        if profile:
            profile.last_whiteboard_id = project_id
            session.add(profile)
            await session.commit()


async def get_last_board(user_id: int) -> Optional[WhiteboardProject]:
    """The board stored as the user's most recent planning target, if any."""
    from core.models import UserProfile

    async with async_session_factory() as session:
        profile = (await session.execute(
            select(UserProfile).where(UserProfile.user_id == user_id)
        )).scalar_one_or_none()
        if not profile or not profile.last_whiteboard_id:
            return None
        return (await session.execute(
            select(WhiteboardProject).where(
                WhiteboardProject.id == profile.last_whiteboard_id,
                WhiteboardProject.user_id == user_id,
            )
        )).scalar_one_or_none()


async def list_user_boards(user_id: int) -> List[WhiteboardProject]:
    """All boards for a user, most recently updated first."""
    async with async_session_factory() as session:
        result = await session.execute(
            select(WhiteboardProject)
            .where(WhiteboardProject.user_id == user_id)
            .order_by(desc(WhiteboardProject.updated_at))
        )
        return list(result.scalars().all())


async def find_board(user_id: int, query: str) -> Optional[WhiteboardProject]:
    """Case-insensitive substring match of a board by title fragment."""
    q = (query or "").strip().strip("#").lower()
    if not q:
        return None
    boards = await list_user_boards(user_id)
    for board in boards:
        if q in board.title.lower():
            return board
    # Fallback: token overlap match (e.g. "tokyo trip" matches "Trip to Tokyo")
    tokens = [t for t in q.replace("-", " ").split() if len(t) > 2]
    best, best_score = None, 0
    for board in boards:
        title_lower = board.title.lower()
        score = sum(1 for t in tokens if t in title_lower)
        if score > best_score:
            best, best_score = board, score
    return best


async def create_board(
    user_id: int,
    title: str,
    category: str = "general",
    emoji_icon: str = "📋",
    summary: Optional[str] = None,
    sections: Optional[List[str]] = None,
) -> WhiteboardProject:
    """Create a new board, optionally seeding an explicit section order."""
    section_list = [s.strip() for s in (sections or DEFAULT_SECTION_TEMPLATES.get(category, DEFAULT_SECTION_TEMPLATES["general"])) if s.strip()]
    async with async_session_factory() as session:
        project = WhiteboardProject(
            user_id=user_id,
            title=title.strip(),
            category=category if category in DEFAULT_SECTION_TEMPLATES else "general",
            emoji_icon=emoji_icon or "📋",
            summary=summary,
            section_order=section_list,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        session.add(project)
        await session.commit()
        await session.refresh(project)
        return project


async def create_or_get_whiteboard(
    user_id: int,
    title: str,
    category: str = "general",
    emoji_icon: str = "📋",
    summary: Optional[str] = None,
) -> WhiteboardProject:
    """Create or retrieve a WhiteboardProject by title for a user."""
    async with async_session_factory() as session:
        result = await session.execute(
            select(WhiteboardProject).where(
                WhiteboardProject.user_id == user_id,
                WhiteboardProject.title.ilike(f"%{title.strip()}%"),
            )
        )
        project = result.scalars().first()
        if not project:
            project = WhiteboardProject(
                user_id=user_id,
                title=title.strip(),
                category=category,
                emoji_icon=emoji_icon,
                summary=summary,
                section_order=DEFAULT_SECTION_TEMPLATES.get(category, DEFAULT_SECTION_TEMPLATES["general"]),
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            session.add(project)
            await session.commit()
            await session.refresh(project)
        return project


async def add_block_to_whiteboard(
    project_id: int,
    section_name: str,
    block_type: str,
    title: str,
    content_payload: Dict[str, Any],
    position_order: Optional[int] = None,
) -> WhiteboardBlock:
    """Append or insert a block into a project board (appends after the last block by default)."""
    section = _normalize_section_name(section_name)
    async with async_session_factory() as session:
        proj = (await session.execute(
            select(WhiteboardProject).where(WhiteboardProject.id == project_id)
        )).scalar_one_or_none()

        if position_order is None:
            max_pos = (await session.execute(
                select(WhiteboardBlock.position_order)
                .where(WhiteboardBlock.project_id == project_id)
                .order_by(desc(WhiteboardBlock.position_order))
                .limit(1)
            )).scalar()
            position_order = (max_pos or 0) + 1

        block = WhiteboardBlock(
            project_id=project_id,
            section_name=section,
            block_type=block_type,
            title=title.strip(),
            content_payload=content_payload or {},
            position_order=position_order,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        session.add(block)

        if proj:
            proj.updated_at = datetime.utcnow()
            await _sync_section_order(session, proj, section)

        await session.commit()
        await session.refresh(block)
        return block


async def fetch_whiteboard_details(project_id: int) -> Optional[Dict[str, Any]]:
    """Fetch complete board with all blocks grouped by section."""
    async with async_session_factory() as session:
        proj = (await session.execute(
            select(WhiteboardProject).where(WhiteboardProject.id == project_id)
        )).scalar_one_or_none()
        if not proj:
            return None

        blocks = (await session.execute(
            select(WhiteboardBlock)
            .where(WhiteboardBlock.project_id == project_id)
            .order_by(WhiteboardBlock.section_name, WhiteboardBlock.position_order, WhiteboardBlock.id)
        )).scalars().all()

        return {
            "project": proj.model_dump(),
            "blocks": [b.model_dump() for b in blocks],
        }


async def board_summary_text(project_id: int) -> Optional[str]:
    """Compact human-readable summary of a board for chat surfaces."""
    details = await fetch_whiteboard_details(project_id)
    if not details:
        return None
    proj = details["project"]
    blocks = details["blocks"]

    sections: Dict[str, List[WhiteboardBlock]] = {}
    for b in blocks:
        sections.setdefault(b["section_name"], []).append(b)

    lines = [f"{proj.get('emoji_icon', '📋')} **{proj['title']}** ({len(blocks)} cards)"]
    if proj.get("summary"):
        lines.append(f"_{proj['summary']}_")
    for sec_name, sec_blocks in sections.items():
        lines.append(f"\n**{sec_name}**")
        for b in sec_blocks[:6]:
            icon = {"checklist": "☑️", "comparison": "⚖️", "itinerary": "🗓", "budget": "💰", "note": "📝"}.get(b["block_type"], "•")
            lines.append(f"  {icon} {b['title']}")
        if len(sec_blocks) > 6:
            lines.append(f"  …and {len(sec_blocks) - 6} more")
    if not blocks:
        lines.append("\n_(empty board — add cards via the web canvas or AI copilot)_")
    return "\n".join(lines)
