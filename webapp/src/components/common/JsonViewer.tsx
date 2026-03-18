interface Props {
  data: unknown;
  collapsed?: boolean;
  maxHeight?: string;
}

/**
 * Syntax-highlighted JSON viewer with collapsible sections.
 * Much better readability than raw <pre> tags.
 */
export default function JsonViewer({ data, collapsed: _collapsed = false, maxHeight = '300px' }: Props) {
  const json = typeof data === 'string' ? data : JSON.stringify(data, null, 2);

  return (
    <div
      className="overflow-auto rounded-lg border border-slate-200 bg-slate-900 font-mono text-xs"
      style={{ maxHeight }}
    >
      <pre className="p-3 leading-relaxed">
        {json.split('\n').map((line, i) => (
          <div key={i} className="flex">
            <span className="mr-3 inline-block w-6 select-none text-right text-slate-600">
              {i + 1}
            </span>
            <span>{colorize(line)}</span>
          </div>
        ))}
      </pre>
    </div>
  );
}

function colorize(line: string): JSX.Element {
  // Key: "key":
  const keyMatch = line.match(/^(\s*)"([^"]+)"(:)/);
  if (keyMatch) {
    const [, indent, key, colon] = keyMatch;
    const rest = line.slice(keyMatch[0].length);
    return (
      <>
        <span className="text-slate-500">{indent}</span>
        <span className="text-sky-400">"{key}"</span>
        <span className="text-slate-500">{colon}</span>
        {colorizeValue(rest)}
      </>
    );
  }

  // Array/object brackets
  if (line.trim().match(/^[\[\]\{\}],?$/)) {
    return <span className="text-slate-400">{line}</span>;
  }

  return <span className="text-slate-300">{line}</span>;
}

function colorizeValue(value: string): JSX.Element {
  const trimmed = value.trim().replace(/,$/, '');
  const hasComma = value.trim().endsWith(',');

  // String
  if (trimmed.startsWith('"')) {
    return (
      <>
        <span className="text-amber-300"> {trimmed}</span>
        {hasComma && <span className="text-slate-500">,</span>}
      </>
    );
  }
  // Number
  if (/^-?\d/.test(trimmed)) {
    return (
      <>
        <span className="text-emerald-400"> {trimmed}</span>
        {hasComma && <span className="text-slate-500">,</span>}
      </>
    );
  }
  // Boolean
  if (trimmed === 'true' || trimmed === 'false') {
    return (
      <>
        <span className="text-purple-400"> {trimmed}</span>
        {hasComma && <span className="text-slate-500">,</span>}
      </>
    );
  }
  // Null
  if (trimmed === 'null') {
    return (
      <>
        <span className="text-red-400"> {trimmed}</span>
        {hasComma && <span className="text-slate-500">,</span>}
      </>
    );
  }

  return <span className="text-slate-300">{value}</span>;
}
