import { useMemo, useState } from 'react';
import { StageType } from '../types';
import type { Recipe } from '../types';
import RecipeDiffViewer from '../components/recipe/RecipeDiffViewer';

// ============================================================
// Types
// ============================================================

interface RecipeInstance {
  id: number;
  name: string;
  description: string;
  stageType: StageType;
  definitionCode: string;
  currentVersion: number;
  versions: Recipe[];
  usedBy: { pipelineId: number; pipelineName: string }[];
}

type GroupKey = 'collector' | 'process' | 'export';

// ============================================================
// Demo Data
// ============================================================

const demoRecipes: RecipeInstance[] = [
  // Collector Recipes
  {
    id: 1,
    name: 'Vendor-A API 수집설정',
    description: 'Vendor-A REST API 주문 데이터 수집 파라미터',
    stageType: StageType.COLLECT,
    definitionCode: 'rest-api',
    currentVersion: 3,
    versions: [
      { version_no: 3, config_json: { batch_size: 200, date_range_days: 7, include_deleted: true, custom_query_params: 'status=active' }, change_note: 'batch_size 200으로 증가, include_deleted 활성화', is_current: true, created_by: 'operator:kim', created_at: '2026-03-15T14:30:00Z' },
      { version_no: 2, config_json: { batch_size: 100, date_range_days: 7, include_deleted: false, custom_query_params: '' }, change_note: 'date_range 3일 → 7일 확장', is_current: false, created_by: 'operator:kim', created_at: '2026-03-10T09:00:00Z' },
      { version_no: 1, config_json: { batch_size: 50, date_range_days: 3, include_deleted: false, custom_query_params: '' }, change_note: '초기 설정', is_current: false, created_by: 'admin', created_at: '2026-03-01T09:00:00Z' },
    ],
    usedBy: [
      { pipelineId: 1, pipelineName: 'Vendor-A 주문 수집' },
      { pipelineId: 6, pipelineName: '로그 수집 파이프라인' },
    ],
  },
  {
    id: 2,
    name: 'FTP 장비 데이터 수집',
    description: 'FTP/SFTP 서버에서 장비 로그 파일 수집 — 재귀 탐색, 날짜 폴더, 완료 마커 감지',
    stageType: StageType.COLLECT,
    definitionCode: 'ftp-sftp-collector',
    currentVersion: 3,
    versions: [
      { version_no: 3, config_json: { remote_path: '/data/equipment/', recursive: true, max_depth: 3, folder_pattern: { enabled: true, format: 'yyyyMMdd', lookback_days: 7, timezone: 'Asia/Seoul' }, file_filter: { filename_regex: '.*\\.csv$', exclude_patterns: ['\\.tmp$', '^\\.'], exclude_zero_byte: true, min_size_bytes: 100, max_age_hours: 168 }, ordering: 'NEWEST_FIRST', discovery_mode: 'ALL_NEW', completion_check: { strategy: 'MARKER_FILE', marker_suffix: '.done' }, post_action: { action: 'MOVE', move_target: '/data/archive/', conflict_resolution: 'TIMESTAMP' }, checksum_verification: true }, change_note: '완료 마커(.done) 감지 추가, archive 이동 활성화', is_current: true, created_by: 'operator:kim', created_at: '2026-03-15T14:00:00Z' },
      { version_no: 2, config_json: { remote_path: '/data/equipment/', recursive: true, max_depth: 3, folder_pattern: { enabled: true, format: 'yyyyMMdd', lookback_days: 3, timezone: 'Asia/Seoul' }, file_filter: { filename_regex: '.*\\.csv$', exclude_patterns: ['\\.tmp$'], exclude_zero_byte: true }, ordering: 'NEWEST_FIRST', discovery_mode: 'ALL_NEW', completion_check: { strategy: 'NONE' }, post_action: { action: 'KEEP' }, checksum_verification: false }, change_note: '날짜 폴더 패턴 적용 (yyyyMMdd), lookback 3일', is_current: false, created_by: 'operator:kim', created_at: '2026-03-10T09:00:00Z' },
      { version_no: 1, config_json: { remote_path: '/logs/equipment/', recursive: true, max_depth: -1, file_filter: { filename_regex: '.*\\.csv$' }, ordering: 'NEWEST_FIRST', discovery_mode: 'ALL', post_action: { action: 'KEEP' } }, change_note: '초기 설정', is_current: false, created_by: 'admin', created_at: '2026-03-05T11:00:00Z' },
    ],
    usedBy: [
      { pipelineId: 2, pipelineName: '장비 데이터 수집' },
      { pipelineId: 5, pipelineName: '실시간 이상탐지' },
    ],
  },
  // Process Recipes
  {
    id: 3,
    name: '이상탐지 파라미터',
    description: '통계 기반 이상탐지 알고리즘 튜닝 파라미터',
    stageType: StageType.PROCESS,
    definitionCode: 'anomaly-detector',
    currentVersion: 5,
    versions: [
      { version_no: 5, config_json: { threshold: 3.5, method: 'modified-z-score', window_size: 200, sensitivity: 'high', alert_on_anomaly: true, min_samples: 30 }, change_note: 'modified z-score 전환, window 200, min_samples 30으로 낮춤', is_current: true, created_by: 'operator:alex', created_at: '2026-03-16T10:15:00Z' },
      { version_no: 4, config_json: { threshold: 3.0, method: 'z-score', window_size: 150, sensitivity: 'high', alert_on_anomaly: true, min_samples: 50 }, change_note: 'window 150으로 증가, sensitivity high', is_current: false, created_by: 'operator:alex', created_at: '2026-03-14T16:00:00Z' },
      { version_no: 3, config_json: { threshold: 3.0, method: 'z-score', window_size: 100, sensitivity: 'medium', alert_on_anomaly: true, min_samples: 50 }, change_note: 'threshold 3.0으로 상향', is_current: false, created_by: 'operator:kim', created_at: '2026-03-12T09:30:00Z' },
      { version_no: 2, config_json: { threshold: 2.5, method: 'z-score', window_size: 100, sensitivity: 'medium', alert_on_anomaly: false, min_samples: 50 }, change_note: 'alert 비활성화 (테스트 기간)', is_current: false, created_by: 'operator:kim', created_at: '2026-03-08T14:00:00Z' },
      { version_no: 1, config_json: { threshold: 2.5, method: 'z-score', window_size: 100, sensitivity: 'medium', alert_on_anomaly: true, min_samples: 50 }, change_note: '초기 설정', is_current: false, created_by: 'admin', created_at: '2026-03-01T09:00:00Z' },
    ],
    usedBy: [
      { pipelineId: 1, pipelineName: 'Vendor-A 주문 수집' },
      { pipelineId: 4, pipelineName: '센서 데이터 분석' },
      { pipelineId: 5, pipelineName: '실시간 이상탐지' },
    ],
  },
  {
    id: 4,
    name: '데이터 변환 규칙',
    description: 'JSON/CSV 간 변환 매핑 규칙',
    stageType: StageType.PROCESS,
    definitionCode: 'data-transformer',
    currentVersion: 2,
    versions: [
      { version_no: 2, config_json: { input_format: 'json', output_format: 'csv', flatten_nested: true, null_handling: 'empty_string', date_format: 'ISO8601' }, change_note: 'null_handling 추가, date_format ISO8601', is_current: true, created_by: 'operator:alex', created_at: '2026-03-13T11:00:00Z' },
      { version_no: 1, config_json: { input_format: 'json', output_format: 'csv', flatten_nested: true }, change_note: '초기 설정', is_current: false, created_by: 'admin', created_at: '2026-03-02T10:00:00Z' },
    ],
    usedBy: [
      { pipelineId: 4, pipelineName: '센서 데이터 분석' },
    ],
  },
  // Export Recipes
  {
    id: 5,
    name: 'S3 출력 설정',
    description: 'S3 버킷 출력 파라미터 (파티션, 배치, 메타데이터)',
    stageType: StageType.EXPORT,
    definitionCode: 's3-upload',
    currentVersion: 2,
    versions: [
      { version_no: 2, config_json: { batch_mode: true, max_batch_size: 2000, include_metadata: true, partition_by: 'date', custom_tags: 'env:prod,team:data' }, change_note: 'batch_size 2000으로 증가, custom_tags 추가', is_current: true, created_by: 'operator:kim', created_at: '2026-03-14T09:00:00Z' },
      { version_no: 1, config_json: { batch_mode: true, max_batch_size: 1000, include_metadata: true, partition_by: 'date', custom_tags: '' }, change_note: '초기 설정', is_current: false, created_by: 'admin', created_at: '2026-03-01T09:00:00Z' },
    ],
    usedBy: [
      { pipelineId: 1, pipelineName: 'Vendor-A 주문 수집' },
      { pipelineId: 4, pipelineName: '센서 데이터 분석' },
    ],
  },
  {
    id: 6,
    name: 'DB 적재 설정',
    description: 'PostgreSQL 데이터 적재 파라미터',
    stageType: StageType.EXPORT,
    definitionCode: 'db-writer',
    currentVersion: 1,
    versions: [
      { version_no: 1, config_json: { batch_mode: true, max_batch_size: 500, include_metadata: false, upsert_mode: true, conflict_key: 'id' }, change_note: '초기 설정', is_current: true, created_by: 'admin', created_at: '2026-03-03T10:00:00Z' },
    ],
    usedBy: [
      { pipelineId: 2, pipelineName: '장비 데이터 수집' },
    ],
  },
];

