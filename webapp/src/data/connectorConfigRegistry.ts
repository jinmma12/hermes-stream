import { StageType } from '../types';

// ── Manifest imports (source of truth) ──────────────────────
import csvJsonConverterManifest from '../../../plugins/csv-json-converter/hermes-plugin.json';
import databasePollerManifest from '../../../plugins/database-poller/hermes-plugin.json';
import dbWriterManifest from '../../../plugins/db-writer/hermes-plugin.json';
import fileOutputManifest from '../../../plugins/file-output/hermes-plugin.json';
import fileWatcherManifest from '../../../plugins/file-watcher/hermes-plugin.json';
import ftpSftpCollectorManifest from '../../../plugins/community-examples/ftp-sftp-collector/hermes-plugin.json';
import jsonTransformManifest from '../../../plugins/json-transform/hermes-plugin.json';
import kafkaConsumerManifest from '../../../plugins/kafka-consumer/hermes-plugin.json';
import kafkaProducerManifest from '../../../plugins/kafka-producer/hermes-plugin.json';
import mergeContentManifest from '../../../plugins/merge-content/hermes-plugin.json';
import passthroughManifest from '../../../plugins/passthrough/hermes-plugin.json';
import restApiCollectorManifest from '../../../plugins/rest-api-collector/hermes-plugin.json';
import splitRecordsManifest from '../../../plugins/split-records/hermes-plugin.json';
import webhookSenderManifest from '../../../plugins/webhook-sender/hermes-plugin.json';

// ── Public types ────────────────────────────────────────────

export type PropertyType = 'text' | 'password' | 'number' | 'select' | 'textarea';
export type PropertyFormat = 'line_list';

export interface PropertyDef {
  key: string;
  path?: string;
  label: string;
  type: PropertyType;
  defaultValue: string | number | boolean;
  tooltip: string;
  options?: string[];
  group?: string;
  placeholder?: string;
  format?: PropertyFormat;
}

export interface ConnectorConfig {
  label: string;
  connectionSettings: PropertyDef[];
  runtimePolicy: PropertyDef[];
  recipeProperties: PropertyDef[];
}

// ── JSON Schema helpers ─────────────────────────────────────

interface JsonSchema {
  type?: string;
  title?: string;
  description?: string;
  default?: unknown;
  enum?: string[];
  properties?: Record<string, JsonSchema>;
  items?: JsonSchema;
}

interface PluginManifest {
  name?: string;
  input_schema?: JsonSchema;
  settings_schema?: JsonSchema;
}

interface ManifestOverrides {
  label?: string;
  /** Keys from settings_schema that belong in the connection section (default: all non-runtime). */
  connectionKeys?: string[];
  /** Keys from settings_schema that belong in the runtime policy section. */
  runtimeKeys?: string[];
}

