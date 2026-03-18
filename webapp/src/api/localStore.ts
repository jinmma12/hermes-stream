/**
 * Local storage persistence layer for pipeline data.
 *
 * When the backend API is unavailable, pipelines are saved to localStorage
 * so they persist across page navigation and browser refresh.
 *
 * This is a fallback — when the API becomes available, local data should
 * be migrated to the backend.
 */

import type { PipelineInstance } from '../types';
import { PipelineStatus } from '../types';

const STORAGE_KEY = 'hermes:pipelines';

// Demo pipelines shown when no saved data exists
const DEMO_PIPELINES: PipelineInstance[] = [
  {
    id: 1,
    name: 'Vendor-A 주문 수집',
    description: 'REST API → Anomaly Detector → S3 Upload',
    monitoring_type: 'API_POLL' as PipelineInstance['monitoring_type'],
    monitoring_config: { interval: '5m' },
    status: PipelineStatus.ACTIVE,
    created_at: '2026-03-01T09:00:00Z',
    updated_at: '2026-03-15T14:30:00Z',
  },
  {
    id: 2,
    name: '장비 데이터 수집',
    description: 'FTP/SFTP → Data Transformer → DB Writer',
    monitoring_type: 'FILE_MONITOR' as PipelineInstance['monitoring_type'],
    monitoring_config: { path: '/data/equipment', pattern: '*.csv' },
    status: PipelineStatus.ACTIVE,
    created_at: '2026-03-05T10:00:00Z',
    updated_at: '2026-03-15T14:25:00Z',
  },
  {
    id: 3,
    name: 'ERP DB 동기화',
    description: 'Database CDC → Transform → DB Writer',
    monitoring_type: 'DB_POLL' as PipelineInstance['monitoring_type'],
    monitoring_config: { table: 'orders', poll_interval: '1m' },
    status: PipelineStatus.PAUSED,
    created_at: '2026-03-10T08:00:00Z',
    updated_at: '2026-03-14T16:00:00Z',
  },
  {
    id: 4,
    name: '센서 데이터 분석',
    description: 'Kafka Consumer → Anomaly Detector → S3 Upload',
    monitoring_type: 'EVENT_STREAM' as PipelineInstance['monitoring_type'],
    monitoring_config: { topics: 'sensor-data' },
    status: PipelineStatus.ACTIVE,
    created_at: '2026-03-08T09:00:00Z',
    updated_at: '2026-03-15T14:00:00Z',
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
