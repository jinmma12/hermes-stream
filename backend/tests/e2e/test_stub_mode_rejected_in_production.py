"""E2E: Stub mode visibility — verify EngineClient stub mode is detectable.

Risk addressed: EngineClient silently falls back to stub mode when gRPC
is unavailable. Operators may think activation/reprocess succeeded when
only a stub response was returned.

These tests verify:
1. Stub mode is detectable via is_connected property
2. Stub responses are clearly marked as "stub"
3. Health endpoint can surface degraded state
"""

from __future__ import annotations

import pytest

from vessel import engine_client as engine_client_module


@pytest.mark.asyncio
async def test_stub_mode_detectable_via_is_connected(monkeypatch):
    """EngineClient.is_connected returns False when in stub mode."""
    monkeypatch.setattr(engine_client_module, "_GRPC_AVAILABLE", False)
    client = engine_client_module.EngineClient(host="engine", port=50051)

    await client.connect()

    assert not client.is_connected, (
        "EngineClient must report is_connected=False in stub mode"
    )


@pytest.mark.asyncio
async def test_stub_responses_clearly_marked(monkeypatch):
    """All stub-mode responses must include status='stub' for caller detection."""
    monkeypatch.setattr(engine_client_module, "_GRPC_AVAILABLE", False)
    client = engine_client_module.EngineClient(host="engine", port=50051)
    await client.connect()

    # activate_pipeline
    result = await client.activate_pipeline("test-pipeline-id")
    assert result["status"] == "stub", "Stub response must have status='stub'"

    # deactivate_pipeline
    result = await client.deactivate_pipeline("test-pipeline-id")
    assert result["status"] == "stub"

    # reprocess_work_item
    result = await client.reprocess_work_item("test-work-item-id")
    assert result["status"] == "stub"

    # get_engine_status
    result = await client.get_engine_status()
    assert result["status"] == "stub"
    assert result["engine"] == "not_connected"

    # get_pipeline_status
    result = await client.get_pipeline_status("test-pipeline-id")
    assert result["status"] == "stub"


@pytest.mark.asyncio
async def test_bulk_reprocess_stub_returns_count(monkeypatch):
    """Bulk reprocess in stub mode returns item count so caller can detect stub."""
    monkeypatch.setattr(engine_client_module, "_GRPC_AVAILABLE", False)
    client = engine_client_module.EngineClient(host="engine", port=50051)
    await client.connect()

    result = await client.bulk_reprocess(
        work_item_ids=["item-1", "item-2", "item-3"],
        requested_by="admin",
    )
    assert result["status"] == "stub"
    assert result["count"] == 3


@pytest.mark.asyncio
async def test_production_mode_should_detect_stub_transport():
    """Contract: a production health check should be able to detect stub mode.

    This test documents the desired behavior: when the system is in
    production mode, the health check must surface that the engine
    transport is in stub mode so operators are aware.

    Currently EngineClient provides enough info via is_connected and
    get_engine_status() for a health check to implement this.
    """
    client = engine_client_module.EngineClient(host="engine", port=50051)
    # Without calling connect(), client is not connected
    assert not client.is_connected

    status = await client.get_engine_status()
    # Health check can use these fields to detect degraded state
    assert status["status"] == "stub"
    assert status["engine"] == "not_connected"
    assert "not yet connected" in status["message"].lower() or "not_connected" in status["engine"]
