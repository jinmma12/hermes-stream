import { useEffect, useMemo, useState } from 'react';

import { StageType } from '../types';

// ============================================================
// Types
// ============================================================

type OnErrorAction = 'STOP' | 'SKIP' | 'RETRY';
type BulletinLevel = 'DEBUG' | 'INFO' | 'WARN' | 'ERROR';
type TabId = 'SETTINGS' | 'PROPERTIES';

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
  initialTab?: TabId;
  processSettings?: ProcessSettings;
  onClose: () => void;
  onSaveSettings?: (settings: ProcessSettings) => void;
}

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
};

const STAGE_META: Record<StageType, { label: string; color: string }> = {
  [StageType.COLLECT]: { label: 'Collector', color: 'blue' },
  [StageType.PROCESS]: { label: 'Process', color: 'purple' },
  [StageType.EXPORT]: { label: 'Export', color: 'emerald' },
};

// ============================================================
// Config Layer Definitions per Connector
// Based on FTP_SFTP_COLLECTOR_CONFIG_SPEC.md 3-layer split:
//   settings = connection   → Settings tab
//   recipe   = collection   → Properties tab
//   runtime  = policy       → Settings tab (advanced section)
// ============================================================

type PropertyDef = { key: string; label: string; type: string; value: string; tooltip: string; options?: string[]; group?: string };

interface ConnectorConfig {
  label: string;
  connectionSettings: PropertyDef[];   // → Settings tab, "Connection" section
  runtimePolicy: PropertyDef[];        // → Settings tab, "Runtime Policy" section
  recipeProperties: PropertyDef[];     // → Properties tab, "Collection Recipe" section
}

