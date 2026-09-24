# Run Execution Workflow Implementation Notes

## Overview

This document describes the implementation of the RunExecutionWorkflow activities for task 7.3.

## Activities Implemented

### 1. resolve_template

**Purpose**: Resolve pipeline template and validate parameters before execution.

**Implementation**:

- Fetches the Run record from the database to get organization context
- Retrieves the PipelineTemplate and verifies it belongs to the organization
- Validates run parameters against the template's parameter schema using PipelineService
- Resolves all methods in the template to ensure they exist in the method registry
- Returns template details including definition and method list

**Error Handling**:

- Returns `valid: False` with error message if run not found
- Returns `valid: False` if template not found or doesn't belong to organization
- Returns `valid: False` if parameter validation fails
- Returns `valid: False` if method resolution fails (nonexistent methods)

**Integration Points**:

- Uses `PipelineService` for parameter validation and method resolution
- Queries `Run` and `PipelineTemplate` models from database
- Validates against known method registry (qc_filter, normalize, cluster, etc.)

### 2. invoke_nextflow

**Purpose**: Invoke Nextflow to execute the pipeline DAG.

**Current Implementation**: Placeholder

- Verifies dataset version exists
- Updates run status to RUNNING and sets started_at timestamp
- Returns placeholder success response with output path
- Returns placeholder software versions

**Future Implementation** (Task 12):

- Generate Nextflow script from template definition
- Prepare input data from dataset_version.s3_path
- Execute Nextflow with proper resource allocation
- Monitor execution progress
- Handle retries for transient errors (network issues, temporary service unavailability)
- Capture stdout/stderr for debugging
- Emit progress events to Control Plane

**Retry Logic**:
The workflow configures a retry policy for this activity:

- Initial interval: 1 second
- Maximum interval: 60 seconds
- Backoff coefficient: 2.0 (exponential backoff)
- Maximum attempts: 5

This handles transient Nextflow communication errors as specified in the requirements.

### 3. collect_artifacts

**Purpose**: Collect generated artifacts and store in S3.

**Current Implementation**: Placeholder

- Creates placeholder Artifact records in the database:
  - H5AD file (processed.h5ad)
  - Embedding plot (umap.png)
  - QC report (qc_report.html)
- Updates run with software versions
- Returns list of artifact IDs

**Future Implementation** (Task 12+):

- Scan Nextflow output directory for artifacts
- Identify artifact types (h5ad, plots, reports, DE results, pathway scores, etc.)
- Upload artifacts to S3 with organization-scoped paths
- Extract artifact sizes and checksums
- Create Artifact records with complete metadata
- Link artifacts to the run

### 4. cleanup_run_resources

**Purpose**: Cleanup resources for failed or cancelled runs (compensation logic).

**Implementation**:

- Deletes partial artifacts from database
- Updates run status to FAILED if still in RUNNING state
- Sets completed_at timestamp
- Sets error message if not already set
- Best-effort cleanup (doesn't raise exceptions)

**Future Enhancements**:

- Delete S3 files for partial artifacts
- Cancel running Nextflow processes
- Clean up temporary compute resources

## Workflow Integration

The RunExecutionWorkflow orchestrates these activities:

1. **resolve_template**: Validates template and parameters
   - Timeout: 60 seconds
   - Retry policy: exponential backoff, max 5 attempts
   - On failure: returns FAILED status with error message

2. **invoke_nextflow**: Executes the pipeline
   - Timeout: 3600 seconds (1 hour)
   - Retry policy: exponential backoff, max 5 attempts
   - On failure: triggers compensation and returns FAILED status

3. **collect_artifacts**: Collects outputs
   - Timeout: 300 seconds (5 minutes)
   - Retry policy: exponential backoff, max 5 attempts
   - On failure: triggers compensation and returns FAILED status

4. **cleanup_run_resources**: Compensation on failure
   - Timeout: 60 seconds
   - Retry policy: max 3 attempts
   - Called when any step fails to clean up partial resources

## Requirements Validation

This implementation validates the following requirements:

- **Requirement 4.1**: Control Plane creates Temporal workflow for run execution ✓
- **Requirement 4.2**: Temporal workflow translates PipelineTemplate into Nextflow DAG (placeholder) ✓
- **Requirement 13.3**: Temporal workflows communicate with Nextflow via API calls (placeholder) ✓
- **Requirement 13.4**: Temporal workflows handle retries and compensation logic ✓

## Testing Strategy

### Unit Testing

Due to Temporal's activity context requirements, unit tests for activities need to be run within a Temporal test environment or through integration tests. The activities are designed to be testable by:

- Using dependency injection (database session from async_session_factory)
- Clear input/output contracts via dictionaries
- Comprehensive error handling with descriptive messages

### Integration Testing

- Test through the complete workflow execution
- Verify activity registration in the worker
- Test retry behavior with transient failures
- Test compensation logic with intentional failures

### Manual Testing

1. Start Temporal server and worker
2. Create a run via API
3. Verify workflow execution in Temporal UI
4. Check run status updates in database
5. Verify artifact creation

## Future Work

### Task 12: Nextflow Integration

- Implement actual Nextflow script generation from template definition
- Set up Nextflow executor configuration
- Implement progress event emission
- Add proper error capture and reporting
- Implement artifact scanning and collection

### Task 13+: Artifact Management

- Implement S3 upload for artifacts
- Add artifact metadata extraction (size, checksum, type-specific metadata)
- Implement pre-signed URL generation for downloads
- Add artifact versioning and retention policies

### Observability

- Add OpenTelemetry tracing to activities
- Emit metrics for activity duration
- Log structured events for debugging
- Add activity-level error classification

## Notes

- The `activity.unsafe.imports_passed_through()` context manager was removed as it's not available in Temporal SDK 1.23.0
- Activities import dependencies directly, which works fine when running in the worker context
- The placeholder implementations allow the workflow to be registered and tested end-to-end
- Retry policies are configured at the workflow level for each activity invocation
- Compensation logic ensures resources are cleaned up even if cleanup partially fails
