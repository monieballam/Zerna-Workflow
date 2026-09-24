"""Property-based tests for persistent storage CRUD round-trip.

# Feature: gap-analysis-and-verification, Property 11: Persistent storage CRUD round-trip

**Validates: Requirements 8.1, 8.2**
"""

from uuid import UUID, uuid4

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from apps.api.models.project import DAGDefinition, Project
from apps.api.services.dag_service import DAGService
from apps.api.services.project_service import ProjectService

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_name_st = st.text(
    min_size=1,
    max_size=100,
    alphabet=st.characters(whitelist_categories=("L", "N", "Zs")),
).filter(lambda s: s.strip() != "")

_description_st = st.one_of(st.none(), st.text(min_size=0, max_size=500))

_metadata_st = st.dictionaries(
    keys=st.text(min_size=1, max_size=30, alphabet="abcdefghijklmnopqrstuvwxyz_"),
    values=st.one_of(
        st.text(min_size=0, max_size=100),
        st.integers(min_value=-1000, max_value=1000),
        st.booleans(),
    ),
    max_size=10,
)

_dag_definition_st = st.fixed_dictionaries(
    {
        "steps": st.lists(
            st.fixed_dictionaries(
                {
                    "name": st.text(
                        min_size=1, max_size=30, alphabet="abcdefghijklmnopqrstuvwxyz_"
                    ),
                    "method": st.text(
                        min_size=1, max_size=30, alphabet="abcdefghijklmnopqrstuvwxyz_"
                    ),
                }
            ),
            min_size=1,
            max_size=5,
        ),
        "dependencies": st.dictionaries(
            keys=st.text(min_size=1, max_size=30, alphabet="abcdefghijklmnopqrstuvwxyz_"),
            values=st.lists(
                st.text(min_size=1, max_size=30, alphabet="abcdefghijklmnopqrstuvwxyz_"),
                max_size=3,
            ),
            max_size=5,
        ),
    }
)


# ---------------------------------------------------------------------------
# Helpers — mock DB that simulates in-memory persistence
# ---------------------------------------------------------------------------


class InMemoryDB:
    """Simulates an async SQLAlchemy session with in-memory storage.

    Stores Project and DAGDefinition objects and supports the subset of
    operations used by ProjectService and DAGService.
    """

    def __init__(self) -> None:
        self._projects: dict[UUID, Project] = {}
        self._dags: dict[UUID, DAGDefinition] = {}

    # --- session interface ---

    def add(self, obj: object) -> None:
        if isinstance(obj, Project):
            self._projects[obj.id] = obj
        elif isinstance(obj, DAGDefinition):
            self._dags[obj.id] = obj

    async def commit(self) -> None:
        pass

    async def refresh(self, obj: object, **kwargs: object) -> None:
        pass

    async def delete(self, obj: object) -> None:
        if isinstance(obj, Project):
            self._projects.pop(obj.id, None)
            # cascade DAGs
            to_remove = [d.id for d in self._dags.values() if d.project_id == obj.id]
            for did in to_remove:
                self._dags.pop(did, None)
        elif isinstance(obj, DAGDefinition):
            self._dags.pop(obj.id, None)

    async def execute(self, stmt: object) -> "_FakeResult":
        """Route SELECT statements to in-memory stores."""
        # We inspect the compiled statement to figure out what's being queried.
        # This is a simplified mock — it inspects the statement's string repr.
        stmt_str = str(stmt)

        if "projects" in stmt_str and "dag_definitions" not in stmt_str:
            return self._execute_project_query(stmt, stmt_str)
        elif "dag_definitions" in stmt_str:
            return self._execute_dag_query(stmt, stmt_str)
        elif "count" in stmt_str.lower():
            # Count query — return count of projects
            return _FakeResult(scalar_value=len(self._projects))
        return _FakeResult(items=[])

    def _execute_project_query(self, stmt: object, stmt_str: str) -> "_FakeResult":
        items = list(self._projects.values())

        # Try to extract org_id and project_id filters from compiled params
        compiled = _try_compile(stmt)
        if compiled:
            params = compiled.get("params", {})
            # Filter by org_id
            org_vals = [v for k, v in params.items() if "organization_id" in k]
            if org_vals:
                items = [p for p in items if p.organization_id == org_vals[0]]
            # Filter by project id
            id_vals = [
                v
                for k, v in params.items()
                if k.endswith("_1") or "id" in k and "organization" not in k
            ]
            # Heuristic: if there's a UUID param that matches a project id
            for v in params.values():
                if isinstance(v, UUID) and v in self._projects and v not in org_vals:
                    items = [p for p in items if p.id == v]
                    break

        # Attach empty dag_definitions list for selectinload simulation
        for p in items:
            if not hasattr(p, "dag_definitions") or p.dag_definitions is None:
                p.dag_definitions = [d for d in self._dags.values() if d.project_id == p.id]

        if "count" in stmt_str.lower():
            return _FakeResult(scalar_value=len(items))

        return _FakeResult(items=items)

    def _execute_dag_query(self, stmt: object, stmt_str: str) -> "_FakeResult":
        items = list(self._dags.values())

        compiled = _try_compile(stmt)
        if compiled:
            params = compiled.get("params", {})
            org_vals = [v for k, v in params.items() if "organization_id" in k]
            proj_vals = [v for k, v in params.items() if "project_id" in k]
            name_vals = [v for k, v in params.items() if "name" in k]

            if org_vals:
                items = [d for d in items if d.organization_id == org_vals[0]]
            if proj_vals:
                items = [d for d in items if d.project_id == proj_vals[0]]
            if name_vals:
                items = [d for d in items if d.name == name_vals[0]]

            # Check for specific DAG id
            for v in params.values():
                if isinstance(v, UUID) and v in self._dags:
                    if v not in (org_vals + proj_vals if org_vals and proj_vals else []):
                        items = [d for d in items if d.id == v]
                        break

        # Sort by version desc (matches service queries)
        items.sort(key=lambda d: d.version, reverse=True)

        # Handle LIMIT 1 (for get_latest_dag)
        if "LIMIT" in stmt_str.upper() or "limit" in stmt_str:
            items = items[:1]

        if "max" in stmt_str.lower() and "group" in stmt_str.lower():
            # latest_only subquery — return latest per name
            latest: dict[str, DAGDefinition] = {}
            for d in items:
                if d.name not in latest or d.version > latest[d.name].version:
                    latest[d.name] = d
            items = list(latest.values())

        return _FakeResult(items=items)