// ---------- FTP/SFTP ----------
const ftpSftpConfig: ConnectorConfig = {
  label: 'FTP/SFTP Collector',
  connectionSettings: [
    { key: 'protocol', label: 'Protocol', type: 'select', value: 'SFTP', tooltip: 'FTP, FTPS (TLS), or SFTP (SSH)', options: ['FTP', 'FTPS', 'SFTP'], group: 'Connection' },
    { key: 'host', label: 'Host', type: 'text', value: '192.168.1.100', tooltip: 'Server hostname or IP', group: 'Connection' },
    { key: 'port', label: 'Port', type: 'number', value: '22', tooltip: 'FTP=21, FTPS=990, SFTP=22', group: 'Connection' },
    { key: 'username', label: 'Username', type: 'text', value: 'hermes', tooltip: 'Authentication username', group: 'Connection' },
    { key: 'password', label: 'Password', type: 'password', value: '', tooltip: 'Password (SFTP: leave empty for key auth)', group: 'Connection' },
    { key: 'private_key_path', label: 'Private Key Path', type: 'text', value: '', tooltip: 'SSH key path (SFTP only)', group: 'Connection' },
    { key: 'passive_mode', label: 'Passive Mode', type: 'select', value: 'true', tooltip: 'Required behind NAT/firewall (FTP/FTPS only)', options: ['true', 'false'], group: 'Connection' },
    { key: 'host_key_checking', label: 'Host Key Check', type: 'select', value: 'true', tooltip: 'Verify SSH host key (SFTP only)', options: ['true', 'false'], group: 'Connection' },
  ],
  runtimePolicy: [
    { key: 'poll_interval', label: 'Poll Interval', type: 'text', value: '5m', tooltip: 'Scan frequency (30s, 5m, 1h)', group: 'Scheduling' },
    { key: 'connection_timeout', label: 'Connect Timeout (sec)', type: 'number', value: '30', tooltip: 'Max wait for connection', group: 'Scheduling' },
    { key: 'data_timeout', label: 'Data Timeout (sec)', type: 'number', value: '60', tooltip: 'Max wait for data transfer', group: 'Scheduling' },
    { key: 'max_concurrent', label: 'Max Concurrent', type: 'number', value: '4', tooltip: 'Simultaneous downloads', group: 'Scheduling' },
    { key: 'retry_max_attempts', label: 'Retry Attempts', type: 'number', value: '5', tooltip: 'Retries with exponential backoff', group: 'Resilience' },
    { key: 'retry_base_delay', label: 'Retry Base Delay (sec)', type: 'number', value: '2', tooltip: 'Base delay: 2s → 4s → 8s...', group: 'Resilience' },
    { key: 'retry_max_delay', label: 'Max Retry Delay (sec)', type: 'number', value: '300', tooltip: 'Backoff cap', group: 'Resilience' },
    { key: 'cb_threshold', label: 'Circuit Breaker Threshold', type: 'number', value: '5', tooltip: 'Failures before circuit opens', group: 'Resilience' },
    { key: 'cb_recovery', label: 'CB Recovery (sec)', type: 'number', value: '300', tooltip: 'Wait before probe attempt', group: 'Resilience' },
  ],
  recipeProperties: [
    { key: 'remote_path', label: 'Remote Path', type: 'text', value: '/data/incoming', tooltip: 'Root directory for scanning', group: 'Traversal' },
    { key: 'recursive', label: 'Recursive', type: 'select', value: 'true', tooltip: 'Scan subdirectories', options: ['true', 'false'], group: 'Traversal' },
    { key: 'max_depth', label: 'Max Depth', type: 'number', value: '3', tooltip: '0=root, -1=unlimited', group: 'Traversal' },
    { key: 'folder_pattern_enabled', label: 'Date Folders', type: 'select', value: 'true', tooltip: 'Use date-based folder filtering', options: ['true', 'false'], group: 'Folder Pattern' },
    { key: 'folder_pattern_format', label: 'Date Format', type: 'text', value: 'yyyyMMdd', tooltip: 'Date format in folder names', group: 'Folder Pattern' },
    { key: 'folder_pattern_lookback', label: 'Lookback Days', type: 'number', value: '7', tooltip: 'Scan last N days of folders', group: 'Folder Pattern' },
    { key: 'filename_regex', label: 'Filename Pattern', type: 'text', value: 'sensor_.*\\.csv$', tooltip: 'Regex filter on filename', group: 'File Filter' },
    { key: 'path_regex', label: 'Path Pattern', type: 'text', value: '', tooltip: 'Regex filter on full path', group: 'File Filter' },
    { key: 'min_size_bytes', label: 'Min Size (bytes)', type: 'number', value: '100', tooltip: 'Skip files smaller than this', group: 'File Filter' },
    { key: 'max_age_hours', label: 'Max Age (hours)', type: 'number', value: '24', tooltip: 'Skip files older than this', group: 'File Filter' },
    { key: 'exclude_zero_byte', label: 'Exclude Empty', type: 'select', value: 'true', tooltip: 'Skip zero-byte files', options: ['true', 'false'], group: 'File Filter' },
    { key: 'ordering', label: 'Ordering', type: 'select', value: 'NEWEST_FIRST', tooltip: 'File collection order', options: ['NEWEST_FIRST', 'OLDEST_FIRST', 'ALPHABETICAL', 'RANDOM'], group: 'Collection' },
    { key: 'discovery_mode', label: 'Discovery Mode', type: 'select', value: 'ALL_NEW', tooltip: 'ALL=every file, LATEST=newest, ALL_NEW=unseen only', options: ['ALL', 'LATEST', 'BATCH', 'ALL_NEW'], group: 'Collection' },
    { key: 'batch_size', label: 'Batch Size', type: 'number', value: '100', tooltip: 'Max files per poll', group: 'Collection' },
    { key: 'completion_strategy', label: 'Completion Check', type: 'select', value: 'NONE', tooltip: 'How to verify file is fully written', options: ['NONE', 'MARKER_FILE', 'SIZE_STABLE'], group: 'Completion' },
    { key: 'marker_suffix', label: 'Marker Suffix', type: 'text', value: '.done', tooltip: 'Companion file suffix (MARKER_FILE mode)', group: 'Completion' },
    { key: 'stable_seconds', label: 'Stable Seconds', type: 'number', value: '10', tooltip: 'Wait time for size stability (SIZE_STABLE mode)', group: 'Completion' },
    { key: 'post_action', label: 'Post Action', type: 'select', value: 'KEEP', tooltip: 'What to do after collection', options: ['KEEP', 'DELETE', 'MOVE', 'RENAME'], group: 'Post-Collection' },
    { key: 'move_target', label: 'Move Target', type: 'text', value: '/archive', tooltip: 'Target path for MOVE action', group: 'Post-Collection' },
    { key: 'checksum_verification', label: 'Checksum', type: 'select', value: 'true', tooltip: 'Verify file integrity', options: ['true', 'false'], group: 'Post-Collection' },
  ],
};

