import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';

import { StageType } from '../types';
import type { Recipe } from '../types';

// ============================================================
// Types
// ============================================================

type OnErrorAction = 'STOP' | 'SKIP' | 'RETRY';
type BulletinLevel = 'DEBUG' | 'INFO' | 'WARN' | 'ERROR';
type TabId = 'SETTINGS' | 'PROPERTIES' | 'RECIPE';

interface ProcessSettings {
  name: string;
  is_enabled: boolean;
  on_error: OnErrorAction;
  retry_count: number;
  retry_delay_seconds: number;
  penalty_duration: string;
  yield_duration: string;
  bulletin_level: BulletinLevel;
}

interface ProcessorConfigProps {
  stageId: number;
  refId: number;
  stageType: StageType;
  processorName?: string;
  connectorCode?: string;
  initialTab?: 'SETTINGS' | 'RECIPE';
  processSettings?: ProcessSettings;
  onClose: () => void;
  onSaveSettings?: (settings: ProcessSettings) => void;
  onSaveRecipe?: (config: unknown, changeNote: string) => void;
}

// Backward compat: old prop shape still works
interface RecipeEditorPanelProps extends ProcessorConfigProps {}

// ============================================================
// Constants
// ============================================================

const DEFAULT_SETTINGS: ProcessSettings = {
  name: 'Unnamed Processor',
  is_enabled: true,
  on_error: 'STOP',
  retry_count: 3,
  retry_delay_seconds: 10,
  penalty_duration: '30s',
  yield_duration: '1s',
  bulletin_level: 'WARN',
};

const TAB_CONFIG: Record<TabId, { label: string; headerClass: string; borderClass: string }> = {
  SETTINGS: { label: 'Settings', headerClass: 'bg-slate-600', borderClass: 'border-slate-500' },
  PROPERTIES: { label: 'Properties', headerClass: 'bg-blue-600', borderClass: 'border-blue-500' },
  RECIPE: { label: 'Recipe', headerClass: 'bg-purple-600', borderClass: 'border-purple-500' },
};

// Demo recipe versions (inline view in pipeline designer)
const demoRecipeVersions: Recipe[] = [
  { version_no: 3, config_json: { threshold: 3.5, method: 'modified-z-score', window_size: 200, sensitivity: 'high' }, change_note: 'Switch to modified z-score', is_current: true, created_by: 'operator:alex', created_at: '2026-03-16T10:15:00Z' },
  { version_no: 2, config_json: { threshold: 3.0, method: 'z-score', window_size: 100 }, change_note: 'Threshold 3.0으로 상향', is_current: false, created_by: 'operator:kim', created_at: '2026-03-15T14:30:00Z' },
  { version_no: 1, config_json: { threshold: 2.5, method: 'z-score', window_size: 100 }, change_note: '초기 설정', is_current: false, created_by: 'admin', created_at: '2026-03-01T09:00:00Z' },
];

const STAGE_META: Record<StageType, { label: string; color: string }> = {
  [StageType.COLLECT]: { label: 'Collector', color: 'blue' },
  [StageType.PROCESS]: { label: 'Process', color: 'purple' },
  [StageType.EXPORT]: { label: 'Export', color: 'emerald' },
};

// ============================================================
// Demo data (same schemas, used when no live API)
// ============================================================

// Processor Properties = HOW the processor works (goes into SETTINGS tab)
// These are stable, processor-type-specific configuration
type PropertyDef = { key: string; label: string; type: string; value: string; tooltip: string; options?: string[]; group?: string };

