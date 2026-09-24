"""DAG definition service with database-backed storage and version history.

Replaces in-memory DAG definitions with persistent storage.
Every update creates a new version, preserving full history (Requirement 8.2).
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.project import DAGDefinition, Project


class DAGService:
    """Service for DAG definition CRUD with version history."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_dag(
        self,
        org_id: UUID,
        project_id: UUID,
        name: str,
        definition: dict,
        description: str | None = None,
        created_by: UUID | None = None,
    ) -> DAGDefinition:
        """Create a new DAG definition (version 1).

        Args:
            org_id: Organization ID for scoping.
            project_id: Parent project ID.
            name: Logical DAG name.
            definition: DAG definition dict (steps, dependencies, etc.).
            description: Optional description.
            created_by: Optional user ID.

        Returns:
            The created DAGDefinition at version 1.

        Raises:
            ValueError: If the project does not exist in the given org.
        """
        # Verify project exists and belongs to org
        proj_stmt = select(Project).where(
            and_(Project.id == project_id, Project.organization_id == org_id)
        )
        proj_result = await self.db.execute(proj_stmt)
        if proj_result.scalar_one_or_none() is None:
            raise ValueError(f"Project {project_id} not found in organization {org_id}")

        dag = DAGDefinition(
            id=uuid4(),
            organization_id=org_id,
            project_id=project_id,
            name=name,
            version=1,
            definition=definition,
            description=description,
            created_by=created_by,
            created_at=datetime.utcnow(),
        )
        self.db.add(dag)
        await self.db.commit()
        await self.db.refresh(dag)
        return dag

    async def update_dag(
        self,
        org_id: UUID,
        project_id: UUID,
        name: str,
        definition: dict,
        description: str | None = None,
        created_by: UUID | None = None,
    ) -> DAGDefinition:
        """Create a new version of an existing DAG definition.

        The previous versions are preserved for history. The new version
        number is max(existing) + 1.

        Args:
            org_id: Organization ID.
            project_id: Parent project ID.
            name: Logical DAG name (must match an existing DAG).
            definition: Updated DAG definition dict.
            description: Optional description for this version.
            created_by: Optional user ID.

        Returns:
            The new DAGDefinition version.

        Raises:
            ValueError: If no existing DAG with this name exists in the project.
        """
        # Find the latest version
        latest = await self.get_latest_dag(org_id, project_id, name)
        if latest is None:
            raise ValueError(f"DAG '{name}' not found in project {project_id}")

        new_version = latest.version + 1

        dag = DAGDefinition(
            id=uuid4(),
            organization_id=org_id,
            project_id=project_id,
            name=name,
            version=new_version,
            definition=definition,
            description=description,
            created_by=created_by,
            created_at=datetime.utcnow(),
        )
        self.db.add(dag)
        await self.db.commit()
        await self.db.refresh(dag)
        return dag

    async def get_dag(self, dag_id: UUID, org_id: UUID) -> DAGDefinition | None:
        """Get a specific DAG definition by ID."""
        stmt = select(DAGDefinition).where(
            and_(DAGDefinition.id == dag_id, DAGDefinition.organization_id == org_id)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_latest_dag(
        self, org_id: UUID, project_id: UUID, name: str
    ) -> DAGDefinition | None:
        """Get the latest version of a DAG by name within a project."""
        stmt = (
            select(DAGDefinition)
            .where(
                and_(
                    DAGDefinition.organization_id == org_id,
                    DAGDefinition.project_id == project_id,
                    DAGDefinition.name == name,
                )
            )
            .order_by(desc(DAGDefinition.version))
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_dag_version_history(
        self, org_id: UUID, project_id: UUID, name: str
    ) -> list[DAGDefinition]:
        """Get all versions of a DAG, ordered newest-first."""
        stmt = (
            select(DAGDefinition)
            .where(
                and_(
                    DAGDefinition.organization_id == org_id,
                    DAGDefinition.project_id == project_id,
                    DAGDefinition.name == name,
                )
            )
            .order_by(desc(DAGDefinition.version))
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def list_dags(
        self,
        org_id: UUID,
        project_id: UUID,
        latest_only: bool = True,
    ) -> list[DAGDefinition]:
        """List DAG definitions in a project.

        Args:
            org_id: Organization ID.
            project_id: Project ID.
            latest_only: If True, return only the latest version of each DAG name.

        Returns:
            List of DAGDefinition records.
        """
        if latest_only:
            # Subquery to get max version per name
            max_ver = (
                select(
                    DAGDefinition.name,
                    func.max(DAGDefinition.version).label("max_version"),
                )
                .where(
                    and_(
                        DAGDefinition.organization_id == org_id,
                        DAGDefinition.project_id == project_id,
                    )
                )
                .group_by(DAGDefinition.name)
                .subquery()
            )
            stmt = (
                select(DAGDefinition)
                .join(
                    max_ver,
                    and_(
                        DAGDefinition.name == max_ver.c.name,
                        DAGDefinition.version == max_ver.c.max_version,
                    ),
                )
                .where(
                    and_(
                        DAGDefinition.organization_id == org_id,
                        DAGDefinition.project_id == project_id,
                    )
                )
                .order_by(DAGDefinition.name)
            )
        else:
            stmt = (
                select(DAGDefinition)
                .where(
                    and_(
                        DAGDefinition.organization_id == org_id,
                        DAGDefinition.project_id == project_id,
                    )
                )
                .order_by(DAGDefinition.name, desc(DAGDefinition.version))
            )

        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def delete_dag_all_versions(self, org_id: UUID, project_id: UUID, name: str) -> int:
        """Delete all versions of a DAG by name.

        Returns the number of versions deleted.
        """
        versions = await self.get_dag_version_history(org_id, project_id, name)
        count = len(versions)
        for v in versions:
            await self.db.delete(v)
        if count > 0:
            await self.db.commit()
        return count
