import { useState } from 'react';
import { StageType } from '../../types';

interface ConnectorItem {
  code: string;
  name: string;
  description: string;
  type: StageType;
  category: string;
  icon?: string;
  source: 'native' | 'airbyte' | 'singer';
}

const CONNECTORS: ConnectorItem[] = [
  // Collectors — Native
  { code: 'ftp-sftp-collector', name: 'FTP/SFTP', description: 'Collect files from FTP/FTPS/SFTP servers', type: StageType.COLLECT, category: 'File', source: 'native' },
  { code: 'rest-api-collector', name: 'REST API', description: 'Poll REST endpoints', type: StageType.COLLECT, category: 'API', source: 'native' },
  { code: 'file-watcher', name: 'File Watcher', description: 'Monitor local directories', type: StageType.COLLECT, category: 'File', source: 'native' },
  { code: 'database-poller', name: 'Database CDC', description: 'Track DB changes', type: StageType.COLLECT, category: 'Database', source: 'native' },
  { code: 'kafka-consumer', name: 'Kafka Consumer', description: 'Consume Kafka topics', type: StageType.COLLECT, category: 'Streaming', source: 'native' },
  { code: 'mqtt-subscriber', name: 'MQTT', description: 'Subscribe to MQTT topics', type: StageType.COLLECT, category: 'IoT', source: 'native' },
  { code: 'tcp-listener', name: 'TCP/UDP Socket', description: 'Receive raw socket data', type: StageType.COLLECT, category: 'Network', source: 'native' },
  // Collectors — Airbyte
  { code: 'source-postgres', name: 'PostgreSQL', description: 'Airbyte PostgreSQL source', type: StageType.COLLECT, category: 'Database', source: 'airbyte' },
  { code: 'source-mysql', name: 'MySQL', description: 'Airbyte MySQL source', type: StageType.COLLECT, category: 'Database', source: 'airbyte' },
  { code: 'source-mongodb', name: 'MongoDB', description: 'Airbyte MongoDB source', type: StageType.COLLECT, category: 'Database', source: 'airbyte' },
  { code: 'source-salesforce', name: 'Salesforce', description: 'Airbyte Salesforce source', type: StageType.COLLECT, category: 'SaaS', source: 'airbyte' },
  { code: 'source-s3', name: 'Amazon S3', description: 'Airbyte S3 source', type: StageType.COLLECT, category: 'Storage', source: 'airbyte' },
  { code: 'tap-csv', name: 'CSV Files', description: 'Singer CSV tap', type: StageType.COLLECT, category: 'File', source: 'singer' },
  // Processors — Native
  { code: 'anomaly-detector', name: 'Anomaly Detector', description: 'Z-score analysis', type: StageType.PROCESS, category: 'Analytics', source: 'native' },
  { code: 'data-transformer', name: 'Data Transformer', description: 'Map/filter/transform', type: StageType.PROCESS, category: 'Transform', source: 'native' },
  { code: 'json-transform', name: 'JSON Transform', description: 'JMESPath expressions', type: StageType.PROCESS, category: 'Transform', source: 'native' },
  { code: 'csv-json-converter', name: 'CSV-JSON Converter', description: 'Bidirectional conversion', type: StageType.PROCESS, category: 'Transform', source: 'native' },
  { code: 'dedup-filter', name: 'Dedup Filter', description: 'Remove duplicates', type: StageType.PROCESS, category: 'Filter', source: 'native' },
  { code: 'content-router', name: 'Content Router', description: 'Conditional routing', type: StageType.PROCESS, category: 'Routing', source: 'native' },
  { code: 'merge-content', name: 'Merge Content', description: 'Merge records into batches', type: StageType.PROCESS, category: 'Batch', source: 'native' },
  { code: 'split-records', name: 'Split Records', description: 'Split batches', type: StageType.PROCESS, category: 'Batch', source: 'native' },
  { code: 'passthrough', name: 'Passthrough', description: 'No-op (testing)', type: StageType.PROCESS, category: 'Utility', source: 'native' },
  // Exports — Native
  { code: 'kafka-producer', name: 'Kafka Producer', description: 'Publish to Kafka topics', type: StageType.EXPORT, category: 'Streaming', source: 'native' },
  { code: 'file-output', name: 'File Output', description: 'Write to local files', type: StageType.EXPORT, category: 'File', source: 'native' },
  { code: 'ftp-sftp-upload', name: 'FTP/SFTP Upload', description: 'Upload files to remote servers', type: StageType.EXPORT, category: 'File', source: 'native' },
  { code: 'webhook-sender', name: 'Webhook', description: 'HTTP POST results', type: StageType.EXPORT, category: 'API', source: 'native' },
  { code: 'db-writer', name: 'Database Writer', description: 'Insert/upsert to DB', type: StageType.EXPORT, category: 'Database', source: 'native' },
  // Exports — Airbyte
  { code: 'destination-postgres', name: 'PostgreSQL', description: 'Airbyte PG destination', type: StageType.EXPORT, category: 'Database', source: 'airbyte' },
  { code: 'destination-bigquery', name: 'BigQuery', description: 'Airbyte BigQuery dest', type: StageType.EXPORT, category: 'Data Warehouse', source: 'airbyte' },
  { code: 'destination-snowflake', name: 'Snowflake', description: 'Airbyte Snowflake dest', type: StageType.EXPORT, category: 'Data Warehouse', source: 'airbyte' },
  { code: 'destination-s3', name: 'Amazon S3', description: 'Airbyte S3 destination', type: StageType.EXPORT, category: 'Storage', source: 'airbyte' },
  { code: 'destination-elasticsearch', name: 'Elasticsearch', description: 'Airbyte ES dest', type: StageType.EXPORT, category: 'Search', source: 'airbyte' },
];

