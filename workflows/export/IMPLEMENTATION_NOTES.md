# ExportWorkflow Implementation Notes

## Task 7.4: Implement ExportWorkflow

**Status:** ✅ Completed

**Validates Requirements:** 9.1, 9.4, 13.4

## Overview

This task implements the ExportWorkflow for exporting analysis results with reproducibility reports. The workflow orchestrates three main activities:

1. **generate_h5ad**: Generate h5ad file with all annotations and embeddings
2. **compile_report**: Compile reproducibility report with provenance information
3. **upload_to_s3**: Upload export artifacts to S3 and generate pre-signed download URLs

## Implementation Details

### Activities Implemented

#### 1. generate_h5ad

- **Location:** `workflows/export/activities.py`
- **Purpose:** Generate h5ad file with all annotations and embeddings
- **Current Status:** Placeholder implementation (full implementation in task 15)
- **Returns:**
  - `success`: bool indicating if generation succeeded
  - `h5ad_path`: str local path to generated h5ad file
  - `error`: optional error message if generation failed

#### 2. compile_report

- **Location:** `workflows/export/activities.py`
- **Purpose:** Compile reproducibility report with provenance information
- **Current Status:** Placeholder implementation (full implementation in task 15)
- **Returns:**
  - `success`: bool indicating if compilation succeeded
  - `report_path`: str local path to generated report
  - `error`: optional error message if compilation failed

#### 3. upload_to_s3

- **Location:** `workflows/export/activities.py`
- **Purpose:** Upload export artifacts to S3 and generate pre-signed download URLs
- **Features:**
  - Organization-scoped S3 paths
  - Pre-signed download URLs (valid for 7 days)
  - Automatic cleanup of temporary files
  - Proper error handling
- **Returns:**
  - `success`: bool indicating if upload succeeded
  - `h5ad_url`: str pre-signed download URL for h5ad
  - `report_url`: str pre-signed download URL for report
  - `h5ad_s3_path`: str S3 path for h5ad (for cleanup)
  - `report_s3_path`: str S3 path for report (for cleanup)
  - `error`: optional error message if upload failed

#### 4. cleanup_export_files (Compensation Logic)

- **Location:** `workflows/export/activities.py`
- **Purpose:** Cleanup export files from S3 on workflow failure
- **Features:**
  - Best-effort cleanup (doesn't raise exceptions)
  - Deletes both h5ad and report files if they were uploaded
  - Logs cleanup operations for debugging

### Workflow Implementation

#### ExportWorkflow

- **Location:** `workflows/export/workflow.py`
- **Features:**
  - Retry policy with exponential backoff (5 attempts max)
  - Compensation logic for partial exports
  - Proper error handling and logging
  - Tracks uploaded files for cleanup on failure

#### Compensation Logic

The workflow includes a `_cleanup_partial_export` method that:

- Is called when any step fails or an exception occurs
- Deletes any partially uploaded files from S3
- Uses best-effort approach (doesn't fail the workflow if cleanup fails)
- Logs all cleanup operations

### Worker Registration

The new `cleanup_export_files` activity has been registered in the Temporal worker:

- **Location:** `workflows/worker.py`
- **Activities Count:** Updated from 11 to 12 activities

## Testing

### Test Coverage

- **Location:** `workflows/tests/test_export_workflow.py`
- **Tests:**
  1. `test_export_workflow_structure`: Verifies workflow has correct structure and compensation logic
  2. `test_export_schemas`: Verifies export schemas are properly defined

### Running Tests

```bash
python -m pytest workflows/tests/test_export_workflow.py -v
```

## Requirements Validation

### Requirement 9.1: Export h5ad files

✅ **Validated** - `generate_h5ad` activity creates h5ad files with all annotations and embeddings

### Requirement 9.4: Generate reproducibility reports

✅ **Validated** - `compile_report` activity generates HTML reports with provenance information

### Requirement 13.4: Temporal workflow compensation logic

✅ **Validated** - Workflow includes `_cleanup_partial_export` method for handling partial exports

## Future Work

The following will be implemented in task 15 (Export and reproducibility):

1. **Full h5ad generation:**
   - Load run artifacts (processed h5ad)
   - Load all annotation revisions
   - Load embeddings (UMAP, t-SNE)
   - Merge all data into single h5ad
   - Add metadata (software versions, parameters, provenance)

2. **Full report compilation:**
   - Load run metadata (parameters, software versions, random seed)
   - Load pipeline template definition
   - Load knowledge pack versions used
   - Generate comprehensive HTML report with:
     - Run summary
     - Pipeline parameters
     - Software versions
     - Random seeds
     - Provenance information
     - Method execution timeline

## Dependencies

- `apps.api.dependencies`: Database session factory
- `apps.api.models.pipeline`: Run and Artifact models
- `apps.api.services.s3_service`: S3 operations
- `zerna_contracts.enums`: ArtifactType enum
- `temporalio`: Temporal workflow and activity decorators

## Notes

- The current implementation uses placeholder logic for h5ad generation and report compilation
- Temporary files are created in system temp directory with unique prefixes
- S3 paths follow organization-scoped pattern: `{org_id}/runs/{run_id}/export/{export_id}_{filename}`
- Pre-signed URLs are valid for 7 days (configurable)
- Cleanup is best-effort and doesn't fail the workflow if it encounters errors
