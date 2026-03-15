# Hermes Test Scenarios

> Purpose: keep migration and roadmap work anchored to executable scenarios.

## Build Smoke

These are the shallowest tests. They answer "can the solution be restored,
built, and minimally started?" not "does the feature work end to end?"

- `dotnet build engine/Hermes.sln`
- `dotnet test engine/tests/Hermes.Api.Tests`

## API Contract Scenarios

These tests lock down the public HTTP surface expected by the React frontend.

- `root_returns_service_metadata`
- `live_health_returns_ok_status`
- `ready_health_returns_ready_status`
- `system_info_exposes_migration_status`
- `definitions_list_endpoints_return_success`
- `unknown_definition_kind_returns_not_found`
- `jobs_list_returns_paginated_shape`
- `pipeline_detail_returns_requested_id`

## Migration Parity Scenarios

These scenarios should be added as Python FastAPI routes move to ASP.NET Core.

- `definitions_list_matches_python_contract`
- `pipeline_detail_matches_python_contract`
- `work_item_detail_matches_python_contract`
- `pipeline_activation_request_is_accepted`
- `reprocess_request_is_accepted`

## Runtime Scenarios

These should mirror the behavior already captured in Python tests.

- `pipeline_can_be_created_and_validated`
- `invalid_step_reference_is_rejected`
- `recipe_version_publish_switches_current_version`
- `failed_algorithm_step_can_be_reprocessed`
- `retry_policy_retries_then_completes`
- `skip_policy_marks_step_skipped_and_continues`

## End-to-End Scenarios

- `api_engine_ui_start_together`
- `ui_can_load_pipeline_list_from_dotnet_api`
- `pipeline_runs_from_detection_to_transfer`
- `operator_can_reprocess_failed_work_item`
