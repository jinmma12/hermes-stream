# Hermes Stage Runtime Next Implementation Plan

## Goal

Take the new stage lifecycle model from backend-only semantics to operator-usable runtime control.

## Priority Order

### P1. API Surface

Implement:

- stop stage endpoint
- resume stage endpoint
- queue summary endpoint
- stage runtime summary endpoint or pipeline status extension

Why first:

- UI should not be built on local assumptions
- runtime control must come from a real API contract

### P2. Backend API Tests

Add tests that lock:

- valid stop/resume flow
- invalid stage/activation rejection
- queue summary response shape
- offline or missing activation behavior

### P3. Frontend Types and Client

Add:

- client methods for stop/resume/queue summary
- TS types for stage runtime and queue summary

### P4. UI Runtime Controls

In `PipelineDesignerPage` or related stage UI:

- runtime status badge per stage
- stop/resume controls
- disable runtime controls in local draft mode

### P5. Queue Visibility

Add:

- queue summary panel or drawer
- empty queue state
- basic provenance/work-item link from queue entries

## Non-Goals For This Iteration

- DRAIN mode execution
- dynamic backpressure enforcement
- queue byte calculations
- cluster-aware state replication
- full NiFi connection graph UI

## Risks

### 1. Confusing config disable with runtime stop

Mitigation:

- separate button labels
- separate badges
- separate tooltips

### 2. Local draft mode pretending to support runtime control

Mitigation:

- disable controls when API unavailable
- explicit tooltip/banner: runtime controls require backend connectivity

### 3. Queue numbers drifting from runtime semantics

Mitigation:

- consume backend queue summary only
- do not recompute queue values in the frontend

## File Targets

Likely backend:

- `backend/hermes/api/routes/pipelines.py`
- `backend/hermes/api/schemas/...`
- `backend/tests/...`

Likely frontend:

- `webapp/src/api/client.ts`
- `webapp/src/types/index.ts`
- `webapp/src/pages/PipelineDesignerPage.tsx`
- stage/node UI components used by the designer

## Minimum Done Definition

This iteration is successful if:

- stop/resume works through API
- queue summary is visible in UI
- disabled vs stopped vs paused is understandable
- tests exist at backend and UI/E2E level

Anything beyond that is optional for this slice.