// ---------- Other connectors (connection + runtime combined, recipe as separate) ----------
const kafkaConsumerConfig: ConnectorConfig = {
  label: 'Kafka Consumer',
  connectionSettings: [
    { key: 'bootstrap_servers', label: 'Bootstrap Servers', type: 'text', value: 'localhost:9092', tooltip: 'Broker addresses', group: 'Connection' },
    { key: 'group_id', label: 'Consumer Group', type: 'text', value: 'hermes-collect', tooltip: 'Consumer group ID', group: 'Connection' },
    { key: 'security_protocol', label: 'Security Protocol', type: 'select', value: 'PLAINTEXT', tooltip: 'Kafka security', options: ['PLAINTEXT', 'SSL', 'SASL_PLAINTEXT', 'SASL_SSL'], group: 'Connection' },
  ],
  runtimePolicy: [
    { key: 'poll_timeout_ms', label: 'Poll Timeout (ms)', type: 'number', value: '1000', tooltip: 'Max wait per poll', group: 'Scheduling' },
    { key: 'max_poll_records', label: 'Max Poll Records', type: 'number', value: '500', tooltip: 'Records per poll', group: 'Scheduling' },
  ],
  recipeProperties: [
    { key: 'topics', label: 'Topics', type: 'text', value: 'equipment-data', tooltip: 'Topic names (comma-separated)', group: 'Subscription' },
    { key: 'auto_offset_reset', label: 'Auto Offset Reset', type: 'select', value: 'latest', tooltip: 'Start position', options: ['earliest', 'latest'], group: 'Subscription' },
  ],
};

const restApiConfig: ConnectorConfig = {
  label: 'REST API Collector',
  connectionSettings: [
    { key: 'auth_type', label: 'Authentication', type: 'select', value: 'bearer', tooltip: 'Auth method', options: ['none', 'bearer', 'basic', 'api_key'], group: 'Connection' },
    { key: 'auth_token', label: 'Auth Token', type: 'password', value: '', tooltip: 'Token or API key', group: 'Connection' },
  ],
  runtimePolicy: [
    { key: 'poll_interval', label: 'Poll Interval', type: 'text', value: '5m', tooltip: 'Poll frequency', group: 'Scheduling' },
    { key: 'timeout', label: 'Timeout (sec)', type: 'number', value: '30', tooltip: 'Request timeout', group: 'Scheduling' },
  ],
  recipeProperties: [
    { key: 'url', label: 'API URL', type: 'text', value: 'https://api.vendor.com/v2/data', tooltip: 'Endpoint URL', group: 'Endpoint' },
    { key: 'method', label: 'HTTP Method', type: 'select', value: 'GET', tooltip: 'HTTP method', options: ['GET', 'POST', 'PUT'], group: 'Endpoint' },
    { key: 'records_path', label: 'Records Path', type: 'text', value: 'data.items', tooltip: 'JSON path to records array', group: 'Parsing' },
  ],
};

const dbPollerConfig: ConnectorConfig = {
  label: 'Database CDC',
  connectionSettings: [
    { key: 'connection_string', label: 'Connection String', type: 'password', value: '', tooltip: 'DB connection string', group: 'Connection' },
  ],
  runtimePolicy: [
    { key: 'poll_interval', label: 'Poll Interval', type: 'text', value: '1m', tooltip: 'Change detection frequency', group: 'Scheduling' },
  ],
  recipeProperties: [
    { key: 'table_name', label: 'Table Name', type: 'text', value: 'orders', tooltip: 'Table to poll', group: 'Query' },
    { key: 'cursor_column', label: 'Cursor Column', type: 'text', value: 'updated_at', tooltip: 'Change tracking column', group: 'Query' },
    { key: 'batch_size', label: 'Batch Size', type: 'number', value: '100', tooltip: 'Max rows per poll', group: 'Query' },
  ],
};

const kafkaProducerConfig: ConnectorConfig = {
  label: 'Kafka Producer',
  connectionSettings: [
    { key: 'bootstrap_servers', label: 'Bootstrap Servers', type: 'text', value: 'localhost:9092', tooltip: 'Broker addresses', group: 'Connection' },
  ],
  runtimePolicy: [],
  recipeProperties: [
    { key: 'topic', label: 'Topic', type: 'text', value: 'output-events', tooltip: 'Target topic', group: 'Publishing' },
    { key: 'key_field', label: 'Key Field', type: 'text', value: '', tooltip: 'Message key field', group: 'Publishing' },
    { key: 'acks', label: 'Acks', type: 'select', value: 'all', tooltip: 'Ack level', options: ['0', '1', 'all'], group: 'Publishing' },
    { key: 'compression', label: 'Compression', type: 'select', value: 'none', tooltip: 'Compression', options: ['none', 'gzip', 'snappy', 'lz4', 'zstd'], group: 'Publishing' },
    { key: 'enable_idempotence', label: 'Idempotent', type: 'select', value: 'true', tooltip: 'Exactly-once semantics', options: ['true', 'false'], group: 'Publishing' },
  ],
};