interface Props {
  onAddNode: (connector: ConnectorItem) => void;
}

const typeColors: Record<StageType, { bg: string; text: string; border: string }> = {
  [StageType.COLLECT]: { bg: 'bg-blue-50', text: 'text-blue-700', border: 'border-blue-200' },
  [StageType.PROCESS]: { bg: 'bg-purple-50', text: 'text-purple-700', border: 'border-purple-200' },
  [StageType.EXPORT]: { bg: 'bg-emerald-50', text: 'text-emerald-700', border: 'border-emerald-200' },
};

const sourceLabels: Record<string, { label: string; color: string }> = {
  native: { label: 'Native', color: 'bg-slate-100 text-slate-600' },
  airbyte: { label: 'Airbyte', color: 'bg-orange-100 text-orange-700' },
  singer: { label: 'Singer', color: 'bg-pink-100 text-pink-700' },
};

export default function ConnectorCatalog({ onAddNode }: Props) {
  const [search, setSearch] = useState('');
  const [typeFilter, setTypeFilter] = useState<StageType | 'all'>('all');

  const filtered = CONNECTORS.filter(c => {
    if (typeFilter !== 'all' && c.type !== typeFilter) return false;
    if (search && !c.name.toLowerCase().includes(search.toLowerCase()) &&
        !c.description.toLowerCase().includes(search.toLowerCase()) &&
        !c.category.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  const grouped = {
    [StageType.COLLECT]: filtered.filter(c => c.type === StageType.COLLECT),
    [StageType.PROCESS]: filtered.filter(c => c.type === StageType.PROCESS),
    [StageType.EXPORT]: filtered.filter(c => c.type === StageType.EXPORT),
  };

  return (
    <div className="flex h-full w-72 flex-col border-r border-slate-200 bg-white">
      <div className="border-b border-slate-200 p-3">
        <h3 className="text-sm font-semibold text-slate-900">Connectors</h3>
        <input
          type="text"
          placeholder="Search connectors..."
          value={search}
          onChange={e => setSearch(e.target.value)}
          className="mt-2 w-full rounded-lg border border-slate-200 px-3 py-1.5 text-xs focus:border-hermes-500 focus:outline-none"
        />
        <div className="mt-2 flex gap-1">
          {(['all', StageType.COLLECT, StageType.PROCESS, StageType.EXPORT] as const).map(t => (
            <button
              key={t}
              onClick={() => setTypeFilter(t)}
              className={`rounded px-2 py-0.5 text-[10px] font-medium ${
                typeFilter === t ? 'bg-hermes-600 text-white' : 'bg-slate-100 text-slate-500'
              }`}
            >
              {t === 'all' ? 'All' : t}
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 overflow-auto p-2">
        {Object.entries(grouped).map(([type, connectors]) => {
          if (connectors.length === 0) return null;
          const stageType = type as StageType;
          const colors = typeColors[stageType];
          return (
            <div key={type} className="mb-3">
              <p className={`mb-1 rounded px-2 py-1 text-[10px] font-bold uppercase tracking-wider ${colors.bg} ${colors.text}`}>
                {type === StageType.COLLECT ? 'Collectors' : type === StageType.PROCESS ? 'Processors' : 'Exports'}
                <span className="ml-1 font-normal">({connectors.length})</span>
              </p>
              {connectors.map(c => {
                const src = sourceLabels[c.source];
                return (
                  <button
                    key={c.code}
                    onClick={() => onAddNode(c)}
                    draggable
                    onDragStart={e => {
                      e.dataTransfer.setData('application/hermes-connector', JSON.stringify(c));
                      e.dataTransfer.effectAllowed = 'copy';
                    }}
                    className={`mb-1 flex w-full items-start gap-2 rounded-lg border p-2 text-left transition-all hover:shadow-sm ${colors.border} hover:${colors.bg}`}
                  >
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-1">
                        <span className="text-xs font-medium text-slate-800 truncate">{c.name}</span>
                        <span className={`shrink-0 rounded px-1 py-0.5 text-[8px] font-medium ${src.color}`}>
                          {src.label}
                        </span>
                      </div>
                      <p className="text-[10px] text-slate-400 truncate">{c.description}</p>
                    </div>
                    <svg className="mt-0.5 h-3.5 w-3.5 shrink-0 text-slate-300" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
                    </svg>
                  </button>
                );
              })}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export type { ConnectorItem };
