"""Background workers for Hermes.

NOTE: Worker execution has been moved to the .NET Engine service.
The Python reference implementations are preserved in engine/reference/workers/.
The MonitoringWorker and ProcessingWorker classes are no longer started
by the Web API; the .NET Engine handles all background processing.
"""