// Connector-specific properties (loaded based on connectorCode)
const connectorProperties: Record<string, { label: string; properties: PropertyDef[] }> = {
  'ftp-sftp-collector': {
    label: 'FTP/SFTP Connection',
    properties: [
      { key: 'protocol', label: 'Protocol', type: 'select', value: 'SFTP', tooltip: 'FTP (plain, port 21), FTPS (FTP over TLS, port 990), SFTP (SSH File Transfer, port 22)', options: ['FTP', 'FTPS', 'SFTP'], group: 'Connection' },
      { key: 'host', label: 'Host', type: 'text', value: '192.168.1.100', tooltip: 'FTP/SFTP server hostname or IP address', group: 'Connection' },
      { key: 'port', label: 'Port', type: 'number', value: '22', tooltip: 'Server port. FTP=21, FTPS=990, SFTP=22. Set 0 for protocol default', group: 'Connection' },
      { key: 'username', label: 'Username', type: 'text', value: 'hermes', tooltip: 'Authentication username', group: 'Connection' },
      { key: 'password', label: 'Password', type: 'password', value: '••••••••', tooltip: 'Authentication password. For SFTP key auth, leave empty', group: 'Connection' },
      { key: 'private_key_path', label: 'Private Key Path', type: 'text', value: '', tooltip: 'SSH private key file path (SFTP only). Takes precedence over password', group: 'Connection' },
      { key: 'passive_mode', label: 'Passive Mode', type: 'select', value: 'true', tooltip: 'Use passive mode for FTP/FTPS. Required behind NAT/firewall. Always true for cloud servers', options: ['true', 'false'], group: 'Connection' },
      { key: 'host_key_checking', label: 'Host Key Check', type: 'select', value: 'true', tooltip: 'Verify SSH host key on SFTP. Disable only for testing', options: ['true', 'false'], group: 'Connection' },
      { key: 'poll_interval', label: 'Poll Interval', type: 'text', value: '5m', tooltip: 'How often to scan for new files. Examples: 30s, 5m, 1h. Min 10s', group: 'Polling' },
      { key: 'connection_timeout', label: 'Connect Timeout (sec)', type: 'number', value: '30', tooltip: 'Max time to wait for connection. Triggers retry with backoff if exceeded', group: 'Polling' },
      { key: 'data_timeout', label: 'Data Timeout (sec)', type: 'number', value: '60', tooltip: 'Max time to wait for data transfer response (listing + download)', group: 'Polling' },
      { key: 'max_concurrent', label: 'Max Concurrent Downloads', type: 'number', value: '4', tooltip: 'Simultaneous downloads. Higher = faster but more server load', group: 'Polling' },
      { key: 'retry_max_attempts', label: 'Max Retry Attempts', type: 'number', value: '5', tooltip: 'Retries for transient failures. Uses exponential backoff: delay × 2^attempt ± 25% jitter', group: 'Resilience' },
      { key: 'retry_base_delay', label: 'Retry Base Delay (sec)', type: 'number', value: '2', tooltip: 'Base delay for backoff. Actual delays: 2s → 4s → 8s → 16s → 32s...', group: 'Resilience' },
      { key: 'retry_max_delay', label: 'Max Retry Delay (sec)', type: 'number', value: '300', tooltip: 'Cap on retry delay. Backoff never exceeds this', group: 'Resilience' },
      { key: 'cb_threshold', label: 'Circuit Breaker Threshold', type: 'number', value: '5', tooltip: 'Consecutive failures before circuit opens (stops retrying). 0 = disable', group: 'Resilience' },
      { key: 'cb_recovery', label: 'CB Recovery Time (sec)', type: 'number', value: '300', tooltip: 'Wait time in OPEN state before probe attempt (HALF_OPEN)', group: 'Resilience' },
    ],
  },
  'kafka-consumer': {
    label: 'Kafka Consumer',
    properties: [
      { key: 'bootstrap_servers', label: 'Bootstrap Servers', type: 'text', value: 'localhost:9092', tooltip: 'Comma-separated list of broker addresses', group: 'Connection' },
      { key: 'group_id', label: 'Consumer Group', type: 'text', value: 'hermes-collect', tooltip: 'Consumer group ID. Shared across instances for load balancing', group: 'Connection' },
      { key: 'topics', label: 'Topics', type: 'text', value: 'equipment-data', tooltip: 'Comma-separated topic names to subscribe to', group: 'Connection' },
      { key: 'security_protocol', label: 'Security Protocol', type: 'select', value: 'PLAINTEXT', tooltip: 'Kafka security protocol', options: ['PLAINTEXT', 'SSL', 'SASL_PLAINTEXT', 'SASL_SSL'], group: 'Connection' },
      { key: 'auto_offset_reset', label: 'Auto Offset Reset', type: 'select', value: 'latest', tooltip: 'Where to start reading if no committed offset exists', options: ['earliest', 'latest'], group: 'Consumer' },
      { key: 'poll_timeout_ms', label: 'Poll Timeout (ms)', type: 'number', value: '1000', tooltip: 'Max time to block waiting for messages per poll', group: 'Consumer' },
      { key: 'max_poll_records', label: 'Max Poll Records', type: 'number', value: '500', tooltip: 'Max records returned per poll call', group: 'Consumer' },
    ],
  },
  'rest-api-collector': {
    label: 'REST API Collector',
    properties: [
      { key: 'url', label: 'API URL', type: 'text', value: 'https://api.vendor.com/v2/data', tooltip: 'REST API endpoint URL', group: 'Endpoint' },
      { key: 'method', label: 'HTTP Method', type: 'select', value: 'GET', tooltip: 'HTTP method for requests', options: ['GET', 'POST', 'PUT'], group: 'Endpoint' },
      { key: 'auth_type', label: 'Authentication', type: 'select', value: 'bearer', tooltip: 'Authentication method', options: ['none', 'bearer', 'basic', 'api_key'], group: 'Endpoint' },
      { key: 'auth_token', label: 'Auth Token', type: 'password', value: '••••••••', tooltip: 'Authentication token or API key', group: 'Endpoint' },
      { key: 'poll_interval', label: 'Poll Interval', type: 'text', value: '5m', tooltip: 'How often to poll. Examples: 30s, 5m, 1h', group: 'Polling' },
      { key: 'timeout', label: 'Timeout (sec)', type: 'number', value: '30', tooltip: 'Request timeout in seconds', group: 'Polling' },
      { key: 'records_path', label: 'Records Path', type: 'text', value: 'data.items', tooltip: 'Dot-notation path to records array in response JSON (e.g., data.items, results)', group: 'Parsing' },
    ],
  },
  'database-poller': {
    label: 'Database CDC',
    properties: [
      { key: 'connection_string', label: 'Connection String', type: 'password', value: '••••••••', tooltip: 'Database connection string', group: 'Connection' },
      { key: 'table_name', label: 'Table Name', type: 'text', value: 'orders', tooltip: 'Table to poll for changes', group: 'Query' },
      { key: 'cursor_column', label: 'Cursor Column', type: 'text', value: 'updated_at', tooltip: 'Column for tracking changes (timestamp or sequence)', group: 'Query' },
      { key: 'poll_interval', label: 'Poll Interval', type: 'text', value: '1m', tooltip: 'How often to check for changes', group: 'Query' },
      { key: 'batch_size', label: 'Batch Size', type: 'number', value: '100', tooltip: 'Max rows per poll', group: 'Query' },
    ],
  },
  'kafka-producer': {
    label: 'Kafka Producer',
    properties: [
      { key: 'bootstrap_servers', label: 'Bootstrap Servers', type: 'text', value: 'localhost:9092', tooltip: 'Comma-separated broker addresses', group: 'Connection' },
      { key: 'topic', label: 'Topic', type: 'text', value: 'output-events', tooltip: 'Target Kafka topic', group: 'Connection' },
      { key: 'key_field', label: 'Key Field', type: 'text', value: '', tooltip: 'JSON field to use as message key (for partitioning). Empty = no key', group: 'Publishing' },
      { key: 'acks', label: 'Acks', type: 'select', value: 'all', tooltip: '0: fire-and-forget, 1: leader ack, all: full ISR ack', options: ['0', '1', 'all'], group: 'Publishing' },
      { key: 'compression', label: 'Compression', type: 'select', value: 'none', tooltip: 'Message compression', options: ['none', 'gzip', 'snappy', 'lz4', 'zstd'], group: 'Publishing' },
      { key: 'enable_idempotence', label: 'Idempotent', type: 'select', value: 'true', tooltip: 'Exactly-once delivery semantics', options: ['true', 'false'], group: 'Publishing' },
    ],
  },
  'db-writer': {
    label: 'Database Writer',
    properties: [
      { key: 'connection_string', label: 'Connection String', type: 'password', value: '••••••••', tooltip: 'Database connection string', group: 'Connection' },
      { key: 'provider', label: 'Provider', type: 'select', value: 'PostgreSQL', tooltip: 'Database type', options: ['PostgreSQL', 'SqlServer'], group: 'Connection' },
      { key: 'table_name', label: 'Table Name', type: 'text', value: 'output_data', tooltip: 'Target table for writing', group: 'Write' },
      { key: 'write_mode', label: 'Write Mode', type: 'select', value: 'INSERT', tooltip: 'INSERT: append, UPSERT: insert or update on conflict, MERGE: full merge', options: ['INSERT', 'UPSERT', 'MERGE'], group: 'Write' },
      { key: 'conflict_key', label: 'Conflict Key', type: 'text', value: 'id', tooltip: 'Column for UPSERT conflict detection', group: 'Write' },
      { key: 'batch_size', label: 'Batch Size', type: 'number', value: '1000', tooltip: 'Records per batch insert', group: 'Write' },
      { key: 'timeout_seconds', label: 'Timeout (sec)', type: 'number', value: '30', tooltip: 'Query timeout', group: 'Write' },
    ],
  },
  'webhook-sender': {
    label: 'Webhook Sender',
    properties: [
      { key: 'url', label: 'Webhook URL', type: 'text', value: 'https://api.partner.com/webhook', tooltip: 'Target webhook endpoint', group: 'Endpoint' },
      { key: 'method', label: 'Method', type: 'select', value: 'POST', tooltip: 'HTTP method', options: ['POST', 'PUT', 'PATCH'], group: 'Endpoint' },
      { key: 'auth_type', label: 'Authentication', type: 'select', value: 'none', tooltip: 'Auth method', options: ['none', 'bearer', 'basic', 'api_key'], group: 'Endpoint' },
      { key: 'auth_token', label: 'Auth Token', type: 'password', value: '', tooltip: 'Token or API key', group: 'Endpoint' },
      { key: 'timeout_seconds', label: 'Timeout (sec)', type: 'number', value: '30', tooltip: 'Request timeout', group: 'Delivery' },
      { key: 'max_retries', label: 'Max Retries', type: 'number', value: '3', tooltip: 'Retry count with exponential backoff', group: 'Delivery' },
      { key: 'batch_mode', label: 'Batch Mode', type: 'select', value: 'false', tooltip: 'Send all records in one request vs individually', options: ['true', 'false'], group: 'Delivery' },
    ],
  },
};

