-- Migration: Add stage_runtime_states table for per-stage stop/resume control
-- This table tracks runtime state (RUNNING/STOPPED/DRAINING/BLOCKED/ERROR)
-- independently from the static is_enabled config flag on pipeline_steps.

CREATE TABLE IF NOT EXISTS stage_runtime_states (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pipeline_activation_id UUID NOT NULL REFERENCES pipeline_activations(id) ON DELETE CASCADE,
    pipeline_step_id UUID NOT NULL REFERENCES pipeline_steps(id) ON DELETE CASCADE,
    runtime_status VARCHAR(20) NOT NULL DEFAULT 'RUNNING',
    stopped_at TIMESTAMPTZ,
    stopped_by VARCHAR(256),
    resumed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_stage_runtime_activation_step UNIQUE (pipeline_activation_id, pipeline_step_id)
);

CREATE INDEX IF NOT EXISTS idx_stage_runtime_activation ON stage_runtime_states(pipeline_activation_id);
CREATE INDEX IF NOT EXISTS idx_stage_runtime_step ON stage_runtime_states(pipeline_step_id);

COMMENT ON TABLE stage_runtime_states IS 'Per-stage runtime state within a pipeline activation. Distinct from is_enabled (config) and pipeline activation status.';
COMMENT ON COLUMN stage_runtime_states.runtime_status IS 'RUNNING, STOPPED, DRAINING, BLOCKED, ERROR';
