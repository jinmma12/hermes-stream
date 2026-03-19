# Engine Reference Implementations (Python)

These Python files are the **original reference implementations** of the Hermes Engine layer.
They have been moved here from `backend/hermes/` as part of the Python/C# separation.

The .NET Engine (`engine/src/Hermes.Engine/`) should replicate this behavior.

## Files

### domain/services/
- `monitoring_engine.py` - Pipeline monitoring (file watch, API poll, DB poll)
- `processing_orchestrator.py` - Work item processing pipeline
- `execution_dispatcher.py` - Step execution dispatch (plugin, NiFi, script)
- `condition_evaluator.py` - Conditional step evaluation
- `snapshot_resolver.py` - Config snapshot resolution for execution

### workers/
- `monitoring_worker.py` - Background worker that runs MonitoringEngine
- `processing_worker.py` - Background worker that runs ProcessingOrchestrator

### plugins/
- `protocol.py` - JSON-line plugin communication protocol
- `registry.py` - Plugin discovery and registration
- `executor.py` - Subprocess-based plugin execution

### infrastructure/nifi/
- `client.py` - Async NiFi REST API client
- `bridge.py` - NiFi-to-Hermes concept mapping
- `executor.py` - NiFi flow execution
- `config.py` - NiFi connection configuration
- `models.py` - NiFi data models
