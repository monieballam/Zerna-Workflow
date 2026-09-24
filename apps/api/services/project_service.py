"""Project service for database-backed project CRUD operations.

Replaces in-memory project listings with persistent storage.
All project data survives API restarts (Requirement 8.1, 8.4).
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from apps.api.models.project import Project


class ProjectService:
    """Service for project CRUD with database-backed persistent storage."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_project(
        self,
        org_id: UUID,
        name: str,
        description: str | None = None,
        metadata: dict | None = None,
        created_by: UUID | None = None,
    ) -> Project:
        """Create a new project.

        Args:
            org_id: Organization ID for scoping.
            name: Project name.
            description: Optional description.
            metadata: Optional extra metadata dict.
            created_by: Optional user ID who created the project.

        Returns:
            The created Project.
        """
        project = Project(
            id=uuid4(),
            organization_id=org_id,
            name=name,
            description=description,
            extra_metadata=metadata or {},
            created_by=created_by,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        self.db.add(project)
        await self.db.commit()
        await self.db.refresh(project)
        return project

    async def get_project(self, project_id: UUID, org_id: UUID) -> Project | None:
        """Get a project by ID with organization scoping.

        Returns None if not found or not in the given org.
        """
        stmt = (
            select(Project)
            .where(and_(Project.id == project_id, Project.organization_id == org_id))
            .options(selectinload(Project.dag_definitions))
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_projects(
        self,
        org_id: UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Project], int]:
        """List projects with pagination.

        Returns (projects, total_count).
        """
        base = select(Project).where(Project.organization_id == org_id)

        count_stmt = select(func.count()).select_from(base.subquery())
        total_result = await self.db.execute(count_stmt)
        total = total_result.scalar_one()

        page_stmt = base.order_by(desc(Project.created_at)).offset(offset).limit(limit)
        result = await self.db.execute(page_stmt)
        return list(result.scalars().all()), total

    async def update_project(
        self,
        project_id: UUID,
        org_id: UUID,
        name: str | None = None,
        description: str | None = None,
        metadata: dict | None = None,
    ) -> Project | None:
        """Update a project's mutable fields.

        Returns the updated Project, or None if not found.
        """
        project = await self.get_project(project_id, org_id)
        if project is None:
            return None

        if name is not None:
            project.name = name
        if description is not None:
            project.description = description
        if metadata is not None:
            project.extra_metadata = {**project.extra_metadata, **metadata}
        project.updated_at = datetime.utcnow()

        await self.db.commit()
        await self.db.refresh(project)
        return project

    async def delete_project(self, project_id: UUID, org_id: UUID) -> bool:
        """Delete a project and its DAG definitions (cascade).

        Returns True if deleted, False if not found.
        """
        project = await self.get_project(project_id, org_id)
        if project is None:
            return False

        await self.db.delete(project)
        await self.db.commit()
        return True