function titleFromKey(key: string): string {
  return key
    .split(/[_.-]/g)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

function defaultValueForSchema(schema: JsonSchema): string | number | boolean {
  if (schema.default !== undefined && typeof schema.default !== 'object') {
    return schema.default as string | number | boolean;
  }
  if (schema.enum?.length) return schema.enum[0];
  if (schema.type === 'boolean') return false;
  if (schema.type === 'integer' || schema.type === 'number') return 0;
  return '';
}

function propertyTypeFromSchema(path: string, schema: JsonSchema): PropertyType {
  if (schema.enum?.length || schema.type === 'boolean') return 'select';
  if (schema.type === 'integer' || schema.type === 'number') return 'number';
  if (schema.type === 'array' && schema.items?.type === 'string') return 'textarea';
  if (/(password|token|secret|passphrase|connection_string)/i.test(path)) return 'password';
  return 'text';
}

function buildSchemaProperties(
  schema: JsonSchema | undefined,
  options: { prefix?: string; group?: string; fallbackGroup: string },
): PropertyDef[] {
  if (!schema?.properties) return [];

  return Object.entries(schema.properties).flatMap(([key, property]) => {
    const path = options.prefix ? `${options.prefix}.${key}` : key;
    const group = property.title && property.type === 'object'
      ? property.title
      : options.group ?? schema.title ?? options.fallbackGroup;

    if (property.type === 'object' && property.properties) {
      return buildSchemaProperties(property, {
        prefix: path,
        group: property.title ?? group,
        fallbackGroup: property.title ?? group,
      });
    }

    return [{
      key: path,
      path,
      label: property.title ?? titleFromKey(key),
      type: propertyTypeFromSchema(path, property),
      defaultValue: defaultValueForSchema(property),
      tooltip: property.description ?? '',
      options: property.type === 'boolean' ? ['true', 'false'] : property.enum,
      group,
      format: property.type === 'array' && property.items?.type === 'string' ? 'line_list' : undefined,
    } satisfies PropertyDef];
  });
}

function fromManifest(manifest: PluginManifest, overrides: ManifestOverrides = {}): ConnectorConfig {
  const label = overrides.label ?? manifest.name ?? 'Connector';
  const settingsProps = buildSchemaProperties(manifest.settings_schema, { fallbackGroup: 'Connection' });
  const recipeProps = buildSchemaProperties(manifest.input_schema, { fallbackGroup: 'Configuration' });
  const connectionKeys = new Set(overrides.connectionKeys ?? []);
  const runtimeKeys = new Set(overrides.runtimeKeys ?? []);

  let connectionSettings = settingsProps;
  let runtimePolicy: PropertyDef[] = [];

  if (connectionKeys.size > 0 || runtimeKeys.size > 0) {
    connectionSettings = settingsProps.filter((p) => !runtimeKeys.has(p.key));
    runtimePolicy = settingsProps.filter((p) => runtimeKeys.has(p.key));

    if (connectionKeys.size > 0) {
      connectionSettings = settingsProps.filter((p) => connectionKeys.has(p.key));
      runtimePolicy = settingsProps.filter((p) => runtimeKeys.has(p.key));
    }
  }

  return { label, connectionSettings, runtimePolicy, recipeProperties: recipeProps };
}

// ── Manifest-driven configs (source of truth) ───────────────
// Every core connector is now driven by its hermes-plugin.json manifest.
// The runtimeKeys arrays tell the registry which settings_schema fields
// belong in the Runtime Policy section vs the Connection section.

export const connectorConfigs: Record<string, ConnectorConfig> = {
  // ── Collectors ──
  'ftp-sftp-collector': fromManifest(ftpSftpCollectorManifest as PluginManifest, {
    label: 'FTP/SFTP Collector',
    runtimeKeys: [
      'poll_interval', 'connection_timeout_seconds', 'data_timeout_seconds',
      'max_concurrent_downloads', 'retry_max_attempts', 'retry_base_delay_seconds',
      'retry_max_delay_seconds', 'circuit_breaker_threshold', 'circuit_breaker_recovery_seconds',
    ],
  }),
  'kafka-consumer': fromManifest(kafkaConsumerManifest as PluginManifest, {
    label: 'Kafka Consumer',
    runtimeKeys: [
      'poll_timeout_ms', 'max_poll_records', 'session_timeout_ms', 'retry_backoff_ms',
    ],
  }),
  'rest-api-collector': fromManifest(restApiCollectorManifest as PluginManifest, {
    label: 'REST API Collector',
    runtimeKeys: [
      'timeout_seconds', 'poll_interval', 'retry_max_attempts', 'retry_delay_seconds',
    ],
  }),
  'database-poller': fromManifest(databasePollerManifest as PluginManifest, {
    label: 'Database CDC Poller',
    runtimeKeys: [
      'poll_interval', 'command_timeout_seconds', 'retry_max_attempts', 'retry_delay_seconds',
    ],
  }),
  'file-watcher': fromManifest(fileWatcherManifest as PluginManifest, {
    label: 'File Watcher',
    runtimeKeys: ['poll_interval', 'debounce_ms'],
  }),

  // ── Processors ──
  'json-transform': fromManifest(jsonTransformManifest as PluginManifest, { label: 'JSON Transform' }),
  'merge-content': fromManifest(mergeContentManifest as PluginManifest, { label: 'Merge Content' }),
  'split-records': fromManifest(splitRecordsManifest as PluginManifest, { label: 'Split Records' }),
  'csv-json-converter': fromManifest(csvJsonConverterManifest as PluginManifest, { label: 'CSV-JSON Converter' }),
  passthrough: fromManifest(passthroughManifest as PluginManifest, { label: 'Passthrough' }),

  // ── Exporters ──
  'kafka-producer': fromManifest(kafkaProducerManifest as PluginManifest, {
    label: 'Kafka Producer',
    runtimeKeys: [
      'delivery_timeout_ms', 'request_timeout_ms', 'retry_count',
      'retry_backoff_ms', 'batch_size', 'linger_ms',
    ],
  }),
  'db-writer': fromManifest(dbWriterManifest as PluginManifest, {
    label: 'Database Writer',
    runtimeKeys: [
      'command_timeout_seconds', 'retry_max_attempts', 'retry_delay_seconds',
    ],
  }),
  'webhook-sender': fromManifest(webhookSenderManifest as PluginManifest, {
    label: 'Webhook Sender',
    runtimeKeys: [
      'timeout_seconds', 'max_retries', 'retry_backoff_ms',
      'circuit_breaker_threshold', 'circuit_breaker_recovery_seconds',
    ],
  }),
  'file-output': fromManifest(fileOutputManifest as PluginManifest, { label: 'File Output' }),
};

// ── Generic fallback (for connectors without a manifest) ────

export const genericConfigs: Record<StageType, ConnectorConfig> = {
  [StageType.COLLECT]: {
    label: 'Collector',
    connectionSettings: [],
    runtimePolicy: [],
    recipeProperties: [
      { key: 'execution_type', label: 'Execution Type', type: 'select', defaultValue: 'plugin', tooltip: 'How to execute', options: ['plugin', 'script', 'http'], group: 'Execution' },
      { key: 'execution_ref', label: 'Execution Ref', type: 'text', defaultValue: '', tooltip: 'Plugin or script reference', group: 'Execution' },
    ],
  },
  [StageType.PROCESS]: {
    label: 'Process',
    connectionSettings: [],
    runtimePolicy: [],
    recipeProperties: [
      { key: 'execution_type', label: 'Execution Type', type: 'select', defaultValue: 'plugin', tooltip: 'How to execute', options: ['plugin', 'script', 'http', 'docker'], group: 'Execution' },
      { key: 'execution_ref', label: 'Execution Ref', type: 'text', defaultValue: 'PROCESS:anomaly-detector', tooltip: 'Plugin or script reference', group: 'Execution' },
      { key: 'max_execution_time', label: 'Max Execution Time', type: 'text', defaultValue: '300s', tooltip: 'Timeout', group: 'Execution' },
      { key: 'input_format', label: 'Input Format', type: 'select', defaultValue: 'json', tooltip: 'Expected format', options: ['json', 'csv', 'raw'], group: 'Execution' },
    ],
  },
  [StageType.EXPORT]: {
    label: 'Export',
    connectionSettings: [],
    runtimePolicy: [],
    recipeProperties: [
      { key: 'destination_type', label: 'Destination', type: 'select', defaultValue: 's3', tooltip: 'Export target', options: ['s3', 'database', 'webhook', 'file'], group: 'Destination' },
      { key: 'format', label: 'Output Format', type: 'select', defaultValue: 'json', tooltip: 'Data format', options: ['json', 'csv', 'parquet'], group: 'Destination' },
      { key: 'compression', label: 'Compression', type: 'select', defaultValue: 'gzip', tooltip: 'Compression', options: ['none', 'gzip', 'snappy', 'zstd'], group: 'Destination' },
    ],
  },
};

export function getConnectorConfig(connectorCode: string | undefined, stageType: StageType): ConnectorConfig {
  if (connectorCode && connectorConfigs[connectorCode]) {
    return connectorConfigs[connectorCode];
  }
  return genericConfigs[stageType];
}