const dbWriterConfig: ConnectorConfig = {
  label: 'Database Writer',
  connectionSettings: [
    { key: 'connection_string', label: 'Connection String', type: 'password', value: '', tooltip: 'DB connection string', group: 'Connection' },
    { key: 'provider', label: 'Provider', type: 'select', value: 'PostgreSQL', tooltip: 'Database type', options: ['PostgreSQL', 'SqlServer'], group: 'Connection' },
  ],
  runtimePolicy: [
    { key: 'timeout_seconds', label: 'Timeout (sec)', type: 'number', value: '30', tooltip: 'Query timeout', group: 'Scheduling' },
  ],
  recipeProperties: [
    { key: 'table_name', label: 'Table Name', type: 'text', value: 'output_data', tooltip: 'Target table', group: 'Write' },
    { key: 'write_mode', label: 'Write Mode', type: 'select', value: 'INSERT', tooltip: 'INSERT, UPSERT, or MERGE', options: ['INSERT', 'UPSERT', 'MERGE'], group: 'Write' },
    { key: 'conflict_key', label: 'Conflict Key', type: 'text', value: 'id', tooltip: 'UPSERT conflict column', group: 'Write' },
    { key: 'batch_size', label: 'Batch Size', type: 'number', value: '1000', tooltip: 'Records per batch', group: 'Write' },
  ],
};

const webhookConfig: ConnectorConfig = {
  label: 'Webhook Sender',
  connectionSettings: [
    { key: 'auth_type', label: 'Authentication', type: 'select', value: 'none', tooltip: 'Auth method', options: ['none', 'bearer', 'basic', 'api_key'], group: 'Connection' },
    { key: 'auth_token', label: 'Auth Token', type: 'password', value: '', tooltip: 'Token or key', group: 'Connection' },
  ],
  runtimePolicy: [
    { key: 'timeout_seconds', label: 'Timeout (sec)', type: 'number', value: '30', tooltip: 'Request timeout', group: 'Delivery' },
    { key: 'max_retries', label: 'Max Retries', type: 'number', value: '3', tooltip: 'Retry with backoff', group: 'Delivery' },
  ],
  recipeProperties: [
    { key: 'url', label: 'Webhook URL', type: 'text', value: 'https://api.partner.com/webhook', tooltip: 'Target endpoint', group: 'Endpoint' },
    { key: 'method', label: 'Method', type: 'select', value: 'POST', tooltip: 'HTTP method', options: ['POST', 'PUT', 'PATCH'], group: 'Endpoint' },
    { key: 'batch_mode', label: 'Batch Mode', type: 'select', value: 'false', tooltip: 'Send all records in one request', options: ['true', 'false'], group: 'Endpoint' },
  ],
};

const connectorConfigs: Record<string, ConnectorConfig> = {
  'ftp-sftp-collector': ftpSftpConfig,
  'kafka-consumer': kafkaConsumerConfig,
  'rest-api-collector': restApiConfig,
  'database-poller': dbPollerConfig,
  'kafka-producer': kafkaProducerConfig,
  'db-writer': dbWriterConfig,
  'webhook-sender': webhookConfig,
};

