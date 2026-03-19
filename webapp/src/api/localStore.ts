/**
 * Local storage persistence layer for pipeline data.
 *
 * When the backend API is unavailable, pipelines are saved to localStorage
 * so they persist across page navigation and browser refresh.
 *
 * This is a fallback — when the API becomes available, local data should
 * be migrated to the backend.
 */

import type { PipelineInstance, PipelineStage } from '../types';
import { PipelineStatus, StageType } from '../types';

const STORAGE_KEY = 'hermes:pipelines';

// Helper to build a stage
function stage(
  id: number, pipelineId: number, order: number,
  stageType: 'COLLECT' | 'PROCESS' | 'EXPORT',
  refName: string, connectorCode?: string,
  recipeConfig?: Record<string, unknown>,
  connectionConfig?: Record<string, unknown>,
): PipelineStage {
  return {
    id,
    pipeline_instance_id: pipelineId,
    stage_order: order,
    stage_type: stageType as StageType,
    ref_type: stageType === 'COLLECT' ? 'COLLECTOR' : stageType === 'PROCESS' ? 'PROCESS' : 'EXPORT',
    ref_id: id,
    ref_name: refName,
    connector_code: connectorCode,
    is_enabled: true,
    on_error: 'STOP' as PipelineStage['on_error'],
    retry_count: 3,
    retry_delay_seconds: 10,
    recipe_config_json: recipeConfig,
    connection_config_json: connectionConfig,
  };
}

// Demo pipelines with actual stages
const DEMO_PIPELINES: PipelineInstance[] = [
  {
    id: 1,
    name: 'Vendor-A 주문 수집',
    description: 'REST API → JSON Transform → Webhook',
    monitoring_type: 'API_POLL' as PipelineInstance['monitoring_type'],
    monitoring_config: { interval: '5m' },
    status: PipelineStatus.ACTIVE,
    created_at: '2026-03-01T09:00:00Z',
    updated_at: '2026-03-15T14:30:00Z',
    stages: [
      stage(11, 1, 1, 'COLLECT', 'REST API Collector', 'rest-api-collector',
        { path: '/v2/orders', method: 'GET', records_path: 'data.items', pagination_type: 'offset' },
        { base_url: 'https://api.vendor-a.com', auth_type: 'bearer' }),
      stage(12, 1, 2, 'PROCESS', 'JSON Transform', 'json-transform',
        { jmespath_expression: 'items[?status==`active`]' }),
      stage(13, 1, 3, 'EXPORT', 'Webhook Sender', 'webhook-sender',
        { path: '/ingest/orders', method: 'POST', batch_mode: true, batch_size: 50 },
        { base_url: 'https://internal.erp.com', auth_type: 'bearer' }),
    ],
  },
  {
    id: 2,
    name: '장비 데이터 수집',
    description: 'FTP/SFTP → CSV-JSON Converter → DB Writer',
    monitoring_type: 'FILE_MONITOR' as PipelineInstance['monitoring_type'],
    monitoring_config: { path: '/data/equipment', pattern: '*.csv' },
    status: PipelineStatus.ACTIVE,
    created_at: '2026-03-05T10:00:00Z',
    updated_at: '2026-03-15T14:25:00Z',
    stages: [
      stage(21, 2, 1, 'COLLECT', 'FTP/SFTP Collector', 'ftp-sftp-collector',
        { remote_path: '/data/equipment', recursive: true, max_depth: 2,
          file_filter: { filename_regex: 'sensor_.*\\.csv$', exclude_zero_byte: true },
          discovery_mode: 'ALL_NEW', completion_check: { strategy: 'MARKER_FILE', marker_suffix: '.done' } },
        { protocol: 'SFTP', host: '192.168.1.50', port: 22, username: 'hermes' }),
      stage(22, 2, 2, 'PROCESS', 'CSV-JSON Converter', 'csv-json-converter',
        { delimiter: ',', has_header: true, encoding: 'utf-8' }),
      stage(23, 2, 3, 'EXPORT', 'Database Writer', 'db-writer',
        { table_name: 'equipment_readings', write_mode: 'UPSERT', conflict_key: 'sensor_id,timestamp', batch_size: 500 },
        { connection_string: 'Host=db.internal;Database=hermes_prod', provider: 'PostgreSQL' }),
    ],
  },
  {
    id: 3,
    name: 'ERP DB 동기화',
    description: 'Database CDC → JSON Transform → DB Writer',
    monitoring_type: 'DB_POLL' as PipelineInstance['monitoring_type'],
    monitoring_config: { table: 'orders', poll_interval: '1m' },
    status: PipelineStatus.PAUSED,
    created_at: '2026-03-10T08:00:00Z',
    updated_at: '2026-03-14T16:00:00Z',
    stages: [
      stage(31, 3, 1, 'COLLECT', 'Database Poller', 'database-poller',
        { table_name: 'erp_orders', cursor_column: 'updated_at', cursor_type: 'timestamp', batch_size: 200 },
        { connection_string: 'Host=erp-db;Database=erp_prod', provider: 'SqlServer' }),
      stage(32, 3, 2, 'PROCESS', 'JSON Transform', 'json-transform',
        { jmespath_expression: '{order_id: id, customer: customer_name, total: amount}' }),
      stage(33, 3, 3, 'EXPORT', 'Database Writer', 'db-writer',
        { table_name: 'synced_orders', write_mode: 'UPSERT', conflict_key: 'order_id', batch_size: 100 },
        { connection_string: 'Host=analytics-db;Database=warehouse', provider: 'PostgreSQL' }),
    ],
  },
  {
    id: 4,
    name: '센서 데이터 분석',
    description: 'Kafka Consumer → Split Records → Kafka Producer',
    monitoring_type: 'EVENT_STREAM' as PipelineInstance['monitoring_type'],
    monitoring_config: { topics: 'sensor-data' },
    status: PipelineStatus.ACTIVE,
    created_at: '2026-03-08T09:00:00Z',
    updated_at: '2026-03-15T14:00:00Z',
    stages: [
      stage(41, 4, 1, 'COLLECT', 'Kafka Consumer', 'kafka-consumer',
        { topics: 'raw-sensor-data', auto_offset_reset: 'latest', key_deserializer: 'string', value_deserializer: 'json' },
        { bootstrap_servers: 'kafka-1:9092,kafka-2:9092', group_id: 'hermes-sensor-group', security_protocol: 'PLAINTEXT' }),
      stage(42, 4, 2, 'PROCESS', 'Split Records', 'split-records',
        { split_path: 'readings', keep_parent_fields: true }),
      stage(43, 4, 3, 'EXPORT', 'Kafka Producer', 'kafka-producer',
        { topic: 'processed-sensor-events', key_field: 'sensor_id', compression: 'snappy', acks: 'all', enable_idempotence: true },
        { bootstrap_servers: 'kafka-1:9092,kafka-2:9092', security_protocol: 'PLAINTEXT' }),
    ],
  },
];