const processorProperties: Record<StageType, { label: string; properties: PropertyDef[] }> = {
  [StageType.COLLECT]: {
    label: 'Collector Properties',
    properties: [
      { key: 'url', label: 'API URL', type: 'text', value: 'https://vendor-a.com/api/orders', tooltip: 'The REST API endpoint to poll' },
      { key: 'method', label: 'HTTP Method', type: 'select', value: 'GET', tooltip: 'HTTP method for requests', options: ['GET', 'POST', 'PUT'] },
      { key: 'interval', label: 'Poll Interval', type: 'text', value: '5m', tooltip: 'How often to check for new data (e.g. 30s, 5m, 1h)' },
      { key: 'timeout', label: 'Timeout (seconds)', type: 'number', value: '30', tooltip: 'Request timeout in seconds' },
      { key: 'auth_type', label: 'Authentication', type: 'select', value: 'bearer', tooltip: 'Authentication method', options: ['none', 'bearer', 'basic', 'api_key'] },
      { key: 'auth_token', label: 'Auth Token', type: 'password', value: '••••••••', tooltip: 'Authentication token or API key' },
    ],
  },
  [StageType.PROCESS]: {
    label: 'Process Properties',
    properties: [
      { key: 'execution_type', label: 'Execution Type', type: 'select', value: 'plugin', tooltip: 'How this algorithm is executed', options: ['plugin', 'script', 'http', 'docker'] },
      { key: 'execution_ref', label: 'Execution Reference', type: 'text', value: 'ALGORITHM:anomaly-detector', tooltip: 'Plugin or script reference' },
      { key: 'max_execution_time', label: 'Max Execution Time', type: 'text', value: '300s', tooltip: 'Maximum time before timeout' },
      { key: 'input_format', label: 'Input Format', type: 'select', value: 'json', tooltip: 'Expected input data format', options: ['json', 'csv', 'raw'] },
    ],
  },
  [StageType.EXPORT]: {
    label: 'Export Properties',
    properties: [
      { key: 'destination_type', label: 'Destination Type', type: 'select', value: 's3', tooltip: 'Where to send processed data', options: ['s3', 'database', 'webhook', 'file', 'elasticsearch'] },
      { key: 'bucket', label: 'S3 Bucket', type: 'text', value: 'my-data-bucket', tooltip: 'Target S3 bucket name' },
      { key: 'prefix', label: 'Key Prefix', type: 'text', value: 'results/', tooltip: 'Prefix for S3 object keys' },
      { key: 'format', label: 'Output Format', type: 'select', value: 'json', tooltip: 'Output data format', options: ['json', 'csv', 'parquet'] },
      { key: 'compression', label: 'Compression', type: 'select', value: 'gzip', tooltip: 'Compression algorithm', options: ['none', 'gzip', 'snappy', 'zstd'] },
      { key: 'connection_string', label: 'Connection String', type: 'password', value: '••••••••', tooltip: 'Database or service connection string' },
    ],
  },
};

