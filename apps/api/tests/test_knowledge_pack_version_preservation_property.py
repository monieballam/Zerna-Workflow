"""Property-based tests for knowledge pack version preservation.

**Validates: Requirements 6.3**
"""

from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from zerna_contracts.enums import KnowledgePackType
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from apps.api.models import Base
from apps.api.services.knowledge_pack_service import KnowledgePackService


@pytest_asyncio.fixture(scope="module")
async def async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


async def get_clean_session(engine):
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        for table in reversed(Base.metadata.sorted_tables):
            await session.execute(delete(table))
        await session.commit()
        return session


def _mock_s3():
    s3 = MagicMock()
    s3.artifacts_bucket = "test-bucket"
    return s3


# ── Strategies ─────────────────────────────────────────────────────────────────

safe_text = st.text(
    min_size=1,
    max_size=20,
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="-_"),
)
version_str = st.text(
    min_size=1,
    max_size=10,
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="."),
)
pack_type_st = st.sampled_from(list(KnowledgePackType))


@pytest.mark.property
class TestKnowledgePackVersionPreservation:
    """Property 17: Knowledge Pack Version Preservation

    For any knowledge pack update, all previous versions should remain accessible
    and unchanged in storage.
    """

    @pytest.mark.asyncio
    @given(
        name=safe_text,
        versions=st.lists(version_str, min_size=2, max_size=5, unique=True),
        pack_type=pack_type_st,
    )
    @settings(max_examples=100)
    async def test_multiple_versions_all_preserved(self, async_engine, name, versions, pack_type):
        """Property: creating multiple versions of the same name preserves all versions.

        **Validates: Requirements 6.3**
        """
        session = await get_clean_session(async_engine)
        svc = KnowledgePackService(db=session, s3_service=_mock_s3())

        created_ids = []
        for v in versions:
            pack = await svc.create_knowledge_pack(
                name=name,
                version=v,
                pack_type=pack_type,
                s3_path=f"knowledge-packs/{name}/{v}/data",
            )
            created_ids.append(pack.id)

        # All versions must still be retrievable
        for pack_id in created_ids:
            retrieved = await svc.get_knowledge_pack(pack_id)
            assert retrieved is not None, f"Pack {pack_id} should still exist"

        await session.close()

    @pytest.mark.asyncio
    @given(name=safe_text, version=version_str, pack_type=pack_type_st)
    @settings(max_examples=100)
    async def test_duplicate_name_version_raises_value_error(
        self, async_engine, name, version, pack_type
    ):
        """Property: attempting to create a duplicate (same name+version) raises ValueError.

        **Validates: Requirements 6.3**
        """
        session = await get_clean_session(async_engine)
        svc = KnowledgePackService(db=session, s3_service=_mock_s3())

        await svc.create_knowledge_pack(
            name=name,
            version=version,
            pack_type=pack_type,
            s3_path=f"knowledge-packs/{name}/{version}/data",
        )

        with pytest.raises(ValueError, match="already exists"):
            await svc.create_knowledge_pack(
                name=name,
                version=version,
                pack_type=pack_type,
                s3_path=f"knowledge-packs/{name}/{version}/data-duplicate",
            )

        await session.close()

    @pytest.mark.asyncio
    @given(
        name=safe_text,
        versions=st.lists(version_str, min_size=2, max_size=5, unique=True),
        pack_type=pack_type_st,
    )
    @settings(max_examples=100)
    async def test_list_returns_all_versions(self, async_engine, name, versions, pack_type):
        """Property: listing knowledge packs returns all versions.

        **Validates: Requirements 6.3**
        """
        session = await get_clean_session(async_engine)
        svc = KnowledgePackService(db=session, s3_service=_mock_s3())

        for v in versions:
            await svc.create_knowledge_pack(
                name=name,
                version=v,
                pack_type=pack_type,
                s3_path=f"knowledge-packs/{name}/{v}/data",
            )

        all_packs = await svc.list_knowledge_packs(pack_type=pack_type, limit=100)
        listed_versions = {p.version for p in all_packs if p.name == name}
        assert set(versions) == listed_versions, (
            f"All versions {versions} should appear in listing, got {listed_versions}"
        )

        await session.close()

    @pytest.mark.asyncio
    @given(
        name=safe_text,
        versions=st.lists(version_str, min_size=2, max_size=4, unique=True),
        pack_type=pack_type_st,
    )
    @settings(max_examples=100)
    async def test_each_version_data_unchanged_after_newer_versions_created(
        self, async_engine, name, versions, pack_type
    ):
        """Property: each version's data is unchanged after creating newer versions.

        **Validates: Requirements 6.3**
        """
        session = await get_clean_session(async_engine)
        svc = KnowledgePackService(db=session, s3_service=_mock_s3())

        # Create all versions and record their s3_paths
        created = {}
        for v in versions:
            s3_path = f"knowledge-packs/{name}/{v}/data"
            pack = await svc.create_knowledge_pack(
                name=name,
                version=v,
                pack_type=pack_type,
                s3_path=s3_path,
            )
            created[pack.id] = {"version": v, "s3_path": s3_path, "pack_type": pack_type}

        # Verify each version's data is unchanged
        for pack_id, expected in created.items():
            pack = await svc.get_knowledge_pack(pack_id)
            assert pack is not None
            assert pack.version == expected["version"]
            assert pack.s3_path == expected["s3_path"]
            assert pack.pack_type == expected["pack_type"]

        await session.close()
