from typing import Optional, Dict, Any, List
from datetime import datetime
from sqlmodel import select
from core.db import async_session_factory
from core.models import WhiteboardProject, WhiteboardBlock, TaskItem, ExpenseTransaction

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
    position_order: int = 0,
) -> WhiteboardBlock:
    """Append or insert a block into a project board."""
    async with async_session_factory() as session:
        block = WhiteboardBlock(
            project_id=project_id,
            section_name=section_name.strip() or "General",
            block_type=block_type,
            title=title.strip(),
            content_payload=content_payload or {},
            position_order=position_order,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        session.add(block)
        
        # update project updated_at
        proj = (await session.execute(
            select(WhiteboardProject).where(WhiteboardProject.id == project_id)
        )).scalar_one_or_none()
        if proj:
            proj.updated_at = datetime.utcnow()
            session.add(proj)

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