// Generic fallback per stage type
const genericConfigs: Record<StageType, ConnectorConfig> = {
  [StageType.COLLECT]: {
    label: 'Collector',
    connectionSettings: [],
    runtimePolicy: [],
    recipeProperties: [
      { key: 'execution_type', label: 'Execution Type', type: 'select', value: 'plugin', tooltip: 'How to execute', options: ['plugin', 'script', 'http'], group: 'Execution' },
      { key: 'execution_ref', label: 'Execution Ref', type: 'text', value: '', tooltip: 'Plugin or script reference', group: 'Execution' },
    ],
  },
  [StageType.PROCESS]: {
    label: 'Process',
    connectionSettings: [],
    runtimePolicy: [],
    recipeProperties: [
      { key: 'execution_type', label: 'Execution Type', type: 'select', value: 'plugin', tooltip: 'How to execute', options: ['plugin', 'script', 'http', 'docker'], group: 'Execution' },
      { key: 'execution_ref', label: 'Execution Ref', type: 'text', value: 'ALGORITHM:anomaly-detector', tooltip: 'Plugin or script reference', group: 'Execution' },
      { key: 'max_execution_time', label: 'Max Execution Time', type: 'text', value: '300s', tooltip: 'Timeout', group: 'Execution' },
      { key: 'input_format', label: 'Input Format', type: 'select', value: 'json', tooltip: 'Expected format', options: ['json', 'csv', 'raw'], group: 'Execution' },
    ],
  },
  [StageType.EXPORT]: {
    label: 'Export',
    connectionSettings: [],
    runtimePolicy: [],
    recipeProperties: [
      { key: 'destination_type', label: 'Destination', type: 'select', value: 's3', tooltip: 'Export target', options: ['s3', 'database', 'webhook', 'file'], group: 'Destination' },
      { key: 'format', label: 'Output Format', type: 'select', value: 'json', tooltip: 'Data format', options: ['json', 'csv', 'parquet'], group: 'Destination' },
      { key: 'compression', label: 'Compression', type: 'select', value: 'gzip', tooltip: 'Compression', options: ['none', 'gzip', 'snappy', 'zstd'], group: 'Destination' },
    ],
  },
};

// ============================================================
// NiFi-style Property Table
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

function renderPropertyInput(prop: PropertyDef) {
  if (prop.type === 'select') {
    return (
      <select className="rounded border border-slate-300 px-2 py-1 text-xs" defaultValue={prop.value}>
        {prop.options?.map(o => <option key={o} value={o}>{o}</option>)}
      </select>
    );
  }
  if (prop.type === 'password') {
    return <input type="password" className="w-full rounded border border-slate-300 px-2 py-1 text-xs" defaultValue={prop.value} />;
  }
  if (prop.type === 'number') {
    return <input type="number" className="w-20 rounded border border-slate-300 px-2 py-1 text-xs" defaultValue={prop.value} />;
  }
  return <input type="text" className="w-full rounded border border-slate-300 px-2 py-1 text-xs" defaultValue={prop.value} />;
}

function PropertyGroup({ title, properties, color = 'slate' }: { title: string; properties: PropertyDef[]; color?: string }) {
  const headerBg = color === 'blue' ? 'bg-blue-50' : color === 'amber' ? 'bg-amber-50' : 'bg-slate-50';
  const headerText = color === 'blue' ? 'text-blue-700' : color === 'amber' ? 'text-amber-700' : 'text-slate-600';
  const headerBorder = color === 'blue' ? 'border-blue-200' : color === 'amber' ? 'border-amber-200' : 'border-slate-300';

  return (
    <div className="mb-3 overflow-hidden rounded-lg border border-slate-200">
      <div className={`flex border-b ${headerBorder} ${headerBg}`}>
        <div className={`w-[180px] shrink-0 border-r ${headerBorder} px-3 py-2 text-[10px] font-bold uppercase tracking-wider ${headerText}`}>
          {title}
        </div>
        <div className={`flex-1 px-3 py-2 text-[10px] font-bold uppercase tracking-wider ${headerText}`}>Value</div>
      </div>
      {properties.map((prop, idx) => (
        <PropertyRow key={prop.key} label={prop.label} tooltip={prop.tooltip} even={idx % 2 === 0}>
          {renderPropertyInput(prop)}
        </PropertyRow>
      ))}
    </div>
  );
}

// ============================================================
// Settings Tab (Instance Meta + Connection + Runtime Policy)
// ============================================================

