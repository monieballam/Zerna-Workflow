"""Property-based tests for organization-scoped storage paths.

**Validates: Requirements 2.5, 11.2**
"""

from uuid import uuid4

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from apps.api.config import Settings
from apps.api.services.s3_service import S3Service


def create_s3_service():
    """Create S3Service with mock settings for testing."""
    from unittest.mock import MagicMock, patch

    mock_settings = Settings(
        database_url="postgresql://test",
        redis_url="redis://test",
        jwt_secret_key="test-secret",
        s3_access_key_id="test-access-key",
        s3_secret_access_key="test-secret-key",
        s3_region="us-east-1",
        s3_datasets_bucket="test-datasets",
        s3_artifacts_bucket="test-artifacts",
        s3_endpoint_url="http://localhost:9000",
    )

    with patch("apps.api.services.s3_service.boto3.client") as mock_boto:
        mock_client = MagicMock()
        mock_boto.return_value = mock_client
        service = S3Service(mock_settings)
        service.s3_client = mock_client
        return service


# Hypothesis strategies for generating test data
def uuid_strategy():
    """Generate valid UUIDs."""
    return st.builds(lambda: uuid4())


def filename_strategy():
    """Generate valid filenames."""
    return st.text(
        alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="-_."),
        min_size=1,
        max_size=50,
    ).filter(lambda s: s and not s.startswith(".") and not s.endswith("."))


def artifact_type_strategy():
    """Generate valid artifact types."""
    return st.sampled_from(
        ["h5ad", "embedding_plot", "qc_report", "de_results", "pathway_scores", "liana_results"]
    )


