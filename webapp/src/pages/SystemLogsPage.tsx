import { useEffect, useState, useRef } from 'react';
import { monitor } from '../api/client';

interface LogEntry {
  id: string;
  event_type: string;
  event_code: string;
  message: string;
  detail_json: string | null;
  pipeline_id: string | null;
  pipeline_name: string | null;
  execution_id: string | null;
  step_type: string | null;
  created_at: string;
  node_id: string | null;
}

const levelColors: Record<string, { bg: string; text: string; border: string }> = {
  DEBUG: { bg: 'bg-slate-50', text: 'text-slate-500', border: 'border-l-slate-300' },
  Info: { bg: 'bg-blue-50', text: 'text-blue-700', border: 'border-l-blue-400' },
  Warn: { bg: 'bg-amber-50', text: 'text-amber-700', border: 'border-l-amber-400' },
  Error: { bg: 'bg-red-50', text: 'text-red-700', border: 'border-l-red-500' },
};

export default function SystemLogsPage() {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [levelFilter, setLevelFilter] = useState<string>('all');
  const [autoScroll, setAutoScroll] = useState(true);
  const [paused, setPaused] = useState(false);
  const logEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    loadLogs();
    if (!paused) {
      const interval = setInterval(loadLogs, 3000);
      return () => clearInterval(interval);
    }
  }, [paused]);

  useEffect(() => {
    if (autoScroll && logEndRef.current) {
      logEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [logs, autoScroll]);

  async function loadLogs() {
    try {
      const data = await monitor.getRecentLogs?.() ?? [];
      setLogs(data);
    } catch {
      // Demo data
      const now = new Date();
      setLogs([
        { id: '1', event_type: 'Info', event_code: 'ENGINE_START', message: 'Hermes Engine started on gRPC:50051, Metrics:9090', detail_json: null, pipeline_id: null, pipeline_name: null, execution_id: null, step_type: null, created_at: new Date(now.getTime() - 300000).toISOString(), node_id: 'worker-1' },
        { id: '2', event_type: 'Info', event_code: 'PIPELINE_ACTIVATED', message: 'Pipeline "Sensor Data Pipeline" activated', detail_json: null, pipeline_id: 'p-001', pipeline_name: 'Sensor Data Pipeline', execution_id: null, step_type: null, created_at: new Date(now.getTime() - 280000).toISOString(), node_id: 'worker-1' },
        { id: '3', event_type: 'Info', event_code: 'MONITOR_POLL', message: 'FileMonitor polled: 3 new files detected in /data/incoming', detail_json: '{"files":3}', pipeline_id: 'p-001', pipeline_name: 'Sensor Data Pipeline', execution_id: null, step_type: null, created_at: new Date(now.getTime() - 260000).toISOString(), node_id: 'worker-1' },
        { id: '4', event_type: 'Info', event_code: 'EXECUTION_START', message: 'Starting execution #1 (Initial) for sensors_batch1.csv', detail_json: null, pipeline_id: 'p-001', pipeline_name: 'Sensor Data Pipeline', execution_id: 'e-001', step_type: null, created_at: new Date(now.getTime() - 250000).toISOString(), node_id: 'worker-1' },
        { id: '5', event_type: 'Info', event_code: 'STEP_START', message: 'Starting step 1 (Collect)', detail_json: null, pipeline_id: 'p-001', pipeline_name: 'Sensor Data Pipeline', execution_id: 'e-001', step_type: 'COLLECT', created_at: new Date(now.getTime() - 249000).toISOString(), node_id: 'worker-1' },
        { id: '6', event_type: 'Info', event_code: 'STEP_DONE', message: 'Step 1 completed in 523ms — 150 records collected', detail_json: '{"records":150,"duration_ms":523}', pipeline_id: 'p-001', pipeline_name: 'Sensor Data Pipeline', execution_id: 'e-001', step_type: 'COLLECT', created_at: new Date(now.getTime() - 248000).toISOString(), node_id: 'worker-1' },
        { id: '7', event_type: 'Info', event_code: 'STEP_START', message: 'Starting step 2 (Process)', detail_json: null, pipeline_id: 'p-001', pipeline_name: 'Sensor Data Pipeline', execution_id: 'e-001', step_type: 'PROCESS', created_at: new Date(now.getTime() - 247000).toISOString(), node_id: 'worker-1' },
        { id: '8', event_type: 'Warn', event_code: 'ANOMALY_DETECTED', message: 'Anomaly detector found 3 outliers in batch (threshold: 0.95)', detail_json: '{"outliers":3,"threshold":0.95}', pipeline_id: 'p-001', pipeline_name: 'Sensor Data Pipeline', execution_id: 'e-001', step_type: 'PROCESS', created_at: new Date(now.getTime() - 246000).toISOString(), node_id: 'worker-1' },
        { id: '9', event_type: 'Info', event_code: 'STEP_DONE', message: 'Step 2 completed in 1,247ms — 147 normal, 3 anomalies', detail_json: '{"normal":147,"anomalies":3}', pipeline_id: 'p-001', pipeline_name: 'Sensor Data Pipeline', execution_id: 'e-001', step_type: 'PROCESS', created_at: new Date(now.getTime() - 245000).toISOString(), node_id: 'worker-1' },
        { id: '10', event_type: 'Info', event_code: 'STEP_START', message: 'Starting step 3 (Export)', detail_json: null, pipeline_id: 'p-001', pipeline_name: 'Sensor Data Pipeline', execution_id: 'e-001', step_type: 'EXPORT', created_at: new Date(now.getTime() - 244000).toISOString(), node_id: 'worker-1' },
        { id: '11', event_type: 'Error', event_code: 'STEP_FAILED', message: 'Step 3 failed: connection timeout to S3 bucket (attempt 1/3)', detail_json: '{"error":"ConnectionTimeout","bucket":"hermes-output"}', pipeline_id: 'p-001', pipeline_name: 'Sensor Data Pipeline', execution_id: 'e-001', step_type: 'EXPORT', created_at: new Date(now.getTime() - 243000).toISOString(), node_id: 'worker-1' },
        { id: '12', event_type: 'Info', event_code: 'STEP_RETRY', message: 'Retrying step 3, attempt 2/3, delay 5s', detail_json: null, pipeline_id: 'p-001', pipeline_name: 'Sensor Data Pipeline', execution_id: 'e-001', step_type: 'EXPORT', created_at: new Date(now.getTime() - 238000).toISOString(), node_id: 'worker-1' },
        { id: '13', event_type: 'Info', event_code: 'STEP_RETRY_SUCCESS', message: 'Step 3 succeeded on retry 2 — 150 records transferred', detail_json: '{"records":150}', pipeline_id: 'p-001', pipeline_name: 'Sensor Data Pipeline', execution_id: 'e-001', step_type: 'EXPORT', created_at: new Date(now.getTime() - 237000).toISOString(), node_id: 'worker-1' },
        { id: '14', event_type: 'Info', event_code: 'EXECUTION_DONE', message: 'Execution #1 Completed in 13,245ms', detail_json: '{"duration_ms":13245,"status":"Completed"}', pipeline_id: 'p-001', pipeline_name: 'Sensor Data Pipeline', execution_id: 'e-001', step_type: null, created_at: new Date(now.getTime() - 236000).toISOString(), node_id: 'worker-1' },
        { id: '15', event_type: 'Info', event_code: 'EXECUTION_START', message: 'Starting execution #1 (Initial) for sensors_batch2.csv', detail_json: null, pipeline_id: 'p-001', pipeline_name: 'Sensor Data Pipeline', execution_id: 'e-002', step_type: null, created_at: new Date(now.getTime() - 200000).toISOString(), node_id: 'worker-1' },
        { id: '16', event_type: 'Info', event_code: 'EXECUTION_DONE', message: 'Execution #1 Completed in 8,120ms', detail_json: '{"duration_ms":8120,"status":"Completed"}', pipeline_id: 'p-001', pipeline_name: 'Sensor Data Pipeline', execution_id: 'e-002', step_type: null, created_at: new Date(now.getTime() - 192000).toISOString(), node_id: 'worker-1' },
        { id: '17', event_type: 'Info', event_code: 'MONITOR_POLL', message: 'ApiPollMonitor polled: content changed, new event detected', detail_json: '{"url":"http://api.vendor.com/status"}', pipeline_id: 'p-002', pipeline_name: 'API Status Pipeline', execution_id: null, step_type: null, created_at: new Date(now.getTime() - 120000).toISOString(), node_id: 'worker-2' },
        { id: '18', event_type: 'Error', event_code: 'STEP_FAILED', message: 'Step 1 failed: HTTP 503 Service Unavailable from vendor API', detail_json: '{"status_code":503}', pipeline_id: 'p-002', pipeline_name: 'API Status Pipeline', execution_id: 'e-003', step_type: 'COLLECT', created_at: new Date(now.getTime() - 110000).toISOString(), node_id: 'worker-2' },
        { id: '19', event_type: 'Info', event_code: 'REPROCESS_REQUESTED', message: 'Reprocess requested by operator:kim — reason: "vendor API recovered"', detail_json: null, pipeline_id: 'p-002', pipeline_name: 'API Status Pipeline', execution_id: null, step_type: null, created_at: new Date(now.getTime() - 60000).toISOString(), node_id: null },
        { id: '20', event_type: 'Info', event_code: 'HEARTBEAT', message: 'Engine healthy — 2 active pipelines, 0 queued, 0 processing', detail_json: '{"active_pipelines":2,"queued":0,"processing":0}', pipeline_id: null, pipeline_name: null, execution_id: null, step_type: null, created_at: new Date(now.getTime() - 5000).toISOString(), node_id: 'worker-1' },
      ]);
    } finally {
      setLoading(false);
    }
  }

  const filteredLogs = levelFilter === 'all'
    ? logs
    : logs.filter(l => l.event_type.toLowerCase() === levelFilter.toLowerCase());

  function formatTime(iso: string): string {
    return new Date(iso).toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit', fractionalSecondDigits: 3 } as any);
  }

  if (loading) return <div className="flex items-center justify-center h-64"><div className="text-slate-500">Loading logs...</div></div>;

  return (
    <div className="flex flex-col h-[calc(100vh-8rem)]">
      {/* Header */}
      <div className="flex items-center justify-between pb-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">System Logs</h1>
          <p className="mt-1 text-sm text-slate-500">
            Real-time engine logs across all nodes and pipelines
          </p>
        </div>
        <div className="flex items-center gap-3">
          {/* Level filter */}
          <div className="flex gap-1 rounded-lg bg-slate-100 p-0.5">
            {['all', 'Error', 'Warn', 'Info', 'DEBUG'].map(level => (
              <button
                key={level}
                onClick={() => setLevelFilter(level)}
                className={`rounded-md px-3 py-1 text-xs font-medium transition-colors ${
                  levelFilter === level
                    ? level === 'Error' ? 'bg-red-500 text-white'
                    : level === 'Warn' ? 'bg-amber-500 text-white'
                    : 'bg-white text-slate-900 shadow-sm'
                    : 'text-slate-500 hover:text-slate-700'
                }`}
              >
                {level === 'all' ? 'All' : level}
              </button>
            ))}
          </div>

          {/* Auto-scroll toggle */}
          <button
            onClick={() => setAutoScroll(!autoScroll)}
            className={`rounded-md px-3 py-1.5 text-xs font-medium ${
              autoScroll ? 'bg-vessel-600 text-white' : 'bg-slate-100 text-slate-600'
            }`}
          >
            {autoScroll ? 'Auto-scroll ON' : 'Auto-scroll OFF'}
          </button>

          {/* Pause/Resume */}
          <button
            onClick={() => setPaused(!paused)}
            className={`rounded-md px-3 py-1.5 text-xs font-medium ${
              paused ? 'bg-amber-500 text-white' : 'bg-slate-100 text-slate-600'
            }`}
          >
            {paused ? 'Resume' : 'Pause'}
          </button>

          <span className="text-xs text-slate-400">{filteredLogs.length} entries</span>
        </div>
      </div>

      {/* Log table */}
      <div className="flex-1 overflow-auto rounded-lg border border-slate-200 bg-white">
        <div className="min-w-full">
          {/* Sticky header */}
          <div className="sticky top-0 z-10 grid grid-cols-[140px_60px_120px_180px_1fr_80px] gap-2 bg-slate-50 px-4 py-2 text-[10px] font-semibold uppercase tracking-wider text-slate-500 border-b border-slate-200">
            <div>Timestamp</div>
            <div>Level</div>
            <div>Event Code</div>
            <div>Pipeline / Step</div>
            <div>Message</div>
            <div>Node</div>
          </div>

          {/* Log rows */}
          {filteredLogs.map(log => {
            const colors = levelColors[log.event_type] || levelColors.Info;
            return (
              <div
                key={log.id}
                className={`grid grid-cols-[140px_60px_120px_180px_1fr_80px] gap-2 px-4 py-1.5 text-xs border-l-2 border-b border-slate-100 hover:bg-slate-50 transition-colors ${colors.border}`}
              >
                <div className="font-mono text-slate-400">{formatTime(log.created_at)}</div>
                <div>
                  <span className={`inline-block rounded px-1.5 py-0.5 text-[10px] font-bold ${colors.bg} ${colors.text}`}>
                    {log.event_type}
                  </span>
                </div>
                <div className="font-mono text-slate-600 truncate">{log.event_code}</div>
                <div className="truncate">
                  {log.pipeline_name && (
                    <span className="text-slate-700">{log.pipeline_name}</span>
                  )}
                  {log.step_type && (
                    <span className="ml-1 rounded bg-slate-100 px-1 py-0.5 text-[10px] text-slate-500">
                      {log.step_type}
                    </span>
                  )}
                  {!log.pipeline_name && !log.step_type && (
                    <span className="text-slate-300">system</span>
                  )}
                </div>
                <div className="text-slate-700 truncate" title={log.message}>{log.message}</div>
                <div className="font-mono text-slate-400 truncate">{log.node_id || '-'}</div>
              </div>
            );
          })}
          <div ref={logEndRef} />
        </div>
      </div>
    </div>
  );
}
