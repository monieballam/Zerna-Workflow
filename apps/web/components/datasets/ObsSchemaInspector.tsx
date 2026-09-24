'use client';

import { useMemo } from 'react';

// ── Types ─────────────────────────────────────────────────────────────────────

export interface ObsColumn {
  name: string;
  dtype: string;
}

export interface SchemaIssue {
  column: string;
  issueType: 'missing' | 'type_mismatch';
  expected?: string;
  actual?: string;
  message: string;
}

export interface ObsSchemaInspectorProps {
  columns: ObsColumn[];
  issues: SchemaIssue[];
  datasetName?: string;
}

// ── Issue Badge ───────────────────────────────────────────────────────────────

function IssueBadge({ type }: { type: SchemaIssue['issueType'] }) {
  const styles = type === 'missing' ? 'bg-red-100 text-red-700' : 'bg-yellow-100 text-yellow-700';
  const label = type === 'missing' ? 'Missing' : 'Type mismatch';
  return (
    <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${styles}`}>
      {label}
    </span>
  );
}

// ── Issues Panel ──────────────────────────────────────────────────────────────

function IssuesPanel({ issues }: { issues: SchemaIssue[] }) {
  if (issues.length === 0) {
    return (
      <div
        className="bg-green-50 border border-green-200 rounded-lg p-3 text-sm text-green-700"
        data-testid="schema-valid"
      >
        Schema is valid — no issues found.
      </div>
    );
  }

  return (
    <div className="border border-red-200 rounded-lg overflow-hidden" data-testid="schema-issues">
      <div className="bg-red-50 px-3 py-2 text-sm font-medium text-red-700">
        {issues.length} {issues.length === 1 ? 'issue' : 'issues'} found
      </div>
      <ul className="divide-y divide-red-100">
        {issues.map((issue, idx) => (
          <li
            key={`${issue.column}-${issue.issueType}-${idx}`}
            className="px-3 py-2 flex items-start gap-2"
          >
            <IssueBadge type={issue.issueType} />
            <div className="text-sm">
              <span className="font-mono font-medium text-gray-800">{issue.column}</span>
              <span className="text-gray-500 ml-1">— {issue.message}</span>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

// ── Column Table ──────────────────────────────────────────────────────────────

function ColumnTable({
  columns,
  issueColumns,
}: {
  columns: ObsColumn[];
  issueColumns: Set<string>;
}) {
  return (
    <div className="overflow-x-auto border border-gray-200 rounded-lg">
      <table className="min-w-full divide-y divide-gray-200" data-testid="obs-column-table">
        <thead className="bg-gray-50">
          <tr>
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">
              Column
            </th>
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">
              Type
            </th>
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">
              Status
            </th>
          </tr>
        </thead>
        <tbody>
          {columns.map((col) => (
            <tr key={col.name} className="border-b border-gray-100 hover:bg-gray-50">
              <td className="px-3 py-2 text-sm font-mono text-gray-800">{col.name}</td>
              <td className="px-3 py-2 text-sm text-gray-600">{col.dtype}</td>
              <td className="px-3 py-2">
                {issueColumns.has(col.name) ? (
                  <span className="text-xs text-red-600 font-medium">⚠ Issue</span>
                ) : (
                  <span className="text-xs text-green-600 font-medium">✓ OK</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Main Component ────────────────────────────────────────────────────────────

export default function ObsSchemaInspector({
  columns,
  issues,
  datasetName,
}: ObsSchemaInspectorProps) {
  const issueColumns = useMemo(() => new Set(issues.map((i) => i.column)), [issues]);

  return (
    <div className="space-y-4" data-testid="obs-schema-inspector">
      {datasetName && (
        <h2 className="text-lg font-semibold text-gray-900">
          {datasetName} — .obs Schema Inspector
        </h2>
      )}

      <div className="flex items-center gap-3 text-sm text-gray-500">
        <span>{columns.length} columns</span>
        <span>·</span>
        <span className={issues.length > 0 ? 'text-red-600 font-medium' : 'text-green-600'}>
          {issues.length} {issues.length === 1 ? 'issue' : 'issues'}
        </span>
      </div>

      <IssuesPanel issues={issues} />
      <ColumnTable columns={columns} issueColumns={issueColumns} />
    </div>
  );
}