// ============================================================
// Constants
// ============================================================

const GROUP_CONFIG: Record<GroupKey, { label: string; stageType: StageType; color: string; bgLight: string; textColor: string; borderColor: string; iconPath: string }> = {
  collector: {
    label: 'Collector Recipes',
    stageType: StageType.COLLECT,
    color: 'blue',
    bgLight: 'bg-blue-50',
    textColor: 'text-blue-700',
    borderColor: 'border-blue-200',
    iconPath: 'M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3',
  },
  process: {
    label: 'Process Recipes',
    stageType: StageType.PROCESS,
    color: 'purple',
    bgLight: 'bg-purple-50',
    textColor: 'text-purple-700',
    borderColor: 'border-purple-200',
    iconPath: 'M9.75 3.104v5.714a2.25 2.25 0 01-.659 1.591L5 14.5M9.75 3.104c-.251.023-.501.05-.75.082m.75-.082a24.301 24.301 0 014.5 0m0 0v5.714c0 .597.237 1.17.659 1.591L19.8 15.3M14.25 3.104c.251.023.501.05.75.082M19.8 15.3l-1.57.393A9.065 9.065 0 0112 15a9.065 9.065 0 00-6.23.693L5 14.5m14.8.8l1.402 1.402c1.232 1.232.65 3.318-1.067 3.611A48.309 48.309 0 0112 21c-2.773 0-5.491-.235-8.135-.687-1.718-.293-2.3-2.379-1.067-3.61L5 14.5',
  },
  export: {
    label: 'Export Recipes',
    stageType: StageType.EXPORT,
    color: 'emerald',
    bgLight: 'bg-emerald-50',
    textColor: 'text-emerald-700',
    borderColor: 'border-emerald-200',
    iconPath: 'M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5',
  },
};

const STAGE_TO_GROUP: Record<StageType, GroupKey> = {
  [StageType.COLLECT]: 'collector',
  [StageType.PROCESS]: 'process',
  [StageType.EXPORT]: 'export',
};

// ============================================================
// JSON Syntax Highlighter
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

// ============================================================
// Main Component
// ============================================================

export default function RecipeManagementPage() {
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedRecipeId, setSelectedRecipeId] = useState<number | null>(3); // Default: 이상탐지 파라미터
  const [selectedVersionIdx, setSelectedVersionIdx] = useState(0);
  const [showDiff, setShowDiff] = useState(false);
  const [expandedGroups, setExpandedGroups] = useState<Set<GroupKey>>(new Set(['collector', 'process', 'export']));

  // Filter recipes by search
  const filteredRecipes = useMemo(() => {
    if (!searchQuery.trim()) return demoRecipes;
    const q = searchQuery.toLowerCase();
    return demoRecipes.filter(
      (r) =>
        r.name.toLowerCase().includes(q) ||
        r.description.toLowerCase().includes(q) ||
        r.definitionCode.toLowerCase().includes(q)
    );
  }, [searchQuery]);

  // Group recipes by type
  const groupedRecipes = useMemo(() => {
    const groups: Record<GroupKey, RecipeInstance[]> = { collector: [], process: [], export: [] };
    for (const r of filteredRecipes) {
      groups[STAGE_TO_GROUP[r.stageType]].push(r);
    }
    return groups;
  }, [filteredRecipes]);

  const selectedRecipe = demoRecipes.find((r) => r.id === selectedRecipeId) ?? null;
  const selectedVersion = selectedRecipe?.versions[selectedVersionIdx] ?? null;
  const groupConfig = selectedRecipe ? GROUP_CONFIG[STAGE_TO_GROUP[selectedRecipe.stageType]] : null;

  function toggleGroup(key: GroupKey) {
    setExpandedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  return (
    <div className="flex h-[calc(100vh-7rem)] flex-col">
      {/* Header */}
      <div className="flex items-center justify-between pb-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Recipes</h1>
          <p className="mt-1 text-sm text-slate-500">
            Global recipe management &mdash; versioned business parameters for all processors
          </p>
        </div>
        <button className="btn-primary">
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
          </svg>
          New Recipe
        </button>
      </div>

      {/* Master-Detail Layout */}
      <div className="flex flex-1 overflow-hidden rounded-xl border border-slate-200 bg-white">
        {/* Left Panel: Recipe List */}
        <div className="flex w-80 shrink-0 flex-col border-r border-slate-200 bg-slate-50/50">
          {/* Search */}
          <div className="border-b border-slate-200 p-3">
            <div className="relative">
              <svg className="absolute left-2.5 top-2 h-4 w-4 text-slate-400" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
              </svg>
              <input
                type="text"
                placeholder="Search recipes..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full rounded-lg border border-slate-200 bg-white py-1.5 pl-8 pr-3 text-xs text-slate-700 placeholder-slate-400 focus:border-hermes-400 focus:outline-none focus:ring-1 focus:ring-hermes-400"
              />
            </div>
          </div>

          {/* Grouped Recipe List */}
          <div className="flex-1 overflow-auto">
            {(Object.entries(GROUP_CONFIG) as [GroupKey, typeof GROUP_CONFIG[GroupKey]][]).map(([key, cfg]) => {
              const recipes = groupedRecipes[key];
              const isExpanded = expandedGroups.has(key);

              return (
                <div key={key}>
                  {/* Group Header */}
                  <button
                    onClick={() => toggleGroup(key)}
                    className={`flex w-full items-center gap-2 border-b px-3 py-2 text-left ${cfg.borderColor} ${cfg.bgLight}`}
                  >
                    <svg
                      className={`h-3 w-3 transition-transform ${cfg.textColor} ${isExpanded ? 'rotate-90' : ''}`}
                      fill="none" viewBox="0 0 24 24" strokeWidth={2.5} stroke="currentColor"
                    >
                      <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
                    </svg>
                    <svg className={`h-4 w-4 ${cfg.textColor}`} fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" d={cfg.iconPath} />
                    </svg>
                    <span className={`text-[11px] font-bold uppercase tracking-wider ${cfg.textColor}`}>
                      {cfg.label}
                    </span>
                    <span className={`ml-auto rounded-full px-1.5 py-0.5 text-[10px] font-medium ${cfg.bgLight} ${cfg.textColor}`}>
                      {recipes.length}
                    </span>
                  </button>

                  {/* Recipe Items */}
                  {isExpanded && recipes.map((recipe) => (
                    <button
                      key={recipe.id}
                      onClick={() => { setSelectedRecipeId(recipe.id); setSelectedVersionIdx(0); setShowDiff(false); }}
                      className={`flex w-full flex-col border-b border-slate-100 px-4 py-3 text-left transition-colors ${
                        selectedRecipeId === recipe.id
                          ? 'bg-white shadow-sm'
                          : 'hover:bg-white/60'
                      }`}
                    >
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-semibold text-slate-800">{recipe.name}</span>
                      </div>
                      <p className="mt-0.5 text-[11px] text-slate-500 line-clamp-1">{recipe.description}</p>
                      <div className="mt-1.5 flex items-center gap-2">
                        <span className="rounded bg-slate-200 px-1.5 py-0.5 text-[10px] font-bold text-slate-600">
                          v{recipe.currentVersion}
                        </span>
                        <span className="text-[10px] text-slate-400">
                          {recipe.versions.length} version{recipe.versions.length !== 1 ? 's' : ''}
                        </span>
                        <span className="text-[10px] text-slate-400">
                          &middot; {recipe.usedBy.length} pipeline{recipe.usedBy.length !== 1 ? 's' : ''}
                        </span>
                      </div>
                    </button>
                  ))}

                  {isExpanded && recipes.length === 0 && (
                    <div className="px-4 py-3 text-[11px] text-slate-400">No recipes found</div>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        {/* Right Panel: Recipe Detail */}
        <div className="flex flex-1 flex-col overflow-hidden">
          {selectedRecipe && groupConfig ? (
            showDiff && selectedRecipe.versions.length >= 2 ? (
              /* Diff View */
              <div className="flex flex-1 flex-col overflow-auto">
                <div className="border-b border-slate-200 px-6 py-3">
                  <button
                    onClick={() => setShowDiff(false)}
                    className="flex items-center gap-1 text-xs font-medium text-purple-600 hover:text-purple-700"
                  >
                    <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" d="M10.5 19.5L3 12m0 0l7.5-7.5M3 12h18" />
                    </svg>
                    Back to Detail
                  </button>
                </div>
                <div className="flex-1 overflow-auto p-6">
                  <RecipeDiffViewer
                    instanceName={selectedRecipe.name}
                    versions={selectedRecipe.versions.map((v) => ({
                      version: v.version_no,
                      config: v.config_json as Record<string, unknown>,
                      created_by: v.created_by,
                      change_note: v.change_note,
                      created_at: v.created_at,
                    }))}
                  />
                </div>
              </div>
            ) : (
              /* Detail View */
              <div className="flex flex-1 flex-col overflow-auto">
                {/* Recipe Header */}
                <div className={`border-b px-6 py-4 ${groupConfig.bgLight}`}>
                  <div className="flex items-center justify-between">
                    <div>
                      <div className="flex items-center gap-2">
                        <h2 className="text-lg font-bold text-slate-900">{selectedRecipe.name}</h2>
                        <span className={`rounded px-2 py-0.5 text-[10px] font-bold uppercase ${groupConfig.bgLight} ${groupConfig.textColor} border ${groupConfig.borderColor}`}>
                          {STAGE_TO_GROUP[selectedRecipe.stageType]}
                        </span>
                      </div>
                      <p className="mt-1 text-xs text-slate-500">{selectedRecipe.description}</p>
                      <p className="mt-0.5 text-[11px] text-slate-400">
                        Definition: <span className="font-mono">{selectedRecipe.definitionCode}</span>
                      </p>
                    </div>
                    <div className="flex items-center gap-2">
                      {selectedRecipe.versions.length >= 2 && (
                        <button
                          onClick={() => setShowDiff(true)}
                          className="flex items-center gap-1 rounded-lg border border-purple-200 bg-purple-50 px-3 py-1.5 text-xs font-medium text-purple-700 hover:bg-purple-100"
                        >
                          <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" d="M7.5 21L3 16.5m0 0L7.5 12M3 16.5h13.5m0-13.5L21 7.5m0 0L16.5 12M21 7.5H7.5" />
                          </svg>
                          Compare Versions
                        </button>
                      )}
                      <button className="flex items-center gap-1 rounded-lg border border-blue-200 bg-blue-50 px-3 py-1.5 text-xs font-medium text-blue-700 hover:bg-blue-100">
                        <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931zm0 0L19.5 7.125M18 14v4.75A2.25 2.25 0 0115.75 21H5.25A2.25 2.25 0 013 18.75V8.25A2.25 2.25 0 015.25 6H10" />
                        </svg>
                        Edit Current
                      </button>
                      <button className="btn-primary text-xs">
                        <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
                        </svg>
                        New Version
                      </button>
                    </div>
                  </div>
                </div>

                {/* Content area: Version Timeline (left) + Config (right) */}
                <div className="flex flex-1 overflow-hidden">
                  {/* Version Timeline */}
                  <div className="w-48 shrink-0 overflow-auto border-r border-slate-200 bg-slate-50/50">
                    <div className="border-b border-slate-200 px-3 py-2">
                      <span className="text-[10px] font-bold uppercase tracking-wider text-slate-500">
                        Versions ({selectedRecipe.versions.length})
                      </span>
                    </div>
                    {selectedRecipe.versions.map((v, idx) => (
                      <button
                        key={v.version_no}
                        onClick={() => setSelectedVersionIdx(idx)}
                        className={`flex w-full flex-col border-b border-slate-100 px-3 py-2.5 text-left transition-colors ${
                          selectedVersionIdx === idx ? 'bg-white shadow-sm' : 'hover:bg-white/60'
                        }`}
                      >
                        <div className="flex items-center gap-1.5">
                          <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${
                            selectedVersionIdx === idx ? 'bg-slate-700 text-white' : 'bg-slate-200 text-slate-600'
                          }`}>
                            v{v.version_no}
                          </span>
                          {v.is_current && (
                            <span className="rounded-full bg-green-100 px-1.5 py-0.5 text-[9px] font-bold text-green-700">
                              current
                            </span>
                          )}
                        </div>
                        <span className="mt-1 text-[10px] text-slate-500 line-clamp-2">{v.change_note}</span>
                        <div className="mt-0.5 flex items-center gap-1">
                          <span className="text-[9px] text-slate-400">{v.created_by}</span>
                          <span className="text-[9px] text-slate-300">&middot;</span>
                          <span className="text-[9px] text-slate-400">{new Date(v.created_at).toLocaleDateString()}</span>
                        </div>
                      </button>
                    ))}
                  </div>

                  {/* Config Detail */}
                  <div className="flex-1 overflow-auto p-5">
                    {selectedVersion && (
                      <div className="space-y-4">
                        {/* Version Info */}
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <span className="rounded bg-slate-700 px-2 py-0.5 text-xs font-bold text-white">
                              v{selectedVersion.version_no}
                            </span>
                            {selectedVersion.is_current && (
                              <span className="rounded-full bg-green-100 px-2 py-0.5 text-[10px] font-bold text-green-700">
                                current
                              </span>
                            )}
                          </div>
                          {!selectedVersion.is_current && (
                            <button className="flex items-center gap-1 rounded-lg border border-amber-200 bg-amber-50 px-3 py-1.5 text-xs font-medium text-amber-700 hover:bg-amber-100">
                              <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                                <path strokeLinecap="round" strokeLinejoin="round" d="M9 15L3 9m0 0l6-6M3 9h12a6 6 0 010 12h-3" />
                              </svg>
                              Publish this Version
                            </button>
                          )}
                        </div>

                        {/* Metadata */}
                        <div className="flex gap-4 text-xs text-slate-600">
                          <div>
                            <span className="font-medium text-slate-500">Author:</span> {selectedVersion.created_by}
                          </div>
                          <div>
                            <span className="font-medium text-slate-500">Date:</span> {new Date(selectedVersion.created_at).toLocaleString()}
                          </div>
                        </div>
                        <div className="rounded-lg bg-slate-50 px-3 py-2">
                          <span className="text-[10px] font-medium text-slate-500">Change Note:</span>
                          <p className="text-xs text-slate-700">{selectedVersion.change_note}</p>
                        </div>

                        {/* Config JSON */}
                        <div>
                          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">Configuration</h4>
                          <JsonPreview data={selectedVersion.config_json} />
                        </div>

                        {/* Used By Pipelines */}
                        <div>
                          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">
                            Used by ({selectedRecipe.usedBy.length} pipeline{selectedRecipe.usedBy.length !== 1 ? 's' : ''})
                          </h4>
                          <div className="flex flex-wrap gap-2">
                            {selectedRecipe.usedBy.map((p) => (
                              <span
                                key={p.pipelineId}
                                className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-white px-3 py-1 text-xs text-slate-700 shadow-sm"
                              >
                                <svg className="h-3 w-3 text-slate-400" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                                  <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25H12" />
                                </svg>
                                {p.pipelineName}
                              </span>
                            ))}
                          </div>
                          {selectedRecipe.usedBy.length > 0 && (
                            <p className="mt-2 text-[10px] text-slate-400">
                              Changing the current version will affect all active pipelines at their next execution.
                            </p>
                          )}
                        </div>

                        {/* Impact Warning for non-current versions */}
                        {!selectedVersion.is_current && selectedRecipe.usedBy.length > 0 && (
                          <div className="rounded-lg border border-amber-200 bg-amber-50 p-3">
                            <div className="flex items-center gap-2">
                              <svg className="h-4 w-4 text-amber-600" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                                <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
                              </svg>
                              <span className="text-xs font-medium text-amber-800">
                                Publishing v{selectedVersion.version_no} will affect {selectedRecipe.usedBy.length} active pipeline{selectedRecipe.usedBy.length !== 1 ? 's' : ''}.
                              </span>
                            </div>
                            <ul className="mt-1.5 ml-6 list-disc text-[11px] text-amber-700">
                              {selectedRecipe.usedBy.map((p) => (
                                <li key={p.pipelineId}>{p.pipelineName}</li>
                              ))}
                            </ul>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )
          ) : (
            /* Empty state */
            <div className="flex flex-1 items-center justify-center">
              <div className="text-center">
                <svg className="mx-auto h-12 w-12 text-slate-300" fill="none" viewBox="0 0 24 24" strokeWidth={1} stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 6.042A8.967 8.967 0 006 3.75c-1.052 0-2.062.18-3 .512v14.25A8.987 8.987 0 016 18c2.305 0 4.408.867 6 2.292m0-14.25a8.966 8.966 0 016-2.292c1.052 0 2.062.18 3 .512v14.25A8.987 8.987 0 0018 18a8.967 8.967 0 00-6 2.292m0-14.25v14.25" />
                </svg>
                <p className="mt-3 text-sm font-medium text-slate-500">Select a recipe to view details</p>
                <p className="mt-1 text-xs text-slate-400">Version history, configuration, and pipeline usage</p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
