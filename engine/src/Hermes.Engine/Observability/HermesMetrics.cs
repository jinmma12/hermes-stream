using Prometheus;

namespace Hermes.Engine.Observability;

/// <summary>
/// Centralized Prometheus metrics for the Hermes Engine.
/// All metrics are prefixed with "hermes_" for easy Grafana dashboard filtering.
/// </summary>
public static class HermesMetrics
{
    // ── Pipeline Monitoring ──

    public static readonly Gauge ActivePipelines = Metrics.CreateGauge(
        "hermes_pipelines_active",
        "Number of currently active (monitoring) pipelines");

    public static readonly Counter MonitorPollsTotal = Metrics.CreateCounter(
        "hermes_monitor_polls_total",
        "Total number of monitoring poll cycles",
        new CounterConfiguration { LabelNames = new[] { "pipeline_id", "monitor_type" } });

    public static readonly Counter EventsDetectedTotal = Metrics.CreateCounter(
        "hermes_events_detected_total",
        "Total events detected by monitors",
        new CounterConfiguration { LabelNames = new[] { "pipeline_id", "event_type" } });

    public static readonly Counter EventsDedupedTotal = Metrics.CreateCounter(
        "hermes_events_deduped_total",
        "Total events rejected by dedup check",
        new CounterConfiguration { LabelNames = new[] { "pipeline_id" } });

    // ── Work Item Processing ──

    public static readonly Counter WorkItemsCreatedTotal = Metrics.CreateCounter(
        "hermes_work_items_created_total",
        "Total work items created",
        new CounterConfiguration { LabelNames = new[] { "pipeline_id", "source_type" } });

    public static readonly Counter WorkItemsCompletedTotal = Metrics.CreateCounter(
        "hermes_work_items_completed_total",
        "Total work items successfully completed",
        new CounterConfiguration { LabelNames = new[] { "pipeline_id" } });

    public static readonly Counter WorkItemsFailedTotal = Metrics.CreateCounter(
        "hermes_work_items_failed_total",
        "Total work items that failed",
        new CounterConfiguration { LabelNames = new[] { "pipeline_id" } });

    public static readonly Gauge WorkItemsProcessing = Metrics.CreateGauge(
        "hermes_work_items_processing",
        "Number of work items currently being processed");

    public static readonly Gauge WorkItemsQueued = Metrics.CreateGauge(
        "hermes_work_items_queued",
        "Number of work items waiting in queue");

    public static readonly Histogram WorkItemDurationSeconds = Metrics.CreateHistogram(
        "hermes_work_item_duration_seconds",
        "Work item processing duration in seconds",
        new HistogramConfiguration
        {
            LabelNames = new[] { "pipeline_id" },
            Buckets = new[] { 0.1, 0.5, 1, 2, 5, 10, 30, 60, 120, 300 }
        });

    // ── Step Execution ──

    public static readonly Counter StepExecutionsTotal = Metrics.CreateCounter(
        "hermes_step_executions_total",
        "Total step executions",
        new CounterConfiguration { LabelNames = new[] { "step_type", "status" } });

    public static readonly Histogram StepDurationSeconds = Metrics.CreateHistogram(
        "hermes_step_duration_seconds",
        "Individual step execution duration in seconds",
        new HistogramConfiguration
        {
            LabelNames = new[] { "step_type" },
            Buckets = new[] { 0.01, 0.05, 0.1, 0.5, 1, 5, 10, 30, 60 }
        });

    // ── Plugin System ──

    public static readonly Gauge PluginsRegistered = Metrics.CreateGauge(
        "hermes_plugins_registered",
        "Number of registered plugins",
        new GaugeConfiguration { LabelNames = new[] { "plugin_type" } });

    public static readonly Counter PluginExecutionsTotal = Metrics.CreateCounter(
        "hermes_plugin_executions_total",
        "Total plugin executions",
        new CounterConfiguration { LabelNames = new[] { "plugin_name", "status" } });

    public static readonly Counter PluginTimeoutsTotal = Metrics.CreateCounter(
        "hermes_plugin_timeouts_total",
        "Total plugin execution timeouts",
        new CounterConfiguration { LabelNames = new[] { "plugin_name" } });

    // ── Reprocessing ──

    public static readonly Counter ReprocessRequestsTotal = Metrics.CreateCounter(
        "hermes_reprocess_requests_total",
        "Total reprocess requests created",
        new CounterConfiguration { LabelNames = new[] { "pipeline_id" } });

    public static readonly Counter ReprocessCompletedTotal = Metrics.CreateCounter(
        "hermes_reprocess_completed_total",
        "Total reprocess requests completed");

    // ── System ──

    public static readonly Gauge EngineUptime = Metrics.CreateGauge(
        "hermes_engine_uptime_seconds",
        "Engine uptime in seconds");

    public static readonly Gauge DbConnectionPoolActive = Metrics.CreateGauge(
        "hermes_db_connections_active",
        "Active database connections");
}
