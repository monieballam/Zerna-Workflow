"""KnowledgePack service for managing versioned reference data."""

from typing import Optional
from uuid import UUID

from zerna_contracts.enums import KnowledgePackType
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.annotation import KnowledgePack
from apps.api.services.cache_service import CacheService
from apps.api.services.s3_service import S3Service


class KnowledgePackService:
    """Service for knowledge pack lifecycle management."""

    def __init__(
        self,
        db: AsyncSession,
        s3_service: S3Service | None = None,
        cache_service: Optional["CacheService"] = None,
    ):
        self.db = db
        self.s3_service = s3_service or S3Service()
        self.cache = cache_service

    async def create_knowledge_pack(
        self,
        name: str,
        version: str,
        pack_type: KnowledgePackType,
        s3_path: str,
        schema_version: str | None = None,
        metadata: dict | None = None,
    ) -> KnowledgePack:
        """Create a new knowledge pack, raising ValueError if name+version already exists."""
        existing = await self.get_knowledge_pack_by_name_version(name, version)
        if existing is not None:
            raise ValueError(
                f"KnowledgePack '{name}' version '{version}' already exists. "
                "Old versions are preserved and cannot be overwritten."
            )

        pack = KnowledgePack(
            name=name,
            version=version,
            pack_type=pack_type,
            s3_path=s3_path,
            schema_version=schema_version,
            extra_metadata=metadata or {},
        )
        self.db.add(pack)
        await self.db.commit()
        await self.db.refresh(pack)

        # Invalidate knowledge pack list caches
        if self.cache:
            await self.cache.invalidate_knowledge_packs()

        return pack

    async def get_knowledge_pack(self, pack_id: UUID) -> KnowledgePack | None:
        """Return KnowledgePack by ID or None."""
        stmt = select(KnowledgePack).where(KnowledgePack.id == pack_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_knowledge_pack_by_name_version(
        self, name: str, version: str
    ) -> KnowledgePack | None:
        """Return KnowledgePack by name+version or None."""
        stmt = select(KnowledgePack).where(
            and_(KnowledgePack.name == name, KnowledgePack.version == version)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_knowledge_packs(
        self,
        pack_type: KnowledgePackType | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[KnowledgePack]:
        """List knowledge packs with optional type filter and pagination.

        Results are cached for CacheTTL.KNOWLEDGE_PACK seconds (1 hour).
        Cache is invalidated when new packs are created.
        """
        stmt = select(KnowledgePack)
        if pack_type is not None:
            stmt = stmt.where(KnowledgePack.pack_type == pack_type)
        stmt = stmt.order_by(KnowledgePack.created_at.desc()).offset(offset).limit(limit)
        result = await self.db.execute(stmt)
        packs = list(result.scalars().all())

        return packs

    def validate_schema(self, pack_type: KnowledgePackType, data: dict) -> tuple[bool, str | None]:
        """Basic schema validation per pack type. Returns (is_valid, error_msg)."""
        if pack_type == KnowledgePackType.CELL_TYPE_MARKERS:
            if "markers" not in data:
                return False, "CELL_TYPE_MARKERS pack must contain 'markers' key"
            if not isinstance(data["markers"], dict):
                return False, "'markers' must be a dict mapping cell type to gene list"
        elif pack_type == KnowledgePackType.PATHWAY_DATABASE:
            if "pathways" not in data:
                return False, "PATHWAY_DATABASE pack must contain 'pathways' key"
            if not isinstance(data["pathways"], dict):
                return False, "'pathways' must be a dict mapping pathway name to gene list"
        elif pack_type == KnowledgePackType.LIGAND_RECEPTOR_PAIRS:
            if "pairs" not in data:
                return False, "LIGAND_RECEPTOR_PAIRS pack must contain 'pairs' key"
            if not isinstance(data["pairs"], list):
                return False, "'pairs' must be a list of ligand-receptor pair dicts"
        return True, None

    async def upload_knowledge_pack(
        self,
        name: str,
        version: str,
        pack_type: KnowledgePackType,
        file_content: bytes,
        schema_version: str | None = None,
        metadata: dict | None = None,
    ) -> KnowledgePack:
        """Upload file content to S3 then create DB record.

        S3 path: knowledge-packs/{name}/{version}/data
        """
        s3_path = f"knowledge-packs/{name}/{version}/data"

        # Upload to S3 artifacts bucket
        self.s3_service.s3_client.put_object(
            Bucket=self.s3_service.artifacts_bucket,
            Key=s3_path,
            Body=file_content,
        )

        return await self.create_knowledge_pack(
            name=name,
            version=version,
            pack_type=pack_type,
            s3_path=s3_path,
            schema_version=schema_version,
            metadata=metadata,
        )
