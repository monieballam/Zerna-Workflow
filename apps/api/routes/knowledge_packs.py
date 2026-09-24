"""KnowledgePack API routes."""

from zerna_contracts.enums import KnowledgePackType
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import get_db
from apps.api.middleware.auth import get_current_user
from apps.api.models.organization import User
from apps.api.schemas.annotation import (
    CreateKnowledgePackRequest,
    KnowledgePackResponse,
    ListKnowledgePacksResponse,
)
from apps.api.services.knowledge_pack_service import KnowledgePackService

router = APIRouter(prefix="/v1/knowledge-packs", tags=["knowledge-packs"])


async def get_kp_service(db: AsyncSession = Depends(get_db)) -> KnowledgePackService:
    return KnowledgePackService(db=db)


@router.post(
    "",
    response_model=KnowledgePackResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create knowledge pack",
)
async def create_knowledge_pack(
    request: CreateKnowledgePackRequest,
    _: User = Depends(get_current_user),
    kp_service: KnowledgePackService = Depends(get_kp_service),
) -> KnowledgePackResponse:
    try:
        pack = await kp_service.create_knowledge_pack(
            name=request.name,
            version=request.version,
            pack_type=request.pack_type,
            s3_path=request.s3_path,
            schema_version=request.schema_version,
            metadata=request.metadata,
        )
        return KnowledgePackResponse.model_validate(pack)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


@router.get(
    "",
    response_model=ListKnowledgePacksResponse,
    status_code=status.HTTP_200_OK,
    summary="List knowledge packs",
)
async def list_knowledge_packs(
    pack_type: KnowledgePackType | None = Query(None, description="Filter by pack type"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _: User = Depends(get_current_user),
    kp_service: KnowledgePackService = Depends(get_kp_service),
) -> ListKnowledgePacksResponse:
    offset = (page - 1) * page_size
    packs = await kp_service.list_knowledge_packs(
        pack_type=pack_type, limit=page_size, offset=offset
    )
    total = len(packs)
    total_pages = (total + page_size - 1) // page_size if total > 0 else 0
    return ListKnowledgePacksResponse(
        items=[KnowledgePackResponse.model_validate(p) for p in packs],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )
