import { useEffect, useState } from 'react';
import type { RJSFSchema, UiSchema } from '@rjsf/utils';
import Form from '@rjsf/core';
import validator from '@rjsf/validator-ajv8';

import { StageType } from '../types';
import type { Recipe } from '../types';
import RecipeDiffViewer from '../components/recipe/RecipeDiffViewer';

interface RecipeEditorPanelProps {
  stageId: number;
  refId: number;
  stageType: StageType;
  onClose: () => void;
}

// Demo schemas for different stage types
const demoSchemas: Record<StageType, { schema: RJSFSchema; uiSchema: UiSchema; defaultConfig: Record<string, unknown> }> = {
  [StageType.COLLECT]: {
    schema: {
      type: 'object',
      properties: {
        url: { type: 'string', title: 'API URL', description: 'The REST API endpoint to poll' },
        method: { type: 'string', title: 'HTTP Method', enum: ['GET', 'POST'], default: 'GET' },
        interval: { type: 'string', title: 'Poll Interval', default: '5m', description: 'How often to check for new data' },
        timeout: { type: 'integer', title: 'Timeout (seconds)', default: 30, minimum: 5, maximum: 300 },
        auth_type: { type: 'string', title: 'Authentication', enum: ['none', 'bearer', 'basic', 'api_key'], default: 'none' },
      },
      required: ['url'],
    },
    uiSchema: {
      url: { 'ui:placeholder': 'https://api.example.com/data' },
      method: { 'ui:widget': 'radio' },
      auth_type: { 'ui:widget': 'select' },
    },
    defaultConfig: {
      url: 'https://vendor-a.com/api/orders',
      method: 'GET',
      interval: '5m',
      timeout: 30,
      auth_type: 'bearer',
    },
  },
  [StageType.ALGORITHM]: {
    schema: {
      type: 'object',
      properties: {
        threshold: { type: 'number', title: 'Detection Threshold', minimum: 0, maximum: 10, default: 2.5, description: 'Higher values = more lenient detection' },
        method: { type: 'string', title: 'Analysis Method', enum: ['z-score', 'iqr', 'modified-z-score'], default: 'z-score' },
        window_size: { type: 'integer', title: 'Window Size', default: 100, minimum: 10, maximum: 10000 },
        sensitivity: { type: 'string', title: 'Sensitivity', enum: ['low', 'medium', 'high'], default: 'medium' },
      },
      required: ['threshold', 'method'],
    },
    uiSchema: {
      threshold: { 'ui:widget': 'range' },
      method: { 'ui:widget': 'radio' },
      sensitivity: { 'ui:widget': 'select' },
    },
    defaultConfig: {
      threshold: 2.5,
      method: 'z-score',
      window_size: 100,
      sensitivity: 'medium',
    },
  },
  [StageType.TRANSFER]: {
    schema: {
      type: 'object',
      properties: {
        bucket: { type: 'string', title: 'S3 Bucket', description: 'Target S3 bucket name' },
        prefix: { type: 'string', title: 'Key Prefix', default: 'results/', description: 'Prefix for S3 object keys' },
        format: { type: 'string', title: 'Output Format', enum: ['json', 'csv', 'parquet'], default: 'json' },
        compression: { type: 'string', title: 'Compression', enum: ['none', 'gzip', 'snappy'], default: 'gzip' },
      },
      required: ['bucket'],
    },
    uiSchema: {
      format: { 'ui:widget': 'radio' },
      compression: { 'ui:widget': 'select' },
    },
    defaultConfig: {
      bucket: 'my-data-bucket',
      prefix: 'results/',
      format: 'json',
      compression: 'gzip',
    },
  },
};

const demoVersionHistory: Recipe[] = [
  {
    version_no: 2,
    config_json: { threshold: 3.0, method: 'z-score', window_size: 100 },
    change_note: 'Increased threshold from 2.5 to 3.0',
    is_current: true,
    created_by: 'operator:kim',
    created_at: '2026-03-15T14:30:00Z',
  },
  {
    version_no: 1,
    config_json: { threshold: 2.5, method: 'z-score', window_size: 100 },
    change_note: 'Initial configuration',
    is_current: false,
    created_by: 'admin',
    created_at: '2026-03-01T09:00:00Z',
  },
];