function load(): PipelineInstance[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return JSON.parse(raw);
  } catch { /* corrupted data */ }
  return [...DEMO_PIPELINES];
}

function save(list: PipelineInstance[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(list));
}

let nextId = 100;

/**
 * localStorage-backed pipeline CRUD for offline/demo mode.
 */
export const localPipelines = {
  list(): PipelineInstance[] {
    return load();
  },

  get(id: number): PipelineInstance | undefined {
    return load().find((p) => p.id === id);
  },

  create(data: Partial<PipelineInstance>): PipelineInstance {
    const list = load();
    const maxId = list.reduce((m, p) => Math.max(m, p.id), nextId);
    nextId = maxId + 1;
    const created: PipelineInstance = {
      id: nextId,
      name: data.name || 'New Pipeline',
      description: data.description || '',
      monitoring_type: data.monitoring_type || ('API_POLL' as PipelineInstance['monitoring_type']),
      monitoring_config: data.monitoring_config || {},
      status: data.status || PipelineStatus.DRAFT,
      stages: data.stages,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };
    list.push(created);
    save(list);
    return created;
  },

  update(id: number, data: Partial<PipelineInstance>): PipelineInstance {
    const list = load();
    const idx = list.findIndex((p) => p.id === id);
    if (idx === -1) throw new Error(`Pipeline ${id} not found`);
    const updated = { ...list[idx], ...data, updated_at: new Date().toISOString() };
    list[idx] = updated;
    save(list);
    return updated;
  },

  delete(id: number): void {
    const list = load().filter((p) => p.id !== id);
    save(list);
  },

  duplicate(id: number): PipelineInstance {
    const source = localPipelines.get(id);
    if (!source) throw new Error(`Pipeline ${id} not found`);
    return localPipelines.create({
      ...source,
      name: `${source.name} (Copy)`,
      status: PipelineStatus.DRAFT,
    });
  },

  archive(id: number): PipelineInstance {
    return localPipelines.update(id, { status: PipelineStatus.ARCHIVED });
  },
};