// ============================================================
// NiFi-style Property Table Row
// ============================================================

interface PropertyRowProps {
  label: string;
  tooltip?: string;
  even: boolean;
  children: React.ReactNode;
}

function PropertyRow({ label, tooltip, even, children }: PropertyRowProps) {
  return (
    <div className={`flex items-center border-b border-slate-200 ${even ? 'bg-slate-50' : 'bg-white'}`}>
      <div className="flex w-[180px] shrink-0 items-center gap-1.5 border-r border-slate-200 px-3 py-2.5">
        {tooltip && (
          <span className="cursor-help text-slate-400" title={tooltip}>
            <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" d="M11.25 11.25l.041-.02a.75.75 0 011.063.852l-.708 2.836a.75.75 0 001.063.853l.041-.021M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-9-3.75h.008v.008H12V8.25z" />
            </svg>
          </span>
        )}
        <span className="text-xs font-medium text-slate-700">{label}</span>
      </div>
      <div className="min-w-0 flex-1 px-3 py-2">{children}</div>
    </div>
  );
}

// ============================================================
// Settings Tab
// ============================================================

function SettingsTab({
  settings,
  onChange,
  onSave,
}: {
  settings: ProcessSettings;
  onChange: (s: ProcessSettings) => void;
  onSave?: (s: ProcessSettings) => void;
}) {
  const update = <K extends keyof ProcessSettings>(key: K, value: ProcessSettings[K]) => {
    onChange({ ...settings, [key]: value });
  };

  const rows: { label: string; tooltip: string; render: () => React.ReactNode }[] = [
    {
      label: 'Name',
      tooltip: 'Display name for this processor instance',
      render: () => (
        <input className="w-full rounded border border-slate-300 px-2 py-1 text-xs" value={settings.name} onChange={(e) => update('name', e.target.value)} />
      ),
    },
    {
      label: 'Enabled',
      tooltip: 'Whether this processor is active in the pipeline',
      render: () => (
        <button
          onClick={() => update('is_enabled', !settings.is_enabled)}
          className={`rounded px-3 py-1 text-xs font-medium ${settings.is_enabled ? 'bg-green-100 text-green-700' : 'bg-slate-200 text-slate-500'}`}
        >
          {settings.is_enabled ? 'Enabled' : 'Disabled'}
        </button>
      ),
    },
    {
      label: 'On Error',
      tooltip: 'Action when processing fails: STOP halts the pipeline, SKIP moves to next item, RETRY attempts again',
      render: () => (
        <select className="rounded border border-slate-300 px-2 py-1 text-xs" value={settings.on_error} onChange={(e) => update('on_error', e.target.value as OnErrorAction)}>
          <option value="STOP">STOP</option>
          <option value="SKIP">SKIP</option>
          <option value="RETRY">RETRY</option>
        </select>
      ),
    },
    {
      label: 'Retry Count',
      tooltip: 'Number of retry attempts before marking as failed',
      render: () => (
        <input type="number" min={0} max={100} className="w-20 rounded border border-slate-300 px-2 py-1 text-xs" value={settings.retry_count} onChange={(e) => update('retry_count', parseInt(e.target.value) || 0)} />
      ),
    },
    {
      label: 'Retry Delay',
      tooltip: 'Seconds to wait between retry attempts',
      render: () => (
        <div className="flex items-center gap-1">
          <input type="number" min={0} className="w-20 rounded border border-slate-300 px-2 py-1 text-xs" value={settings.retry_delay_seconds} onChange={(e) => update('retry_delay_seconds', parseInt(e.target.value) || 0)} />
          <span className="text-[10px] text-slate-400">sec</span>
        </div>
      ),
    },
    {
      label: 'Penalty Duration',
      tooltip: 'Time a processor is penalized after a failure before accepting new work',
      render: () => (
        <input className="w-24 rounded border border-slate-300 px-2 py-1 text-xs" value={settings.penalty_duration} onChange={(e) => update('penalty_duration', e.target.value)} />
      ),
    },
    {
      label: 'Yield Duration',
      tooltip: 'Time the processor yields when it has no work to do',
      render: () => (
        <input className="w-24 rounded border border-slate-300 px-2 py-1 text-xs" value={settings.yield_duration} onChange={(e) => update('yield_duration', e.target.value)} />
      ),
    },
    {
      label: 'Bulletin Level',
      tooltip: 'Minimum severity level for bulletin board messages',
      render: () => (
        <select className="rounded border border-slate-300 px-2 py-1 text-xs" value={settings.bulletin_level} onChange={(e) => update('bulletin_level', e.target.value as BulletinLevel)}>
          <option value="DEBUG">DEBUG</option>
          <option value="INFO">INFO</option>
          <option value="WARN">WARN</option>
          <option value="ERROR">ERROR</option>
        </select>
      ),
    },
  ];

  return (
    <div className="flex flex-col gap-4 p-4">
      <div className="overflow-hidden rounded-lg border border-slate-200">
        <div className="flex border-b border-slate-300 bg-slate-100">
          <div className="w-[180px] shrink-0 border-r border-slate-300 px-3 py-2 text-[10px] font-bold uppercase tracking-wider text-slate-500">Property</div>
          <div className="flex-1 px-3 py-2 text-[10px] font-bold uppercase tracking-wider text-slate-500">Value</div>
        </div>
        {rows.map((row, idx) => (
          <PropertyRow key={row.label} label={row.label} tooltip={row.tooltip} even={idx % 2 === 0}>
            {row.render()}
          </PropertyRow>
        ))}
      </div>
      {onSave && (
        <button onClick={() => onSave(settings)} className="btn-primary w-full justify-center">
          Apply Settings
        </button>
      )}
    </div>
  );
}


