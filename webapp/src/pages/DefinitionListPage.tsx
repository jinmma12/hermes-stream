import { useEffect, useState } from 'react';
import type { CollectorDefinition as _C, ProcessDefinition as _A, ExportDefinition as _T } from '../types';
import { DefinitionStatus, StageType } from '../types';
import { definitions } from '../api/client';
import StatusBadge from '../components/common/StatusBadge';
import LoadingSpinner from '../components/common/LoadingSpinner';
import EmptyState from '../components/common/EmptyState';

type Tab = 'collectors' | 'processors' | 'exports';

interface DefinitionCard {
  id: number;
  code: string;
  name: string;
  description: string;
  category: string;
  icon_url: string | null;
  status: DefinitionStatus;
  type: StageType;
  versionCount: number;
}

export default function DefinitionListPage() {
  const [activeTab, setActiveTab] = useState<Tab>('collectors');
  const [cards, setCards] = useState<DefinitionCard[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadDefinitions();
  }, [activeTab]);

  async function loadDefinitions() {
    setLoading(true);
    try {
      let data: DefinitionCard[] = [];
      if (activeTab === 'collectors') {
        const defs = await definitions.listCollectors();
        data = defs.map((d) => ({ ...d, type: StageType.COLLECT, versionCount: d.versions?.length || 0 }));
      } else if (activeTab === 'processors') {
        const defs = await definitions.listProcessors();
        data = defs.map((d) => ({ ...d, type: StageType.PROCESS, versionCount: d.versions?.length || 0 }));
      } else {
        const defs = await definitions.listExports();
        data = defs.map((d) => ({ ...d, type: StageType.EXPORT, versionCount: d.versions?.length || 0 }));
      }
      setCards(data);
    } catch {
      // Demo data
      if (activeTab === 'collectors') {
        setCards([
          { id: 1, code: 'ftp-sftp-collector', name: 'FTP/SFTP Collector', description: 'Collects files from FTP/FTPS/SFTP servers. Recursive traversal, regex filters, completion checks.', category: 'File', icon_url: null, status: DefinitionStatus.ACTIVE, type: StageType.COLLECT, versionCount: 3 },
          { id: 2, code: 'rest-api-collector', name: 'REST API Collector', description: 'Polls REST API endpoints. GET/POST, authentication, pagination.', category: 'API', icon_url: null, status: DefinitionStatus.ACTIVE, type: StageType.COLLECT, versionCount: 2 },
          { id: 3, code: 'file-watcher', name: 'File Watcher', description: 'Monitors local directories for new or modified files. Glob patterns.', category: 'File', icon_url: null, status: DefinitionStatus.ACTIVE, type: StageType.COLLECT, versionCount: 1 },
          { id: 4, code: 'database-poller', name: 'Database CDC', description: 'Polls database tables for changes using timestamp or sequence tracking.', category: 'Database', icon_url: null, status: DefinitionStatus.ACTIVE, type: StageType.COLLECT, versionCount: 2 },
          { id: 5, code: 'kafka-consumer', name: 'Kafka Consumer', description: 'Consumes messages from Kafka topics. Consumer group, offset management.', category: 'Streaming', icon_url: null, status: DefinitionStatus.ACTIVE, type: StageType.COLLECT, versionCount: 1 },
          { id: 6, code: 'mqtt-subscriber', name: 'MQTT Subscriber', description: 'Subscribes to MQTT topics for real-time IoT data collection.', category: 'IoT', icon_url: null, status: DefinitionStatus.DRAFT, type: StageType.COLLECT, versionCount: 1 },
        ]);
      } else if (activeTab === 'processors') {
        setCards([
          { id: 1, code: 'anomaly-detector', name: 'Anomaly Detector', description: 'Statistical anomaly detection using z-score, IQR, or modified z-score.', category: 'Analytics', icon_url: null, status: DefinitionStatus.ACTIVE, type: StageType.PROCESS, versionCount: 2 },
          { id: 2, code: 'data-transformer', name: 'Data Transformer', description: 'Transforms data between formats with mapping rules. JSON, CSV, XML.', category: 'Transform', icon_url: null, status: DefinitionStatus.ACTIVE, type: StageType.PROCESS, versionCount: 1 },
          { id: 3, code: 'json-transform', name: 'JSON Transform', description: 'JMESPath-based JSON transformation and extraction.', category: 'Transform', icon_url: null, status: DefinitionStatus.ACTIVE, type: StageType.PROCESS, versionCount: 1 },
          { id: 4, code: 'csv-json-converter', name: 'CSV-JSON Converter', description: 'Bidirectional CSV/JSON conversion with header mapping.', category: 'Transform', icon_url: null, status: DefinitionStatus.ACTIVE, type: StageType.PROCESS, versionCount: 1 },
          { id: 5, code: 'dedup-filter', name: 'Dedup Filter', description: 'Removes duplicates based on configurable key fields and time windows.', category: 'Filter', icon_url: null, status: DefinitionStatus.ACTIVE, type: StageType.PROCESS, versionCount: 1 },
          { id: 6, code: 'content-router', name: 'Content Router', description: 'Routes data to different outputs based on content conditions.', category: 'Routing', icon_url: null, status: DefinitionStatus.ACTIVE, type: StageType.PROCESS, versionCount: 1 },
          { id: 7, code: 'merge-content', name: 'Merge Content', description: 'Merges multiple records into batches (NiFi MergeContent).', category: 'Batch', icon_url: null, status: DefinitionStatus.ACTIVE, type: StageType.PROCESS, versionCount: 1 },
          { id: 8, code: 'split-records', name: 'Split Records', description: 'Splits batches into individual records (NiFi SplitRecord).', category: 'Batch', icon_url: null, status: DefinitionStatus.ACTIVE, type: StageType.PROCESS, versionCount: 1 },
        ]);
      } else {
        setCards([
          { id: 1, code: 'kafka-producer', name: 'Kafka Producer', description: 'Publishes processed data to Kafka topics. Partitioning, acks.', category: 'Streaming', icon_url: null, status: DefinitionStatus.ACTIVE, type: StageType.EXPORT, versionCount: 1 },
          { id: 2, code: 'file-output', name: 'File Output', description: 'Writes processed data to local files. JSON, CSV, text formats.', category: 'File', icon_url: null, status: DefinitionStatus.ACTIVE, type: StageType.EXPORT, versionCount: 1 },
          { id: 3, code: 'db-writer', name: 'Database Writer', description: 'Writes to PostgreSQL, MySQL, or MSSQL. Insert, upsert, merge.', category: 'Database', icon_url: null, status: DefinitionStatus.ACTIVE, type: StageType.EXPORT, versionCount: 2 },
          { id: 4, code: 'webhook-sender', name: 'Webhook Sender', description: 'Sends results to external webhook endpoints with retry.', category: 'API', icon_url: null, status: DefinitionStatus.ACTIVE, type: StageType.EXPORT, versionCount: 1 },
          { id: 5, code: 'ftp-sftp-upload', name: 'FTP/SFTP Upload', description: 'Uploads files to remote FTP/SFTP servers.', category: 'File', icon_url: null, status: DefinitionStatus.ACTIVE, type: StageType.EXPORT, versionCount: 1 },
        ]);
      }
    } finally {
      setLoading(false);
    }
  }

  const tabConfig = {
    collectors: { label: 'Collectors', color: 'blue', icon: 'M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3' },
    processors: { label: 'Processors', color: 'purple', icon: 'M9.75 3.104v5.714a2.25 2.25 0 01-.659 1.591L5 14.5M9.75 3.104c-.251.023-.501.05-.75.082m.75-.082a24.301 24.301 0 014.5 0m0 0v5.714c0 .597.237 1.17.659 1.591L19.8 15.3M14.25 3.104c.251.023.501.05.75.082M19.8 15.3l-1.57.393A9.065 9.065 0 0112 15a9.065 9.065 0 00-6.23.693L5 14.5m14.8.8l1.402 1.402c1.232 1.232.65 3.318-1.067 3.611A48.309 48.309 0 0112 21c-2.773 0-5.491-.235-8.135-.687-1.718-.293-2.3-2.379-1.067-3.61L5 14.5' },
    exports: { label: 'Exports', color: 'emerald', icon: 'M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5' },
  };

  const typeColorMap: Record<StageType, { bg: string; text: string; iconBg: string }> = {
    [StageType.COLLECT]: { bg: 'bg-blue-50', text: 'text-blue-700', iconBg: 'bg-blue-500' },
    [StageType.PROCESS]: { bg: 'bg-purple-50', text: 'text-purple-700', iconBg: 'bg-purple-500' },
    [StageType.EXPORT]: { bg: 'bg-emerald-50', text: 'text-emerald-700', iconBg: 'bg-emerald-500' },
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Definitions</h1>
          <p className="mt-1 text-sm text-slate-500">
            Plugin definitions available for building pipelines
          </p>
        </div>
        <button className="btn-primary">
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
          </svg>
          New Definition
        </button>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 rounded-lg bg-slate-100 p-1">
        {(Object.keys(tabConfig) as Tab[]).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`flex-1 rounded-md px-4 py-2 text-sm font-medium transition-colors ${
              activeTab === tab
                ? 'bg-white text-slate-900 shadow-sm'
                : 'text-slate-500 hover:text-slate-700'
            }`}
          >
            {tabConfig[tab].label}
          </button>
        ))}
      </div>

      {/* Cards */}
      {loading ? (
        <LoadingSpinner message="Loading definitions..." />
      ) : cards.length === 0 ? (
        <EmptyState
          title={`No ${activeTab} defined`}
          description={`Create a ${activeTab.slice(0, -1)} definition to get started.`}
        />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {cards.map((card) => {
            const colors = typeColorMap[card.type];
            return (
              <div key={card.id} className="card group p-5 transition-shadow hover:shadow-md">
                <div className="flex items-start justify-between">
                  <div className={`flex h-10 w-10 items-center justify-center rounded-lg ${colors.iconBg}`}>
                    <svg className="h-5 w-5 text-white" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" d={tabConfig[activeTab].icon} />
                    </svg>
                  </div>
                  <StatusBadge status={card.status} />
                </div>

                <h3 className="mt-3 text-sm font-semibold text-slate-900">{card.name}</h3>
                <p className="mt-1 line-clamp-2 text-xs text-slate-500">{card.description}</p>

                <div className="mt-4 flex items-center gap-3 border-t border-slate-100 pt-3">
                  <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${colors.bg} ${colors.text}`}>
                    {card.category}
                  </span>
                  <span className="text-[10px] text-slate-400">
                    {card.versionCount} version{card.versionCount !== 1 ? 's' : ''}
                  </span>
                  <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-mono text-slate-500">
                    {card.code}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