function SettingsTab({
  settings,
  onChange,
  onSave,
  connectorConfig,
}: {
  settings: ProcessSettings;
  onChange: (s: ProcessSettings) => void;
  onSave?: (s: ProcessSettings) => void;
  connectorConfig: ConnectorConfig;
}) {
  const [hasChanges, setHasChanges] = useState(false);

  const update = <K extends keyof ProcessSettings>(key: K, value: ProcessSettings[K]) => {
    const next = { ...settings, [key]: value };
    onChange(next);
    setHasChanges(true);
  };

  const handleApply = () => {
    onSave?.(settings);
    setHasChanges(false);
  };

  // Group connection settings
  const connGroups = [...new Set(connectorConfig.connectionSettings.map(p => p.group).filter(Boolean))];
  const runtimeGroups = [...new Set(connectorConfig.runtimePolicy.map(p => p.group).filter(Boolean))];

  return (
    <div className="flex flex-col gap-3 p-4">
      {/* Instance Metadata */}
      <div className="overflow-hidden rounded-lg border border-slate-200">
        <div className="flex border-b border-slate-300 bg-slate-100">
          <div className="w-[180px] shrink-0 border-r border-slate-300 px-3 py-2 text-[10px] font-bold uppercase tracking-wider text-slate-500">Instance</div>
          <div className="flex-1 px-3 py-2 text-[10px] font-bold uppercase tracking-wider text-slate-500">Value</div>
        </div>
        <PropertyRow label="Name" tooltip="Display name for this processor instance" even={true}>
          <input className="w-full rounded border border-slate-300 px-2 py-1 text-xs" value={settings.name} onChange={(e) => update('name', e.target.value)} />
        </PropertyRow>
        <PropertyRow label="Enabled" tooltip="Whether this processor is active" even={false}>
          <button
            onClick={() => update('is_enabled', !settings.is_enabled)}
            className={`rounded px-3 py-1 text-xs font-medium ${settings.is_enabled ? 'bg-green-100 text-green-700' : 'bg-slate-200 text-slate-500'}`}
          >
            {settings.is_enabled ? 'Enabled' : 'Disabled'}
          </button>
        </PropertyRow>
        <PropertyRow label="On Error" tooltip="STOP, SKIP, or RETRY on failure" even={true}>
          <select className="rounded border border-slate-300 px-2 py-1 text-xs" value={settings.on_error} onChange={(e) => update('on_error', e.target.value as OnErrorAction)}>
            <option value="STOP">STOP</option>
            <option value="SKIP">SKIP</option>
            <option value="RETRY">RETRY</option>
          </select>
        </PropertyRow>
        <PropertyRow label="Retry Count" tooltip="Retry attempts before failure" even={false}>
          <input type="number" min={0} className="w-20 rounded border border-slate-300 px-2 py-1 text-xs" value={settings.retry_count} onChange={(e) => update('retry_count', parseInt(e.target.value) || 0)} />
        </PropertyRow>
      </div>

      {/* Connection Settings */}
      {connGroups.length > 0 && connGroups.map(group => (
        <PropertyGroup
          key={group}
          title={group!}
          properties={connectorConfig.connectionSettings.filter(p => p.group === group)}
          color="blue"
        />
      ))}
      {connGroups.length === 0 && connectorConfig.connectionSettings.length > 0 && (
        <PropertyGroup title="Connection" properties={connectorConfig.connectionSettings} color="blue" />
      )}

      {/* Runtime Policy */}
      {runtimeGroups.length > 0 && runtimeGroups.map(group => (
        <PropertyGroup
          key={group}
          title={group!}
          properties={connectorConfig.runtimePolicy.filter(p => p.group === group)}
          color="amber"
        />
      ))}
      {runtimeGroups.length === 0 && connectorConfig.runtimePolicy.length > 0 && (
        <PropertyGroup title="Runtime Policy" properties={connectorConfig.runtimePolicy} color="amber" />
      )}

      {/* Apply button */}
      {hasChanges && onSave && (
        <button
          onClick={handleApply}
          className="flex w-full items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 py-2.5 text-xs font-semibold text-white shadow-sm transition-colors hover:bg-blue-700"
        >
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
          </svg>
          Apply Changes
        </button>
      )}
    </div>
  );
}

// ============================================================
// JSON Config Editor
// ============================================================