def _try_compile(stmt: object) -> dict | None:
    """Try to extract bound parameters from a SQLAlchemy statement."""
    try:
        from sqlalchemy.dialects import sqlite

        compiled = stmt.compile(dialect=sqlite.dialect(), compile_kwargs={"literal_binds": False})  # type: ignore[union-attr]
        return {"params": compiled.params}
    except Exception:
        return None


class _FakeResult:
    """Mimics SQLAlchemy Result for scalar_one_or_none / scalars().all()."""

    def __init__(
        self,
        items: list | None = None,
        scalar_value: object = None,
    ) -> None:
        self._items = items or []
        self._scalar_value = scalar_value

    def scalar_one_or_none(self) -> object:
        if self._scalar_value is not None:
            return self._scalar_value
        return self._items[0] if self._items else None

    def scalar_one(self) -> object:
        if self._scalar_value is not None:
            return self._scalar_value
        return self._items[0]

    def scalars(self) -> "_FakeScalars":
        return _FakeScalars(self._items)

    def unique(self) -> "_FakeResult":
        return self


class _FakeScalars:
    def __init__(self, items: list) -> None:
        self._items = items

    def all(self) -> list:
        return self._items


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------


class TestProjectCRUDRoundTrip:
    """Property 11 (part 1): For any project created via the API, reading it
    back must return the same data.

    **Validates: Requirements 8.1**
    """

    @pytest.mark.asyncio
    @given(
        name=_name_st,
        description=_description_st,
        metadata=_metadata_st,
    )
    @settings(
        max_examples=100,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    async def test_project_create_read_roundtrip(
        self,
        name: str,
        description: str | None,
        metadata: dict,
    ) -> None:
        """Creating a project and reading it back returns the same data.

        **Validates: Requirements 8.1**
        """
        db = InMemoryDB()
        svc = ProjectService(db=db)  # type: ignore[arg-type]

        org_id = uuid4()
        user_id = uuid4()

        created = await svc.create_project(
            org_id=org_id,
            name=name,
            description=description,
            metadata=metadata,
            created_by=user_id,
        )

        # Read back
        fetched = await svc.get_project(created.id, org_id)

        assert fetched is not None
        assert fetched.id == created.id
        assert fetched.name == name
        assert fetched.description == description
        assert fetched.extra_metadata == metadata
        assert fetched.organization_id == org_id
        assert fetched.created_by == user_id

    @pytest.mark.asyncio
    @given(
        name=_name_st,
        description=_description_st,
        metadata=_metadata_st,
    )
    @settings(
        max_examples=100,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    async def test_project_delete_removes_from_storage(
        self,
        name: str,
        description: str | None,
        metadata: dict,
    ) -> None:
        """Deleting a project means it can no longer be read back.

        **Validates: Requirements 8.1**
        """
        db = InMemoryDB()
        svc = ProjectService(db=db)  # type: ignore[arg-type]

        org_id = uuid4()

        created = await svc.create_project(
            org_id=org_id,
            name=name,
            description=description,
            metadata=metadata,
        )

        deleted = await svc.delete_project(created.id, org_id)
        assert deleted is True

        fetched = await svc.get_project(created.id, org_id)
        assert fetched is None


class TestDAGDefinitionCRUDRoundTrip:
    """Property 11 (part 2): For any DAG definition created via the API,
    reading it back must return the same data. Version history must be
    preserved across updates.

    **Validates: Requirements 8.2**
    """

    @pytest.mark.asyncio
    @given(
        dag_name=_name_st,
        definition=_dag_definition_st,
        description=_description_st,
    )
    @settings(
        max_examples=100,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    async def test_dag_create_read_roundtrip(
        self,
        dag_name: str,
        definition: dict,
        description: str | None,
    ) -> None:
        """Creating a DAG and reading it back returns the same data.

        **Validates: Requirements 8.2**
        """
        db = InMemoryDB()
        proj_svc = ProjectService(db=db)  # type: ignore[arg-type]
        dag_svc = DAGService(db=db)  # type: ignore[arg-type]

        org_id = uuid4()
        user_id = uuid4()

        # Create a project first
        project = await proj_svc.create_project(
            org_id=org_id,
            name="test-project",
        )

        created = await dag_svc.create_dag(
            org_id=org_id,
            project_id=project.id,
            name=dag_name,
            definition=definition,
            description=description,
            created_by=user_id,
        )

        assert created.version == 1

        # Read back
        fetched = await dag_svc.get_dag(created.id, org_id)

        assert fetched is not None
        assert fetched.id == created.id
        assert fetched.name == dag_name
        assert fetched.definition == definition
        assert fetched.description == description
        assert fetched.version == 1
        assert fetched.project_id == project.id
        assert fetched.organization_id == org_id

    @pytest.mark.asyncio
    @given(
        dag_name=_name_st,
        def_v1=_dag_definition_st,
        def_v2=_dag_definition_st,
        def_v3=_dag_definition_st,
    )
    @settings(
        max_examples=100,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    async def test_dag_version_history_preserved(
        self,
        dag_name: str,
        def_v1: dict,
        def_v2: dict,
        def_v3: dict,
    ) -> None:
        """Updating a DAG creates new versions and all versions are preserved.

        **Validates: Requirements 8.2**
        """
        db = InMemoryDB()
        proj_svc = ProjectService(db=db)  # type: ignore[arg-type]
        dag_svc = DAGService(db=db)  # type: ignore[arg-type]

        org_id = uuid4()

        project = await proj_svc.create_project(
            org_id=org_id,
            name="test-project",
        )

        # Create v1
        v1 = await dag_svc.create_dag(
            org_id=org_id,
            project_id=project.id,
            name=dag_name,
            definition=def_v1,
        )
        assert v1.version == 1

        # Update to v2
        v2 = await dag_svc.update_dag(
            org_id=org_id,
            project_id=project.id,
            name=dag_name,
            definition=def_v2,
        )
        assert v2.version == 2

        # Update to v3
        v3 = await dag_svc.update_dag(
            org_id=org_id,
            project_id=project.id,
            name=dag_name,
            definition=def_v3,
        )
        assert v3.version == 3

        # All versions must be retrievable
        history = await dag_svc.get_dag_version_history(org_id, project.id, dag_name)
        assert len(history) == 3

        # Versions are ordered newest-first
        assert history[0].version == 3
        assert history[1].version == 2
        assert history[2].version == 1

        # Each version preserves its definition
        assert history[0].definition == def_v3
        assert history[1].definition == def_v2
        assert history[2].definition == def_v1

        # Latest DAG should be v3
        latest = await dag_svc.get_latest_dag(org_id, project.id, dag_name)
        assert latest is not None
        assert latest.version == 3
        assert latest.definition == def_v3
