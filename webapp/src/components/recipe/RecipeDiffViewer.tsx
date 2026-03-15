import { useState } from 'react';
import ReactDiffViewer, { DiffMethod } from 'react-diff-viewer-continued';

interface RecipeVersion {
  version: number;
  config: Record<string, unknown>;
  created_by: string;
  change_note: string;
  created_at: string;
}

interface Props {
  versions: RecipeVersion[];
  instanceName: string;
}

/**
 * Git-diff style Recipe version comparison.
 * Side-by-side or unified view with syntax highlighting.
 * Inspired by: GitHub diff, GitLab merge request, kdiff3.
 */
export default function RecipeDiffViewer({ versions, instanceName }: Props) {
  const [leftVersion, setLeftVersion] = useState(versions.length > 1 ? versions.length - 2 : 0);
  const [rightVersion, setRightVersion] = useState(versions.length - 1);
  const [splitView, setSplitView] = useState(true);

  if (versions.length < 2) {
    return (
      <div className="rounded-lg border border-slate-200 bg-white p-6 text-center text-sm text-slate-500">
        Need at least 2 versions to compare. Current: v{versions[0]?.version ?? 0}
      </div>
    );
  }

  const left = versions[leftVersion];
  const right = versions[rightVersion];

  const leftJson = JSON.stringify(left.config, null, 2);
  const rightJson = JSON.stringify(right.config, null, 2);

  // Count changes
  const leftLines = leftJson.split('\n');
  const rightLines = rightJson.split('\n');
  const additions = rightLines.filter(l => !leftLines.includes(l)).length;
  const deletions = leftLines.filter(l => !rightLines.includes(l)).length;

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-lg font-bold text-slate-900">{instanceName}</h3>
          <p className="text-xs text-slate-500">Recipe Version Comparison</p>
        </div>
        <div className="flex items-center gap-3">
          <span className="rounded bg-green-100 px-2 py-0.5 text-xs font-mono font-bold text-green-700">
            +{additions}
          </span>
          <span className="rounded bg-red-100 px-2 py-0.5 text-xs font-mono font-bold text-red-700">
            -{deletions}
          </span>
          <button
            onClick={() => setSplitView(!splitView)}
            className="rounded-lg border border-slate-200 px-3 py-1 text-xs font-medium text-slate-600 hover:bg-slate-50"
          >
            {splitView ? 'Unified' : 'Side-by-Side'}
          </button>
        </div>
      </div>

      {/* Version selectors */}
      <div className="flex gap-4">
        <div className="flex-1">
          <label className="mb-1 block text-[10px] font-semibold uppercase tracking-wider text-slate-500">
            Base (older)
          </label>
          <select
            value={leftVersion}
            onChange={e => setLeftVersion(Number(e.target.value))}
            className="w-full rounded-lg border border-slate-200 px-3 py-1.5 text-xs"
          >
            {versions.map((v, i) => (
              <option key={i} value={i}>
                v{v.version} — {v.change_note || 'No note'} ({new Date(v.created_at).toLocaleDateString()})
              </option>
            ))}
          </select>
        </div>
        <div className="flex items-end pb-1">
          <svg className="h-5 w-5 text-slate-400" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 4.5L21 12m0 0l-7.5 7.5M21 12H3" />
          </svg>
        </div>
        <div className="flex-1">
          <label className="mb-1 block text-[10px] font-semibold uppercase tracking-wider text-slate-500">
            Compare (newer)
          </label>
          <select
            value={rightVersion}
            onChange={e => setRightVersion(Number(e.target.value))}
            className="w-full rounded-lg border border-slate-200 px-3 py-1.5 text-xs"
          >
            {versions.map((v, i) => (
              <option key={i} value={i}>
                v{v.version} — {v.change_note || 'No note'} ({new Date(v.created_at).toLocaleDateString()})
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Version metadata */}
      <div className="flex gap-4">
        <div className="flex-1 rounded-lg bg-red-50 p-2">
          <p className="text-[10px] font-bold text-red-600">v{left.version}</p>
          <p className="text-[10px] text-slate-600">by {left.created_by}</p>
          <p className="text-[10px] text-slate-400">{left.change_note}</p>
        </div>
        <div className="flex-1 rounded-lg bg-green-50 p-2">
          <p className="text-[10px] font-bold text-green-600">v{right.version}</p>
          <p className="text-[10px] text-slate-600">by {right.created_by}</p>
          <p className="text-[10px] text-slate-400">{right.change_note}</p>
        </div>
      </div>

      {/* Diff viewer */}
      <div className="overflow-hidden rounded-lg border border-slate-200">
        <ReactDiffViewer
          oldValue={leftJson}
          newValue={rightJson}
          splitView={splitView}
          compareMethod={DiffMethod.WORDS}
          leftTitle={`v${left.version}`}
          rightTitle={`v${right.version}`}
          styles={{
            variables: {
              light: {
                diffViewerBackground: '#ffffff',
                addedBackground: '#e6ffec',
                addedColor: '#1a7f37',
                removedBackground: '#ffebe9',
                removedColor: '#cf222e',
                wordAddedBackground: '#abf2bc',
                wordRemovedBackground: '#ff818266',
                addedGutterBackground: '#ccffd8',
                removedGutterBackground: '#ffd7d5',
                gutterBackground: '#f6f8fa',
                gutterBackgroundDark: '#f0f1f3',
                highlightBackground: '#fffbdd',
                highlightGutterBackground: '#fff5b1',
                codeFoldGutterBackground: '#dbedff',
                codeFoldBackground: '#f1f8ff',
                emptyLineBackground: '#fafbfc',
              },
            },
            contentText: { fontSize: '12px', lineHeight: '20px', fontFamily: 'ui-monospace, monospace' },
            gutter: { fontSize: '11px', minWidth: '40px' },
          }}
        />
      </div>
    </div>
  );
}
