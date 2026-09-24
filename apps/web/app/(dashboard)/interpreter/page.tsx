'use client';

import { useState, useCallback, useRef, useEffect } from 'react';
import { parseUTC } from '@/lib/dates';

// ── Types ─────────────────────────────────────────────────────────────────────

interface QueryResult {
  query_id: string;
  intent: string;
  result_text: string;
  result_data: Record<string, unknown>;
  suggestions: string[];
  error: string | null;
  processed_at: string;
}

interface HistoryEntry {
  query_id: string;
  session_id: string;
  query_text: string;
  result: QueryResult;
  created_at: string;
}

// ── Intent badge ──────────────────────────────────────────────────────────────

const INTENT_COLORS: Record<string, string> = {
  expression_lookup: 'bg-blue-100 text-blue-700',
  comparison: 'bg-purple-100 text-purple-700',
  plot_generation: 'bg-green-100 text-green-700',
  cell_type_query: 'bg-amber-100 text-amber-700',
  marker_query: 'bg-teal-100 text-teal-700',
  unknown: 'bg-gray-100 text-gray-500',
};

function IntentBadge({ intent }: { intent: string }) {
  const cls = INTENT_COLORS[intent] ?? INTENT_COLORS.unknown;
  return (
    <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${cls}`}>
      {intent.replace(/_/g, ' ')}
    </span>
  );
}

// ── History entry card ────────────────────────────────────────────────────────

function HistoryCard({ entry }: { entry: HistoryEntry }) {
  const { result } = entry;
  const ts = (parseUTC(entry.created_at) ?? new Date()).toLocaleTimeString();

  return (
    <div
      className="bg-white border border-gray-200 rounded-lg p-4 space-y-2"
      data-testid={`history-entry-${entry.query_id}`}
    >
      <div className="flex items-center justify-between">
        <IntentBadge intent={result.intent} />
        <span className="text-xs text-gray-400">{ts}</span>
      </div>

      <p className="text-sm font-medium text-gray-800">{entry.query_text}</p>

      {result.error ? (
        <div className="text-sm text-red-600 bg-red-50 rounded p-2">
          {result.error}
          {result.suggestions.length > 0 && (
            <ul className="mt-1 list-disc list-inside text-xs text-red-500">
              {result.suggestions.map((s, i) => (
                <li key={i}>{s}</li>
              ))}
            </ul>
          )}
        </div>
      ) : (
        <p className="text-sm text-gray-600">{result.result_text}</p>
      )}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function InterpreterPage() {
  const [query, setQuery] = useState('');
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to latest result
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [history]);

  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      const trimmed = query.trim();
      if (!trimmed) return;

      setIsLoading(true);
      setError(null);

      try {
        const res = await fetch('/api/proxy/interpreter/query', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ query: trimmed }),
        });

        if (!res.ok) throw new Error(`Request failed: ${res.status}`);

        const rawData: unknown = await res.json();
        const data = rawData as { result: QueryResult; history: HistoryEntry[] };
        setHistory(data.history);
        setQuery('');
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Unknown error');
      } finally {
        setIsLoading(false);
      }
    },
    [query]
  );

  return (
    <div className="flex flex-col h-full max-h-[calc(100vh-8rem)]" data-testid="interpreter-page">
      {/* Header */}
      <div className="mb-4">
        <h1 className="text-2xl font-bold text-gray-900">Interpreter</h1>
        <p className="text-sm text-gray-500 mt-1">
          Ask questions about your analysis results in plain English.
        </p>
      </div>

      {/* Session history */}
      <div className="flex-1 overflow-y-auto space-y-3 mb-4 pr-1" data-testid="session-history">
        {history.length === 0 && !isLoading && (
          <div className="flex items-center justify-center h-48 text-gray-400 text-sm">
            No queries yet. Try asking something below.
          </div>
        )}
        {history.map((entry) => (
          <HistoryCard key={entry.query_id} entry={entry} />
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Error banner */}
      {error && (
        <div className="mb-2 text-sm text-red-600 bg-red-50 rounded p-2" data-testid="query-error">
          {error}
        </div>
      )}

      {/* Query input */}
      <form
        onSubmit={(event) => {
          void handleSubmit(event);
        }}
        className="flex gap-2"
        data-testid="query-form"
      >
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="e.g. Show expression of CD3E in T cells"
          className="flex-1 rounded-lg border border-gray-300 px-4 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          disabled={isLoading}
          aria-label="Natural language query"
          data-testid="query-input"
        />
        <button
          type="submit"
          disabled={isLoading || !query.trim()}
          className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
          data-testid="query-submit"
        >
          {isLoading ? 'Processing…' : 'Ask'}
        </button>
      </form>
    </div>
  );
}