export default function RecipeEditorPanel({ stageType, onClose }: RecipeEditorPanelProps) {
  const [formData, setFormData] = useState<Record<string, unknown>>({});
  const [changeNote, setChangeNote] = useState('');
  const [versions, setVersions] = useState<Recipe[]>([]);
  const [showHistory, setShowHistory] = useState(false);
  const [showDiff, setShowDiff] = useState(false);

  const demoData = demoSchemas[stageType];

  useEffect(() => {
    setFormData(demoData.defaultConfig);
    setVersions(demoVersionHistory);
  }, [stageType]);

  function handleSave() {
    if (!changeNote.trim()) {
      alert('Please enter a change note.');
      return;
    }
    const newVersion: Recipe = {
      version_no: versions.length + 1,
      config_json: formData,
      change_note: changeNote,
      is_current: true,
      created_by: 'operator',
      created_at: new Date().toISOString(),
    };
    setVersions([newVersion, ...versions.map((v) => ({ ...v, is_current: false }))]);
    setChangeNote('');
    alert('Recipe saved as new version!');
  }

  const stageLabel = {
    [StageType.COLLECT]: { name: 'Collector', color: 'blue' },
    [StageType.ALGORITHM]: { name: 'Algorithm', color: 'purple' },
    [StageType.TRANSFER]: { name: 'Transfer', color: 'emerald' },
  }[stageType];

  return (
    <div className="flex w-96 flex-col border-l border-slate-200 bg-white">
      {/* Panel Header */}
      <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
        <div>
          <div className="flex items-center gap-2">
            <span className={`inline-block h-2 w-2 rounded-full bg-${stageLabel.color}-500`} />
            <h3 className="text-sm font-semibold text-slate-900">Recipe Editor</h3>
          </div>
          <p className="mt-0.5 text-xs text-slate-500">{stageLabel.name} Configuration</p>
        </div>
        <button
          onClick={onClose}
          className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600"
        >
          <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      {/* Version Toggle */}
      <div className="flex border-b border-slate-200">
        <button
          onClick={() => setShowHistory(false)}
          className={`flex-1 px-4 py-2 text-xs font-medium transition-colors ${
            !showHistory ? 'border-b-2 border-hermes-600 text-hermes-700' : 'text-slate-500 hover:text-slate-700'
          }`}
        >
          Configuration
        </button>
        <button
          onClick={() => setShowHistory(true)}
          className={`flex-1 px-4 py-2 text-xs font-medium transition-colors ${
            showHistory ? 'border-b-2 border-hermes-600 text-hermes-700' : 'text-slate-500 hover:text-slate-700'
          }`}
        >
          Version History ({versions.length})
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto">
        {!showHistory ? (
          <div className="p-4">
            {/* JSON Schema Form */}
            <div className="hermes-form">
              <Form
                schema={demoData.schema}
                uiSchema={demoData.uiSchema}
                formData={formData}
                validator={validator}
                onChange={(e) => setFormData(e.formData)}
                liveValidate
              >
                {/* Hide default submit button */}
                <div />
              </Form>
            </div>

            {/* Change Note + Save */}
            <div className="mt-6 space-y-3 border-t border-slate-200 pt-4">
              <div>
                <label className="mb-1 block text-xs font-medium text-slate-700">
                  Change Note
                </label>
                <input
                  type="text"
                  value={changeNote}
                  onChange={(e) => setChangeNote(e.target.value)}
                  placeholder="Describe what changed..."
                  className="input"
                />
              </div>
              <button onClick={handleSave} className="btn-primary w-full justify-center">
                <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
                </svg>
                Save as New Version
              </button>
            </div>
          </div>
        ) : showDiff && versions.length >= 2 ? (
          <div className="p-4">
            <button
              onClick={() => setShowDiff(false)}
              className="mb-3 flex items-center gap-1 text-xs text-hermes-600 hover:text-hermes-700"
            >
              <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M10.5 19.5L3 12m0 0l7.5-7.5M3 12h18" />
              </svg>
              Back to History
            </button>
            <RecipeDiffViewer
              instanceName={stageLabel.name}
              versions={versions.map(v => ({
                version: v.version_no,
                config: v.config_json as Record<string, unknown>,
                created_by: v.created_by,
                change_note: v.change_note,
                created_at: v.created_at,
              }))}
            />
          </div>
        ) : (
          <div className="divide-y divide-slate-100">
            {/* Compare button */}
            {versions.length >= 2 && (
              <div className="px-4 py-2">
                <button
                  onClick={() => setShowDiff(true)}
                  className="flex w-full items-center justify-center gap-2 rounded-lg border border-hermes-200 bg-hermes-50 px-3 py-2 text-xs font-medium text-hermes-700 transition-colors hover:bg-hermes-100"
                >
                  <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M7.5 21L3 16.5m0 0L7.5 12M3 16.5h13.5m0-13.5L21 7.5m0 0L16.5 12M21 7.5H7.5" />
                  </svg>
                  Compare Versions (Diff)
                </button>
              </div>
            )}
            {versions.map((version) => (
              <div
                key={version.version_no}
                className={`px-4 py-3 ${version.is_current ? 'bg-hermes-50' : ''}`}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold text-slate-700">
                      v{version.version_no}
                    </span>
                    {version.is_current && (
                      <span className="rounded-full bg-hermes-100 px-2 py-0.5 text-[10px] font-medium text-hermes-700">
                        current
                      </span>
                    )}
                  </div>
                  <span className="text-[10px] text-slate-400">
                    {new Date(version.created_at).toLocaleString()}
                  </span>
                </div>
                <p className="mt-1 text-xs text-slate-500">{version.change_note}</p>
                <p className="mt-0.5 text-[10px] text-slate-400">by {version.created_by}</p>

                {/* Config preview */}
                <pre className="mt-2 rounded-lg bg-slate-50 p-2 text-[10px] text-slate-600">
                  {JSON.stringify(version.config_json, null, 2)}
                </pre>

                {!version.is_current && (
                  <button
                    onClick={() => {
                      setFormData(version.config_json as Record<string, unknown>);
                      setShowHistory(false);
                    }}
                    className="mt-2 text-[11px] font-medium text-hermes-600 hover:text-hermes-700"
                  >
                    Restore this version
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