@pytest.mark.property
class TestOrganizationScopedStoragePaths:
    """Property 7: Organization-Scoped Storage Paths

    For any artifact or dataset file stored in S3, the path should begin with
    the organization ID prefix, ensuring storage isolation.
    """

    @given(
        org_id=uuid_strategy(),
        dataset_id=uuid_strategy(),
        filename=filename_strategy(),
    )
    def test_dataset_path_starts_with_org_id(self, org_id, dataset_id, filename):
        """Property: All dataset paths must start with organization ID."""
        s3_service = create_s3_service()
        path = s3_service.generate_dataset_path(org_id, dataset_id, filename)

        # Path must start with organization ID
        assert path.startswith(str(org_id)), (
            f"Dataset path '{path}' does not start with org_id '{org_id}'"
        )

        # Path must contain the expected structure
        assert f"{org_id}/datasets/{dataset_id}/{filename}" == path, (
            f"Dataset path '{path}' does not match expected format"
        )

    @given(
        org_id=uuid_strategy(),
        run_id=uuid_strategy(),
        artifact_type=artifact_type_strategy(),
        filename=filename_strategy(),
    )
    def test_artifact_path_starts_with_org_id(self, org_id, run_id, artifact_type, filename):
        """Property: All artifact paths must start with organization ID."""
        s3_service = create_s3_service()
        path = s3_service.generate_artifact_path(org_id, run_id, artifact_type, filename)

        # Path must start with organization ID
        assert path.startswith(str(org_id)), (
            f"Artifact path '{path}' does not start with org_id '{org_id}'"
        )

        # Path must contain the expected structure
        assert f"{org_id}/runs/{run_id}/{artifact_type}/{filename}" == path, (
            f"Artifact path '{path}' does not match expected format"
        )

    @given(
        org_id_1=uuid_strategy(),
        org_id_2=uuid_strategy(),
        dataset_id=uuid_strategy(),
        filename=filename_strategy(),
    )
    def test_different_orgs_have_non_overlapping_dataset_paths(
        self, org_id_1, org_id_2, dataset_id, filename
    ):
        """Property: Paths from different organizations never overlap."""
        assume(org_id_1 != org_id_2)

        s3_service = create_s3_service()
        path_1 = s3_service.generate_dataset_path(org_id_1, dataset_id, filename)
        path_2 = s3_service.generate_dataset_path(org_id_2, dataset_id, filename)

        # Paths must be different
        assert path_1 != path_2, f"Different organizations generated same path: '{path_1}'"

        # Path 1 must not be a prefix of path 2 and vice versa
        assert not path_1.startswith(path_2) and not path_2.startswith(path_1), (
            f"Paths overlap: '{path_1}' and '{path_2}'"
        )

        # Each path must contain its respective org_id
        assert str(org_id_1) in path_1 and str(org_id_1) not in path_2, (
            f"Path 1 '{path_1}' does not properly isolate org_id_1 '{org_id_1}'"
        )
        assert str(org_id_2) in path_2 and str(org_id_2) not in path_1, (
            f"Path 2 '{path_2}' does not properly isolate org_id_2 '{org_id_2}'"
        )

    @given(
        org_id_1=uuid_strategy(),
        org_id_2=uuid_strategy(),
        run_id=uuid_strategy(),
        artifact_type=artifact_type_strategy(),
        filename=filename_strategy(),
    )
    def test_different_orgs_have_non_overlapping_artifact_paths(
        self, org_id_1, org_id_2, run_id, artifact_type, filename
    ):
        """Property: Artifact paths from different organizations never overlap."""
        assume(org_id_1 != org_id_2)

        s3_service = create_s3_service()
        path_1 = s3_service.generate_artifact_path(org_id_1, run_id, artifact_type, filename)
        path_2 = s3_service.generate_artifact_path(org_id_2, run_id, artifact_type, filename)

        # Paths must be different
        assert path_1 != path_2, f"Different organizations generated same artifact path: '{path_1}'"

        # Path 1 must not be a prefix of path 2 and vice versa
        assert not path_1.startswith(path_2) and not path_2.startswith(path_1), (
            f"Artifact paths overlap: '{path_1}' and '{path_2}'"
        )

        # Each path must contain its respective org_id
        assert str(org_id_1) in path_1 and str(org_id_1) not in path_2, (
            f"Artifact path 1 '{path_1}' does not properly isolate org_id_1 '{org_id_1}'"
        )
        assert str(org_id_2) in path_2 and str(org_id_2) not in path_1, (
            f"Artifact path 2 '{path_2}' does not properly isolate org_id_2 '{org_id_2}'"
        )

    @given(
        org_id=uuid_strategy(),
        dataset_id=uuid_strategy(),
        filename=filename_strategy(),
    )
    def test_dataset_path_format_consistency(self, org_id, dataset_id, filename):
        """Property: Dataset paths follow consistent format with org_id/datasets/dataset_id/filename."""
        s3_service = create_s3_service()
        path = s3_service.generate_dataset_path(org_id, dataset_id, filename)

        # Split path and verify structure
        parts = path.split("/")

        assert len(parts) == 4, (
            f"Dataset path '{path}' does not have 4 parts (org_id/datasets/dataset_id/filename)"
        )

        assert parts[0] == str(org_id), f"First part of path '{parts[0]}' is not org_id '{org_id}'"

        assert parts[1] == "datasets", f"Second part of path '{parts[1]}' is not 'datasets'"

        assert parts[2] == str(dataset_id), (
            f"Third part of path '{parts[2]}' is not dataset_id '{dataset_id}'"
        )

        assert parts[3] == filename, (
            f"Fourth part of path '{parts[3]}' is not filename '{filename}'"
        )

    @given(
        org_id=uuid_strategy(),
        run_id=uuid_strategy(),
        artifact_type=artifact_type_strategy(),
        filename=filename_strategy(),
    )
    def test_artifact_path_format_consistency(self, org_id, run_id, artifact_type, filename):
        """Property: Artifact paths follow consistent format with org_id/runs/run_id/artifact_type/filename."""
        s3_service = create_s3_service()
        path = s3_service.generate_artifact_path(org_id, run_id, artifact_type, filename)

        # Split path and verify structure
        parts = path.split("/")

        assert len(parts) == 5, (
            f"Artifact path '{path}' does not have 5 parts (org_id/runs/run_id/artifact_type/filename)"
        )

        assert parts[0] == str(org_id), f"First part of path '{parts[0]}' is not org_id '{org_id}'"

        assert parts[1] == "runs", f"Second part of path '{parts[1]}' is not 'runs'"

        assert parts[2] == str(run_id), f"Third part of path '{parts[2]}' is not run_id '{run_id}'"

        assert parts[3] == artifact_type, (
            f"Fourth part of path '{parts[3]}' is not artifact_type '{artifact_type}'"
        )

        assert parts[4] == filename, f"Fifth part of path '{parts[4]}' is not filename '{filename}'"

    @given(
        org_id=uuid_strategy(),
        dataset_id=uuid_strategy(),
        filename=filename_strategy(),
    )
    def test_presigned_upload_url_maintains_org_scoping(self, org_id, dataset_id, filename):
        """Property: Pre-signed upload URLs maintain organization scoping in the S3 path."""
        from unittest.mock import MagicMock

        s3_service = create_s3_service()
        # Generate organization-scoped path
        s3_path = s3_service.generate_dataset_path(org_id, dataset_id, filename)
        bucket = s3_service.datasets_bucket

        # Mock the presigned URL generation
        expected_url = f"https://s3.amazonaws.com/{bucket}/{s3_path}?signature=test"
        s3_service.s3_client.generate_presigned_url = MagicMock(return_value=expected_url)

        # Generate presigned URL
        url = s3_service.generate_presigned_upload_url(bucket, s3_path)

        # Verify the URL was generated with the correct path
        s3_service.s3_client.generate_presigned_url.assert_called_once()
        call_args = s3_service.s3_client.generate_presigned_url.call_args

        # Check that the Key parameter contains the org-scoped path
        assert call_args[1]["Params"]["Key"] == s3_path, (
            f"Presigned URL Key '{call_args[1]['Params']['Key']}' does not match org-scoped path '{s3_path}'"
        )

        # Verify the path in the Key starts with org_id
        assert call_args[1]["Params"]["Key"].startswith(str(org_id)), (
            f"Presigned URL Key does not start with org_id '{org_id}'"
        )

    @given(
        org_id=uuid_strategy(),
        run_id=uuid_strategy(),
        artifact_type=artifact_type_strategy(),
        filename=filename_strategy(),
    )
    def test_presigned_download_url_maintains_org_scoping(
        self, org_id, run_id, artifact_type, filename
    ):
        """Property: Pre-signed download URLs maintain organization scoping in the S3 path."""
        from unittest.mock import MagicMock

        s3_service = create_s3_service()
        # Generate organization-scoped path
        s3_path = s3_service.generate_artifact_path(org_id, run_id, artifact_type, filename)
        bucket = s3_service.artifacts_bucket

        # Mock the presigned URL generation
        expected_url = f"https://s3.amazonaws.com/{bucket}/{s3_path}?signature=test"
        s3_service.s3_client.generate_presigned_url = MagicMock(return_value=expected_url)

        # Generate presigned URL
        url = s3_service.generate_presigned_download_url(bucket, s3_path)

        # Verify the URL was generated with the correct path
        s3_service.s3_client.generate_presigned_url.assert_called_once()
        call_args = s3_service.s3_client.generate_presigned_url.call_args

        # Check that the Key parameter contains the org-scoped path
        assert call_args[1]["Params"]["Key"] == s3_path, (
            f"Presigned URL Key '{call_args[1]['Params']['Key']}' does not match org-scoped path '{s3_path}'"
        )

        # Verify the path in the Key starts with org_id
        assert call_args[1]["Params"]["Key"].startswith(str(org_id)), (
            f"Presigned URL Key does not start with org_id '{org_id}'"
        )

    @given(
        num_orgs=st.integers(min_value=2, max_value=10),
        num_datasets_per_org=st.integers(min_value=1, max_value=5),
        data=st.data(),
    )
    def test_multiple_orgs_paths_never_collide(self, num_orgs, num_datasets_per_org, data):
        """Property: Paths from multiple organizations never collide, even with many datasets."""
        s3_service = create_s3_service()
        # Generate multiple organizations
        org_ids = [data.draw(uuid_strategy()) for _ in range(num_orgs)]

        # Ensure all org_ids are unique
        assume(len(set(org_ids)) == num_orgs)

        # Generate paths for each organization
        all_paths = set()
        org_paths = {}

        for org_id in org_ids:
            org_paths[org_id] = set()
            for _ in range(num_datasets_per_org):
                dataset_id = data.draw(uuid_strategy())
                filename = data.draw(filename_strategy())
                path = s3_service.generate_dataset_path(org_id, dataset_id, filename)

                # Verify path starts with org_id
                assert path.startswith(str(org_id)), (
                    f"Path '{path}' does not start with org_id '{org_id}'"
                )

                # Add to org-specific paths
                org_paths[org_id].add(path)

                # Check for collisions with other organizations
                assert path not in all_paths, f"Path collision detected: '{path}' already exists"

                all_paths.add(path)

        # Verify no path from one org is a prefix of a path from another org
        for org_id_1 in org_ids:
            for org_id_2 in org_ids:
                if org_id_1 != org_id_2:
                    for path_1 in org_paths[org_id_1]:
                        for path_2 in org_paths[org_id_2]:
                            assert not path_1.startswith(path_2) and not path_2.startswith(
                                path_1
                            ), f"Path overlap detected between orgs: '{path_1}' and '{path_2}'"

    @given(
        org_id=uuid_strategy(),
        num_resources=st.integers(min_value=5, max_value=20),
        data=st.data(),
    )
    def test_all_paths_for_org_share_common_prefix(self, org_id, num_resources, data):
        """Property: All paths for a given organization share the organization ID as a common prefix."""
        s3_service = create_s3_service()
        paths = []

        # Generate mixed dataset and artifact paths
        for _ in range(num_resources):
            if data.draw(st.booleans()):
                # Generate dataset path
                dataset_id = data.draw(uuid_strategy())
                filename = data.draw(filename_strategy())
                path = s3_service.generate_dataset_path(org_id, dataset_id, filename)
            else:
                # Generate artifact path
                run_id = data.draw(uuid_strategy())
                artifact_type = data.draw(artifact_type_strategy())
                filename = data.draw(filename_strategy())
                path = s3_service.generate_artifact_path(org_id, run_id, artifact_type, filename)

            paths.append(path)

        # All paths must start with the organization ID
        common_prefix = str(org_id)
        for path in paths:
            assert path.startswith(common_prefix), (
                f"Path '{path}' does not start with common org prefix '{common_prefix}'"
            )

        # Verify the common prefix is exactly the org_id (not a substring)
        for path in paths:
            first_part = path.split("/")[0]
            assert first_part == str(org_id), (
                f"First path component '{first_part}' is not exactly org_id '{org_id}'"
            )
