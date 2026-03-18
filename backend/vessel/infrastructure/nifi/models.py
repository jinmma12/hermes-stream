"""NiFi Data Models.

Pydantic models that mirror the Apache NiFi REST API response structures.
These models cover the subset of NiFi's API surface that Vessel integrates
with: process groups, processors, connections, provenance, templates,
parameter contexts, and system diagnostics.

All models use ``model_config = {"extra": "allow"}`` so that additional
fields returned by newer NiFi versions are preserved rather than rejected.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Shared / utility models
# ---------------------------------------------------------------------------


class NiFiRevision(BaseModel):
    """Optimistic-locking revision used by NiFi's PUT/DELETE endpoints.

    Every mutable NiFi entity carries a ``revision`` object.  The ``version``
    must be echoed back on updates to prevent lost-update conflicts.
    """

    version: int = 0
    client_id: str | None = Field(default=None, alias="clientId")

    model_config = {"extra": "allow", "populate_by_name": True}


class Position(BaseModel):
    """Canvas position for a NiFi component."""

    x: float = 0.0
    y: float = 0.0

    model_config = {"extra": "allow"}


# ---------------------------------------------------------------------------
# Process Group models
# ---------------------------------------------------------------------------


class ProcessGroupCounts(BaseModel):
    """Aggregate counts for a process group."""

    running_count: int = Field(default=0, alias="runningCount")
    stopped_count: int = Field(default=0, alias="stoppedCount")
    invalid_count: int = Field(default=0, alias="invalidCount")
    disabled_count: int = Field(default=0, alias="disabledCount")
    active_remote_port_count: int = Field(default=0, alias="activeRemotePortCount")
    inactive_remote_port_count: int = Field(default=0, alias="inactiveRemotePortCount")
    input_port_count: int = Field(default=0, alias="inputPortCount")
    output_port_count: int = Field(default=0, alias="outputPortCount")

    model_config = {"extra": "allow", "populate_by_name": True}


class ProcessGroupStatusSnapshot(BaseModel):
    """Snapshot of process group throughput statistics."""

    id: str = ""
    name: str = ""
    bytes_in: int = Field(default=0, alias="bytesIn")
    bytes_out: int = Field(default=0, alias="bytesOut")
    bytes_read: int = Field(default=0, alias="bytesRead")
    bytes_written: int = Field(default=0, alias="bytesWritten")
    flowfiles_in: int = Field(default=0, alias="flowFilesIn")
    flowfiles_out: int = Field(default=0, alias="flowFilesOut")
    flowfiles_queued: int = Field(default=0, alias="flowFilesQueued")
    bytes_queued: int = Field(default=0, alias="bytesQueued")
    active_thread_count: int = Field(default=0, alias="activeThreadCount")

    model_config = {"extra": "allow", "populate_by_name": True}


class ProcessGroupStatus(BaseModel):
    """Status response for a process group."""

    id: str = ""
    name: str = ""
    aggregate_snapshot: ProcessGroupStatusSnapshot | None = Field(
        default=None, alias="aggregateSnapshot"
    )

    model_config = {"extra": "allow", "populate_by_name": True}


class ProcessGroup(BaseModel):
    """A NiFi Process Group — Vessel maps these to PipelineInstances."""

    id: str = ""
    name: str = ""
    position: Position | None = None
    comments: str = ""
    running_count: int = Field(default=0, alias="runningCount")
    stopped_count: int = Field(default=0, alias="stoppedCount")
    invalid_count: int = Field(default=0, alias="invalidCount")
    disabled_count: int = Field(default=0, alias="disabledCount")
    input_port_count: int = Field(default=0, alias="inputPortCount")
    output_port_count: int = Field(default=0, alias="outputPortCount")
    parent_group_id: str | None = Field(default=None, alias="parentGroupId")
    revision: NiFiRevision | None = None
    parameter_context: dict[str, Any] | None = Field(
        default=None, alias="parameterContext"
    )

    model_config = {"extra": "allow", "populate_by_name": True}


# ---------------------------------------------------------------------------
# Processor models
# ---------------------------------------------------------------------------


class ProcessorState(StrEnum):
    """NiFi processor scheduling states."""

    RUNNING = "RUNNING"
    STOPPED = "STOPPED"
    DISABLED = "DISABLED"


class ProcessorConfig(BaseModel):
    """Processor configuration (scheduling, properties, relationships)."""

    scheduling_period: str | None = Field(default=None, alias="schedulingPeriod")
    scheduling_strategy: str | None = Field(default=None, alias="schedulingStrategy")
    concurrently_schedulable_task_count: int = Field(
        default=1, alias="concurrentlySchedulableTaskCount"
    )
    penalty_duration: str | None = Field(default=None, alias="penaltyDuration")
    yield_duration: str | None = Field(default=None, alias="yieldDuration")
    properties: dict[str, Any] = Field(default_factory=dict)
    auto_terminated_relationships: list[str] = Field(
        default_factory=list, alias="autoTerminatedRelationships"
    )
    comments: str = ""

    model_config = {"extra": "allow", "populate_by_name": True}


class PropertyDescriptor(BaseModel):
    """Descriptor for a single processor property."""

    name: str = ""
    display_name: str = Field(default="", alias="displayName")
    description: str = ""
    required: bool = False
    sensitive: bool = False
    default_value: str | None = Field(default=None, alias="defaultValue")
    allowable_values: list[dict[str, Any]] | None = Field(
        default=None, alias="allowableValues"
    )

    model_config = {"extra": "allow", "populate_by_name": True}


class ProcessorStatusSnapshot(BaseModel):
    """Snapshot of processor-level statistics."""

    bytes_in: int = Field(default=0, alias="bytesIn")
    bytes_out: int = Field(default=0, alias="bytesOut")
    bytes_read: int = Field(default=0, alias="bytesRead")
    bytes_written: int = Field(default=0, alias="bytesWritten")
    flowfiles_in: int = Field(default=0, alias="flowFilesIn")
    flowfiles_out: int = Field(default=0, alias="flowFilesOut")
    tasks_count: int = Field(default=0, alias="taskCount")
    task_duration_nanos: int = Field(default=0, alias="tasksDurationNanos")
    active_thread_count: int = Field(default=0, alias="activeThreadCount")

    model_config = {"extra": "allow", "populate_by_name": True}


class ProcessorStatus(BaseModel):
    """Status response for a processor."""

    id: str = ""
    name: str = ""
    type: str = ""
    run_status: str = Field(default="", alias="runStatus")
    aggregate_snapshot: ProcessorStatusSnapshot | None = Field(
        default=None, alias="aggregateSnapshot"
    )

    model_config = {"extra": "allow", "populate_by_name": True}


class Processor(BaseModel):
    """A NiFi Processor — the atomic processing unit."""

    id: str = ""
    name: str = ""
    type: str = ""
    state: str = ""
    position: Position | None = None
    config: ProcessorConfig | None = None
    relationships: list[dict[str, Any]] = Field(default_factory=list)
    validation_errors: list[str] = Field(
        default_factory=list, alias="validationErrors"
    )
    property_descriptors: dict[str, PropertyDescriptor] = Field(
        default_factory=dict, alias="propertyDescriptors"
    )
    parent_group_id: str | None = Field(default=None, alias="parentGroupId")
    revision: NiFiRevision | None = None

    model_config = {"extra": "allow", "populate_by_name": True}


# ---------------------------------------------------------------------------
# Connection / Queue models
# ---------------------------------------------------------------------------


class QueueSize(BaseModel):
    """Size of a NiFi connection queue."""

    object_count: int = Field(default=0, alias="objectCount")
    byte_count: int = Field(default=0, alias="byteCount")

    model_config = {"extra": "allow", "populate_by_name": True}


class Connection(BaseModel):
    """A NiFi Connection linking two components with a queue."""

    id: str = ""
    name: str = ""
    source_id: str = Field(default="", alias="sourceId")
    source_group_id: str = Field(default="", alias="sourceGroupId")
    source_type: str = Field(default="", alias="sourceType")
    destination_id: str = Field(default="", alias="destinationId")
    destination_group_id: str = Field(default="", alias="destinationGroupId")
    destination_type: str = Field(default="", alias="destinationType")
    selected_relationships: list[str] = Field(
        default_factory=list, alias="selectedRelationships"
    )
    back_pressure_object_threshold: int = Field(
        default=10000, alias="backPressureObjectThreshold"
    )
    back_pressure_data_size_threshold: str = Field(
        default="1 GB", alias="backPressureDataSizeThreshold"
    )
    queue_size: QueueSize | None = Field(default=None, alias="status")
    revision: NiFiRevision | None = None

    model_config = {"extra": "allow", "populate_by_name": True}


# ---------------------------------------------------------------------------
# FlowFile models
# ---------------------------------------------------------------------------


class FlowFileSummary(BaseModel):
    """Summary of a FlowFile sitting in a connection queue."""

    uuid: str = ""
    filename: str = ""
    size: int = 0
    position: int = 0
    queued_duration: int = Field(default=0, alias="queuedDuration")
    lineage_duration: int = Field(default=0, alias="lineageDuration")
    penalized: bool = False
    attributes: dict[str, str] = Field(default_factory=dict)

    model_config = {"extra": "allow", "populate_by_name": True}


# ---------------------------------------------------------------------------
# Provenance models
# ---------------------------------------------------------------------------


class ProvenanceEventType(StrEnum):
    """NiFi provenance event types."""

    CREATE = "CREATE"
    RECEIVE = "RECEIVE"
    FETCH = "FETCH"
    SEND = "SEND"
    REMOTE_INVOCATION = "REMOTE_INVOCATION"
    DROP = "DROP"
    EXPIRE = "EXPIRE"
    FORK = "FORK"
    JOIN = "JOIN"
    CLONE = "CLONE"
    CONTENT_MODIFIED = "CONTENT_MODIFIED"
    ATTRIBUTES_MODIFIED = "ATTRIBUTES_MODIFIED"
    ROUTE = "ROUTE"
    ADDINFO = "ADDINFO"
    REPLAY = "REPLAY"
    DOWNLOAD = "DOWNLOAD"
    UNKNOWN = "UNKNOWN"


class ProvenanceEvent(BaseModel):
    """A single NiFi provenance event — maps to Vessel ExecutionEventLog."""

    id: str = ""
    event_id: int = Field(default=0, alias="eventId")
    event_type: str = Field(default="", alias="eventType")
    event_time: str | None = Field(default=None, alias="eventTime")
    flowfile_uuid: str = Field(default="", alias="flowFileUuid")
    file_size: int = Field(default=0, alias="fileSize")
    component_id: str = Field(default="", alias="componentId")
    component_name: str = Field(default="", alias="componentName")
    component_type: str = Field(default="", alias="componentType")
    group_id: str = Field(default="", alias="groupId")
    details: str = ""
    attributes: list[dict[str, Any]] = Field(default_factory=list)
    updated_attributes: list[dict[str, Any]] = Field(
        default_factory=list, alias="updatedAttributes"
    )
    content_claim_section: str | None = Field(
        default=None, alias="contentClaimSection"
    )
    content_claim_container: str | None = Field(
        default=None, alias="contentClaimContainer"
    )
    content_claim_identifier: str | None = Field(
        default=None, alias="contentClaimIdentifier"
    )
    content_claim_offset: int | None = Field(
        default=None, alias="contentClaimOffset"
    )
    content_claim_file_size: int | None = Field(
        default=None, alias="contentClaimFileSize"
    )
    parent_uuids: list[str] = Field(default_factory=list, alias="parentUuids")
    child_uuids: list[str] = Field(default_factory=list, alias="childUuids")
    transit_uri: str | None = Field(default=None, alias="transitUri")
    source_system_flowfile_identifier: str | None = Field(
        default=None, alias="sourceSystemFlowFileIdentifier"
    )

    model_config = {"extra": "allow", "populate_by_name": True}


class ProvenanceResults(BaseModel):
    """Results of a NiFi provenance query."""

    provenance_events: list[ProvenanceEvent] = Field(
        default_factory=list, alias="provenanceEvents"
    )
    total: int = 0
    total_count: int = Field(default=0, alias="totalCount")
    generated: str | None = None
    oldest_event: str | None = Field(default=None, alias="oldestEvent")
    percentage_completed: int = Field(default=0, alias="percentCompleted")
    finished: bool = False

    model_config = {"extra": "allow", "populate_by_name": True}


# ---------------------------------------------------------------------------
# Template models
# ---------------------------------------------------------------------------


class Template(BaseModel):
    """A NiFi template (NiFi 1.x; deprecated in 2.x)."""

    id: str = ""
    name: str = ""
    description: str = ""
    group_id: str | None = Field(default=None, alias="groupId")
    timestamp: str | None = None
    uri: str | None = None

    model_config = {"extra": "allow", "populate_by_name": True}


# ---------------------------------------------------------------------------
# Parameter Context models
# ---------------------------------------------------------------------------


class Parameter(BaseModel):
    """A single parameter in a NiFi Parameter Context."""

    name: str = ""
    value: str | None = None
    sensitive: bool = False
    description: str = ""
    provided: bool = False

    model_config = {"extra": "allow", "populate_by_name": True}


class ParameterContext(BaseModel):
    """A NiFi Parameter Context — maps to Vessel Recipe versions."""

    id: str = ""
    name: str = ""
    description: str = ""
    parameters: list[dict[str, Any]] = Field(default_factory=list)
    bound_process_groups: list[dict[str, Any]] = Field(
        default_factory=list, alias="boundProcessGroups"
    )
    revision: NiFiRevision | None = None

    model_config = {"extra": "allow", "populate_by_name": True}

    def get_parameters_flat(self) -> dict[str, str | None]:
        """Return parameters as a flat ``{name: value}`` dict.

        NiFi wraps each parameter in ``{"parameter": {...}}``.  This helper
        unwraps them for easier consumption.
        """
        result: dict[str, str | None] = {}
        for entry in self.parameters:
            param = entry.get("parameter", entry)
            result[param.get("name", "")] = param.get("value")
        return result


# ---------------------------------------------------------------------------
# System / Cluster models
# ---------------------------------------------------------------------------


class GarbageCollection(BaseModel):
    """JVM garbage collection statistics."""

    name: str = ""
    collection_count: int = Field(default=0, alias="collectionCount")
    collection_time: str = Field(default="", alias="collectionTime")

    model_config = {"extra": "allow", "populate_by_name": True}


class StorageUsage(BaseModel):
    """Disk storage usage for a content/provenance repository."""

    identifier: str = ""
    free_space: str = Field(default="", alias="freeSpace")
    total_space: str = Field(default="", alias="totalSpace")
    used_space: str = Field(default="", alias="usedSpace")
    free_space_bytes: int = Field(default=0, alias="freeSpaceBytes")
    total_space_bytes: int = Field(default=0, alias="totalSpaceBytes")
    used_space_bytes: int = Field(default=0, alias="usedSpaceBytes")
    utilization: str = ""

    model_config = {"extra": "allow", "populate_by_name": True}


class SystemDiagnostics(BaseModel):
    """NiFi system diagnostics — JVM, disk, threads."""

    total_non_heap: str = Field(default="", alias="totalNonHeap")
    total_non_heap_bytes: int = Field(default=0, alias="totalNonHeapBytes")
    used_non_heap: str = Field(default="", alias="usedNonHeap")
    used_non_heap_bytes: int = Field(default=0, alias="usedNonHeapBytes")
    free_non_heap: str = Field(default="", alias="freeNonHeap")
    free_non_heap_bytes: int = Field(default=0, alias="freeNonHeapBytes")
    max_heap: str = Field(default="", alias="maxHeap")
    max_heap_bytes: int = Field(default=0, alias="maxHeapBytes")
    total_heap: str = Field(default="", alias="totalHeap")
    total_heap_bytes: int = Field(default=0, alias="totalHeapBytes")
    used_heap: str = Field(default="", alias="usedHeap")
    used_heap_bytes: int = Field(default=0, alias="usedHeapBytes")
    free_heap: str = Field(default="", alias="freeHeap")
    free_heap_bytes: int = Field(default=0, alias="freeHeapBytes")
    heap_utilization: str = Field(default="", alias="heapUtilization")
    available_processors: int = Field(default=0, alias="availableProcessors")
    processor_load_average: float = Field(default=0.0, alias="processorLoadAverage")
    total_threads: int = Field(default=0, alias="totalThreads")
    daemon_threads: int = Field(default=0, alias="daemonThreads")
    garbage_collection: list[GarbageCollection] = Field(
        default_factory=list, alias="garbageCollection"
    )
    content_repository_storage_usage: list[StorageUsage] = Field(
        default_factory=list, alias="contentRepositoryStorageUsage"
    )
    provenance_repository_storage_usage: list[StorageUsage] = Field(
        default_factory=list, alias="provenanceRepositoryStorageUsage"
    )
    flowfile_repository_storage_usage: StorageUsage | None = Field(
        default=None, alias="flowFileRepositoryStorageUsage"
    )
    uptime: str = ""
    stats_last_refreshed: str | None = Field(
        default=None, alias="statsLastRefreshed"
    )

    model_config = {"extra": "allow", "populate_by_name": True}


class ClusterSummary(BaseModel):
    """High-level NiFi cluster summary."""

    connected_node_count: int = Field(default=0, alias="connectedNodeCount")
    total_node_count: int = Field(default=0, alias="totalNodeCount")
    connected_nodes: str = Field(default="", alias="connectedNodes")
    clustered: bool = False
    connected_to_cluster: bool = Field(default=False, alias="connectedToCluster")

    model_config = {"extra": "allow", "populate_by_name": True}


class ControllerStatusSnapshot(BaseModel):
    """Controller-level status snapshot."""

    active_thread_count: int = Field(default=0, alias="activeThreadCount")
    terminated_thread_count: int = Field(default=0, alias="terminatedThreadCount")
    queued_count: str = Field(default="0", alias="queued")
    bytes_queued: int = Field(default=0, alias="bytesQueued")
    flowfiles_queued: int = Field(default=0, alias="flowFilesQueued")
    running_count: int = Field(default=0, alias="runningCount")
    stopped_count: int = Field(default=0, alias="stoppedCount")
    invalid_count: int = Field(default=0, alias="invalidCount")
    disabled_count: int = Field(default=0, alias="disabledCount")

    model_config = {"extra": "allow", "populate_by_name": True}


class ControllerStatus(BaseModel):
    """NiFi controller status response."""

    controller_status: ControllerStatusSnapshot | None = Field(
        default=None, alias="controllerStatus"
    )

    model_config = {"extra": "allow", "populate_by_name": True}


# ---------------------------------------------------------------------------
# NiFi Health (Vessel-specific composite model)
# ---------------------------------------------------------------------------


class NiFiHealthStatus(BaseModel):
    """Composite health status used by the Vessel Monitor Dashboard.

    This is not a NiFi API model — it is assembled by the bridge layer from
    multiple NiFi API calls.
    """

    reachable: bool = False
    cluster_connected: bool = False
    connected_nodes: int = 0
    total_nodes: int = 0
    heap_utilization: str = ""
    active_threads: int = 0
    queued_flowfiles: int = 0
    queued_bytes: int = 0
    running_processors: int = 0
    stopped_processors: int = 0
    invalid_processors: int = 0
    back_pressure_connections: list[str] = Field(default_factory=list)
    error: str | None = None
    checked_at: datetime | None = None

    model_config = {"extra": "allow"}