function JsonConfigEditor({ connectorCode, properties }: { connectorCode?: string; properties: PropertyDef[] }) {
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
    try { JSON.parse(text); setError(null); return true; }
    catch (e) { setError((e as Error).message); return false; }
  }

  function handleSave() {
    if (handleValidate(jsonText)) {
      try { setJsonText(JSON.stringify(JSON.parse(jsonText), null, 2)); } catch { /* keep */ }
      setIsEditing(false);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    }
  }

  return (
    <div className="mt-4">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className="text-[10px] font-bold uppercase tracking-wider text-slate-500">JSON Config</span>
          {connectorCode && <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[9px] font-mono text-slate-500">{connectorCode}</span>}
        </div>
        <div className="flex items-center gap-1">
          {saved && <span className="text-[10px] font-medium text-green-600">Saved</span>}
          {isEditing ? (
            <>
              <button onClick={() => { setJsonText(initialJson); setError(null); setIsEditing(false); }} className="rounded border border-slate-200 px-2 py-0.5 text-[10px] font-medium text-slate-500 hover:bg-slate-50">Cancel</button>
              <button onClick={handleSave} className="rounded border border-blue-200 bg-blue-50 px-2 py-0.5 text-[10px] font-medium text-blue-700 hover:bg-blue-100">Apply</button>
            </>
          ) : (
            <button onClick={() => setIsEditing(true)} className="rounded border border-slate-200 px-2 py-0.5 text-[10px] font-medium text-slate-500 hover:bg-slate-50">Edit JSON</button>
          )}
        </div>
      </div>
      {isEditing ? (
        <div>
          <textarea
            value={jsonText}
            onChange={(e) => { setJsonText(e.target.value); handleValidate(e.target.value); }}
            spellCheck={false}
            className={`w-full rounded-lg border p-3 font-mono text-[11px] leading-5 focus:outline-none focus:ring-1 ${error ? 'border-red-300 bg-red-50 text-red-900 focus:ring-red-400' : 'border-slate-300 bg-slate-900 text-slate-200 focus:ring-blue-400'}`}
            rows={Math.min(20, jsonText.split('\n').length + 2)}
          />
          {error && (
            <div className="mt-1 flex items-center gap-1 text-[10px] text-red-600">
              <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" /></svg>
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
    <pre className="overflow-auto rounded-lg bg-slate-900 p-3 font-mono text-[11px] leading-5 text-slate-300" dangerouslySetInnerHTML={{ __html: highlighted }} />
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

  const config = (connectorCode && connectorConfigs[connectorCode])
    ? connectorConfigs[connectorCode]
    : genericConfigs[stageType];

  useEffect(() => {
    if (initialSettings) setSettings(initialSettings);
  }, [stageType]);

  const tabStyle = TAB_CONFIG[activeTab];

  // Group recipe properties
  const recipeGroups = [...new Set(config.recipeProperties.map(p => p.group).filter(Boolean))];

  return (
    <div className="flex w-[480px] flex-col border-l border-slate-200 bg-white">
      {/* Panel Header */}
      <div className={`flex items-center justify-between px-4 py-3 text-white ${tabStyle.headerClass}`}>
        <div>
          <div className="flex items-center gap-2">
            <span className="inline-block h-2 w-2 rounded-full bg-white/60" />
            <h3 className="text-sm font-semibold">{processorName ?? stageMeta.label}</h3>
          </div>
          <p className="mt-0.5 text-[11px] text-white/70">{config.label} Configuration</p>
        </div>
        <button onClick={onClose} className="rounded-lg p-1.5 text-white/70 transition-colors hover:bg-white/10 hover:text-white">
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
            className={`relative flex-1 px-4 py-2.5 text-xs font-semibold uppercase tracking-wider transition-colors ${activeTab === id ? 'bg-white text-slate-800' : 'text-slate-500 hover:text-slate-700'}`}
          >
            {cfg.label}
            {activeTab === id && <span className={`absolute bottom-0 left-0 right-0 h-0.5 ${cfg.headerClass}`} />}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      <div className="flex-1 overflow-auto">
        {activeTab === 'SETTINGS' && (
          <SettingsTab settings={settings} onChange={setSettings} onSave={onSaveSettings} connectorConfig={config} />
        )}
        {activeTab === 'PROPERTIES' && (
          <div className="p-4">
            {recipeGroups.length > 0 ? (
              recipeGroups.map(group => (
                <PropertyGroup
                  key={group}
                  title={group!}
                  properties={config.recipeProperties.filter(p => p.group === group)}
                  color="blue"
                />
              ))
            ) : config.recipeProperties.length > 0 ? (
              <PropertyGroup title="Configuration" properties={config.recipeProperties} color="blue" />
            ) : (
              <div className="rounded-lg border-2 border-dashed border-slate-200 py-8 text-center">
                <p className="text-xs text-slate-400">No recipe properties for this connector type</p>
              </div>
            )}
            <JsonConfigEditor connectorCode={connectorCode} properties={config.recipeProperties} />
          </div>
        )}
      </div>
    </div>
  );
}
