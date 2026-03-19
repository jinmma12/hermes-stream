# Hermes Stage Runtime API And UI Design

## 1. Why This Next

Hermes now has:

- a per-stage runtime state model
- stop/resume service methods
- queue summary derivation
- tests proving model-level semantics

Hermes still does not have:

- public API endpoints for stage runtime control
- public API endpoints for queue visibility
- operator UI surfaces for stopped stages and backlog inspection
- provenance views tied to stage backlog inspection

This is now the correct next step.

Without it, stage lifecycle remains a backend-only capability and operators still
cannot use it as an actual runtime control surface.

## 2. Scope

This phase is intentionally narrower than "full NiFi clone".

In scope:

- stage stop/resume API
- activation queue summary API
- stage runtime state in pipeline status surfaces
- operator UI controls for stage stop/resume
- queue/backlog visibility in the pipeline designer and monitoring views
- provenance navigation from stopped/backlogged stages

Out of scope for this phase:

- DRAINING runtime semantics
- byte-accurate queue accounting
- automatic backpressure pause
- cluster-safe stage runtime ownership
- full provenance explorer redesign

## 3. Runtime Truth

The runtime source of truth remains the backend/.NET runtime model.

UI rules:

- UI must never imply that a stage is stopped unless runtime says so
- UI must distinguish:
  - pipeline paused
  - stage stopped
  - stage disabled in config
- queue depth is runtime data, not canvas-local state

## 4. Required API Additions

## 4.1 Stage Runtime DTO

Suggested response model:

```json
{
  "pipeline_activation_id": "uuid",
  "pipeline_step_id": "uuid",
  "runtime_status": "RUNNING",
  "stopped_at": null,
  "stopped_by": null,
  "resumed_at": null
}
```

## 4.2 Queue Summary DTO

Suggested response model:

```json
{
  "stage_id": "uuid",
  "stage_order": 2,
  "stage_type": "PROCESS",
  "runtime_status": "STOPPED",
  "queued_count": 14,
  "in_flight_count": 0,
  "completed_count": 231
}
```

## 4.3 Endpoints

Suggested additions under activation scope:

- `GET /api/v1/pipelines/{pipeline_id}/activations/{activation_id}/stages/runtime`
  - returns stage runtime states for the activation

- `POST /api/v1/pipelines/{pipeline_id}/activations/{activation_id}/stages/{stage_id}/stop`
  - request body:
    - `stopped_by`
    - optional `reason`

- `POST /api/v1/pipelines/{pipeline_id}/activations/{activation_id}/stages/{stage_id}/resume`

- `GET /api/v1/pipelines/{pipeline_id}/activations/{activation_id}/queues`
  - returns queue summary for all stages

- optional later:
  - `GET /api/v1/pipelines/{pipeline_id}/activations/{activation_id}/stages/{stage_id}/queue-items`

## 4.4 Status Surface Update

`GET /api/v1/pipelines/{pipeline_id}/status` should remain pipeline-level, but should add:

- latest activation id
- stage runtime summary
- queue summary

Minimal example:

```json
{
  "pipeline_id": "uuid",
  "status": "ACTIVE",
  "latest_activation": {
    "id": "uuid",
    "status": "RUNNING"
  },
  "stages": [
    {
      "stage_id": "uuid",
      "runtime_status": "STOPPED",
      "queued_count": 12
    }
  ]
}
```

## 5. UI Design

## 5.1 Pipeline Designer

Each stage card/node should eventually show:

- config enabled/disabled state
- runtime state badge
  - `RUNNING`
  - `STOPPED`
  - later `BLOCKED`, `DRAINING`, `ERROR`
- queued count badge
- quick action:
  - `Stop`
  - `Resume`

Important distinction:

- `Disable`
  - edits pipeline definition

- `Stop`
  - runtime operator action on the active activation

These controls must not be merged into one toggle.

## 5.2 Queue Panel

Add a queue/runtime drawer or side panel showing:

- stage order and stage name
- runtime status
- queued count
- in-flight count
- completed count

For the first phase, per-stage summary is enough.

## 5.3 Provenance Link

From a stopped stage with backlog, the operator should be able to:

- open work items for the activation
- filter by current waiting stage or last completed stage

Minimal acceptable implementation:

- button or link from queue panel to the existing provenance/work item view with filter params

## 5.4 Empty Queue State

UI should explicitly show:

- `Queue Empty`

This matters because one of the operator goals is:

- stop stage
- inspect backlog
- resume
- confirm drain completion

## 6. Required Type Changes

Frontend types should gain:

- `StageRuntimeState`
- `StageQueueSummary`
- activation status payload containing stage runtime/queue summaries

Pipeline canvas local model must not invent these values.
They must come from API or clearly marked local fallback/draft mode.

## 7. Persistence And Fallback Rules

If backend API is unavailable:

- runtime stop/resume controls must be disabled
- queue visibility must not show fake values
- local draft mode can still edit pipeline definition
- runtime controls require real backend connectivity

This is important.
Runtime control is not a local draft concern.

## 8. Test Plan

## 8.1 Backend API Tests

Add tests for:

- stop stage endpoint changes runtime status
- resume stage endpoint changes runtime status
- stop invalid stage for activation returns error
- queue summary endpoint returns expected counts
- disabled stage is not exposed as runtime-stoppable

## 8.2 Frontend UI Tests

Add tests for:

- stage shows STOPPED badge when API says STOPPED
- clicking Stop calls stage stop endpoint
- clicking Resume calls stage resume endpoint
- queue panel shows queued_count
- empty queue renders correct empty state
- runtime controls disabled in offline draft mode

## 8.3 E2E Flow Tests

Add E2E tests for:

- active pipeline -> stop process stage -> queue count visible
- resume process stage -> queue drains -> queue empty visible
- pipeline deactivate still stops whole activation
- disabled stage does not render as runtime-stoppable

## 9. Acceptance Criteria

This phase is done when:

1. operators can stop/resume a stage from the UI
2. operators can see queue backlog for a stopped stage
3. operators can distinguish disabled vs stopped vs pipeline paused
4. queue empty state is visible after drain
5. runtime controls are disabled when API is unavailable
6. API and UI tests cover the behavior

## 10. Follow-On Work

After this phase:

- DRAINING semantics
- byte-aware queue metrics
- stage-level health dashboard
- cluster-aware runtime state ownership
- full provenance/backlog explorer