// ============================================================
// JSON Config Editor (Advanced mode for connector settings)
// ============================================================

function JsonConfigEditor({ connectorCode, properties }: { connectorCode?: string; properties: PropertyDef[] }) {
  // Build initial JSON from properties
  const initialJson = useMemo(() => {
    const obj: Record<string, unknown> = {};
    for (const p of properties) {
      if (p.type === 'number') obj[p.key] = Number(p.value) || 0;
      else if (p.value === 'true') obj[p.key] = true;
      else if (p.value === 'false') obj[p.key] = false;
      else obj[p.key] = p.value;
    }
    return JSON.stringify(obj, null, 2);
  }, [properties]);

  const [jsonText, setJsonText] = useState(initialJson);
  const [isEditing, setIsEditing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  function handleValidate(text: string) {
    try {
      JSON.parse(text);
      setError(null);
      return true;
    } catch (e) {
      setError((e as Error).message);
      return false;
    }
  }

  function handleSave() {
    if (handleValidate(jsonText)) {
      // Format the JSON
      try {
        const parsed = JSON.parse(jsonText);
        setJsonText(JSON.stringify(parsed, null, 2));
      } catch { /* keep as-is */ }
      setIsEditing(false);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    }
  }

  function handleCancel() {
    setJsonText(initialJson);
    setError(null);
    setIsEditing(false);
  }

  return (
    <div className="mt-4">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className="text-[10px] font-bold uppercase tracking-wider text-slate-500">
            JSON Config
          </span>
          {connectorCode && (
            <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[9px] font-mono text-slate-500">
              {connectorCode}
            </span>
          )}
        </div>
        <div className="flex items-center gap-1">
          {saved && (
            <span className="text-[10px] font-medium text-green-600">Saved</span>
          )}
          {isEditing ? (
            <>
              <button
                onClick={handleCancel}
                className="rounded border border-slate-200 px-2 py-0.5 text-[10px] font-medium text-slate-500 hover:bg-slate-50"
              >
                Cancel
              </button>
              <button
                onClick={handleSave}
                className="rounded border border-blue-200 bg-blue-50 px-2 py-0.5 text-[10px] font-medium text-blue-700 hover:bg-blue-100"
              >
                Apply
              </button>
            </>
          ) : (
            <button
              onClick={() => setIsEditing(true)}
              className="rounded border border-slate-200 px-2 py-0.5 text-[10px] font-medium text-slate-500 hover:bg-slate-50"
            >
              Edit JSON
            </button>
          )}
        </div>
      </div>

      {isEditing ? (
        <div>
          <textarea
            value={jsonText}
            onChange={(e) => {
              setJsonText(e.target.value);
              handleValidate(e.target.value);
            }}
            spellCheck={false}
            className={`w-full rounded-lg border p-3 font-mono text-[11px] leading-5 focus:outline-none focus:ring-1 ${
              error
                ? 'border-red-300 bg-red-50 text-red-900 focus:ring-red-400'
                : 'border-slate-300 bg-slate-900 text-slate-200 focus:ring-blue-400'
            }`}
            rows={Math.min(20, jsonText.split('\n').length + 2)}
          />
          {error && (
            <div className="mt-1 flex items-center gap-1 text-[10px] text-red-600">
              <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
              </svg>
              {error}
            </div>
          )}
        </div>
      ) : (
        <JsonPreview data={JSON.parse(jsonText)} />
      )}
    </div>
  );
}

// ============================================================
// Main Panel Component
// ============================================================

export default function RecipeEditorPanel({
  stageType,
  processorName,
  connectorCode,
  initialTab,
  processSettings: initialSettings,
  onClose,
  onSaveSettings,
}: RecipeEditorPanelProps) {
  const [activeTab, setActiveTab] = useState<TabId>(initialTab ?? 'SETTINGS');
  const [settings, setSettings] = useState<ProcessSettings>(initialSettings ?? DEFAULT_SETTINGS);

  const stageMeta = STAGE_META[stageType];

  // Use connector-specific properties if available, fallback to generic
  const connectorProps = connectorCode && connectorProperties[connectorCode]
    ? connectorProperties[connectorCode]
    : processorProperties[stageType];

  useEffect(() => {
    if (initialSettings) setSettings(initialSettings);
  }, [stageType]);

  const tabStyle = TAB_CONFIG[activeTab];

  return (
    <div className="flex w-[480px] flex-col border-l border-slate-200 bg-white">
      {/* Panel Header */}
      <div className={`flex items-center justify-between px-4 py-3 text-white ${tabStyle.headerClass}`}>
        <div>
          <div className="flex items-center gap-2">
            <span className="inline-block h-2 w-2 rounded-full bg-white/60" />
            <h3 className="text-sm font-semibold">
              {processorName ?? stageMeta.label}
            </h3>
          </div>
          <p className="mt-0.5 text-[11px] text-white/70">
            {stageMeta.label} Processor Settings
          </p>
        </div>
        <button
          onClick={onClose}
          className="rounded-lg p-1.5 text-white/70 transition-colors hover:bg-white/10 hover:text-white"
        >
          <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      {/* Tab Bar */}
      <div className="flex border-b border-slate-200 bg-slate-50">
        {(Object.entries(TAB_CONFIG) as [TabId, typeof TAB_CONFIG[TabId]][]).map(([id, cfg]) => (
          <button
            key={id}
            onClick={() => setActiveTab(id)}
            className={`relative flex-1 px-4 py-2.5 text-xs font-semibold uppercase tracking-wider transition-colors ${
              activeTab === id
                ? 'bg-white text-slate-800'
                : 'text-slate-500 hover:text-slate-700'
            }`}
          >
            {cfg.label}
            {activeTab === id && (
              <span className={`absolute bottom-0 left-0 right-0 h-0.5 ${cfg.headerClass}`} />
            )}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      <div className="flex-1 overflow-auto">
        {activeTab === 'SETTINGS' && (
          <SettingsTab settings={settings} onChange={setSettings} onSave={onSaveSettings} />
        )}
        {activeTab === 'PROPERTIES' && (
          <div className="p-4">
            {/* Render properties grouped if groups exist */}
            {(() => {
              const props = connectorProps.properties;
              const groups = [...new Set(props.map(p => p.group).filter(Boolean))];
              const hasGroups = groups.length > 0;

              if (hasGroups) {
                return groups.map(group => {
                  const groupProps = props.filter(p => p.group === group);
                  return (
                    <div key={group} className="mb-4">
                      <div className="overflow-hidden rounded-lg border border-slate-200">
                        <div className="flex border-b border-slate-300 bg-blue-50">
                          <div className="w-[180px] shrink-0 border-r border-blue-200 px-3 py-2 text-[10px] font-bold uppercase tracking-wider text-blue-700">
                            {group}
                          </div>
                          <div className="flex-1 px-3 py-2 text-[10px] font-bold uppercase tracking-wider text-blue-700">Value</div>
                        </div>
                        {groupProps.map((prop, idx) => (
                          <PropertyRow key={prop.key} label={prop.label} tooltip={prop.tooltip} even={idx % 2 === 0}>
                            {prop.type === 'select' ? (
                              <select className="rounded border border-slate-300 px-2 py-1 text-xs" defaultValue={prop.value}>
                                {prop.options?.map(o => <option key={o} value={o}>{o}</option>)}
                              </select>
                            ) : prop.type === 'password' ? (
                              <input type="password" className="w-full rounded border border-slate-300 px-2 py-1 text-xs" defaultValue={prop.value} />
                            ) : prop.type === 'number' ? (
                              <input type="number" className="w-20 rounded border border-slate-300 px-2 py-1 text-xs" defaultValue={prop.value} />
                            ) : (
                              <input type="text" className="w-full rounded border border-slate-300 px-2 py-1 text-xs" defaultValue={prop.value} />
                            )}
                          </PropertyRow>
                        ))}
                      </div>
                    </div>
                  );
                });
              }

              // Flat (no groups)
              return (
                <div className="overflow-hidden rounded-lg border border-slate-200">
                  <div className="flex border-b border-slate-300 bg-blue-50">
                    <div className="w-[180px] shrink-0 border-r border-blue-200 px-3 py-2 text-[10px] font-bold uppercase tracking-wider text-blue-700">
                      {connectorProps.label}
                    </div>
                    <div className="flex-1 px-3 py-2 text-[10px] font-bold uppercase tracking-wider text-blue-700">Value</div>
                  </div>
                  {props.map((prop, idx) => (
                    <PropertyRow key={prop.key} label={prop.label} tooltip={prop.tooltip} even={idx % 2 === 0}>
                      {prop.type === 'select' ? (
                        <select className="rounded border border-slate-300 px-2 py-1 text-xs" defaultValue={prop.value}>
                          {prop.options?.map(o => <option key={o} value={o}>{o}</option>)}
                        </select>
                      ) : prop.type === 'password' ? (
                        <input type="password" className="w-full rounded border border-slate-300 px-2 py-1 text-xs" defaultValue={prop.value} />
                      ) : prop.type === 'number' ? (
                        <input type="number" className="w-20 rounded border border-slate-300 px-2 py-1 text-xs" defaultValue={prop.value} />
                      ) : (
                        <input type="text" className="w-full rounded border border-slate-300 px-2 py-1 text-xs" defaultValue={prop.value} />
                      )}
                    </PropertyRow>
                  ))}
                </div>
              );
            })()}

            {/* JSON Config Editor */}
            <JsonConfigEditor
              connectorCode={connectorCode}
              properties={connectorProps.properties}
            />
          </div>
        )}
        {activeTab === 'RECIPE' && (
          <RecipeInlineTab versions={demoRecipeVersions} />
        )}
      </div>
    </div>
  );
}

// ============================================================
// Inline Recipe Tab (shown inside pipeline designer panel)
// ============================================================

function JsonPreview({ data }: { data: unknown }) {
  const highlighted = useMemo(() => {
    const raw = JSON.stringify(data, null, 2);
    return raw
      .replace(/("(?:\\.|[^"\\])*")\s*:/g, '<span class="text-purple-400">$1</span>:')
      .replace(/:\s*("(?:\\.|[^"\\])*")/g, ': <span class="text-green-400">$1</span>')
      .replace(/:\s*(\d+\.?\d*)/g, ': <span class="text-blue-400">$1</span>')
      .replace(/:\s*(true|false|null)/g, ': <span class="text-amber-400">$1</span>');
  }, [data]);
  return (
    <pre
      className="overflow-auto rounded-lg bg-slate-900 p-3 font-mono text-[11px] leading-5 text-slate-300"
      dangerouslySetInnerHTML={{ __html: highlighted }}
    />
  );
}

function RecipeInlineTab({ versions }: { versions: Recipe[] }) {
  const [selectedIdx, setSelectedIdx] = useState(0);
  const current = versions[selectedIdx];

  return (
    <div className="flex h-full">
      {/* Version list (left) */}
      <div className="w-[130px] shrink-0 overflow-auto border-r border-slate-200 bg-slate-50">
        <div className="border-b border-slate-200 p-2">
          <Link
            to="/recipes"
            className="flex w-full items-center justify-center gap-1 rounded border border-purple-200 bg-purple-50 px-2 py-1.5 text-[10px] font-medium text-purple-700 hover:bg-purple-100"
          >
            <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 6H5.25A2.25 2.25 0 003 8.25v10.5A2.25 2.25 0 005.25 21h10.5A2.25 2.25 0 0018 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25" />
            </svg>
            Manage All
          </Link>
        </div>
        {versions.map((v, idx) => (
          <button
            key={v.version_no}
            onClick={() => setSelectedIdx(idx)}
            className={`flex w-full flex-col border-b border-slate-200 px-3 py-2 text-left transition-colors ${
              selectedIdx === idx ? 'bg-white shadow-sm' : 'hover:bg-slate-100'
            }`}
          >
            <div className="flex items-center gap-1.5">
              <span className="rounded bg-slate-200 px-1.5 py-0.5 text-[10px] font-bold text-slate-700">v{v.version_no}</span>
              {v.is_current && (
                <span className="rounded-full bg-green-100 px-1.5 py-0.5 text-[9px] font-bold text-green-700">current</span>
              )}
            </div>
            <span className="mt-1 text-[10px] text-slate-500 line-clamp-2">{v.change_note}</span>
            <span className="mt-0.5 text-[9px] text-slate-400">{v.created_by}</span>
          </button>
        ))}
      </div>

      {/* Detail (right) */}
      <div className="flex-1 overflow-auto p-4">
        {current && (
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="rounded bg-slate-700 px-2 py-0.5 text-xs font-bold text-white">v{current.version_no}</span>
                {current.is_current && (
                  <span className="rounded-full bg-green-100 px-2 py-0.5 text-[10px] font-bold text-green-700">current</span>
                )}
              </div>
            </div>
            <div className="space-y-1 text-xs text-slate-600">
              <p><span className="font-medium text-slate-500">Author:</span> {current.created_by}</p>
              <p><span className="font-medium text-slate-500">Date:</span> {new Date(current.created_at).toLocaleString()}</p>
              <p><span className="font-medium text-slate-500">Note:</span> {current.change_note}</p>
            </div>
            <JsonPreview data={current.config_json} />
          </div>
        )}
      </div>
    </div>
  );
}
