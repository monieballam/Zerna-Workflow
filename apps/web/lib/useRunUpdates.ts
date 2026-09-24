'use client';

import { useEffect, useRef, useState } from 'react';
import type { Run } from '@zerna/sdk';

const POLL_INTERVAL_MS = 5000;
const ACTIVE_STATUSES = new Set<Run['status']>(['queued', 'running']);

async function fetchRun(runId: string): Promise<Run | null> {
  const response = await fetch(`/api/proxy/v1/runs/${runId}`, {
    cache: 'no-store',
  });
  if (!response.ok) {
    return null;
  }
  return (await response.json()) as Run;
}

/**
 * Poll active runs and merge updates into the provided initial list.
 */
export function useRunUpdates(initialRuns: Run[]): Run[] {
  const [runs, setRuns] = useState<Run[]>(initialRuns);
  const runsRef = useRef<Run[]>(initialRuns);

  useEffect(() => {
    setRuns(initialRuns);
    runsRef.current = initialRuns;
  }, [initialRuns]);

  useEffect(() => {
    let timeoutId: ReturnType<typeof setTimeout> | undefined;
    let cancelled = false;

    async function pollActiveRuns() {
      const activeRuns = runsRef.current.filter((run) => ACTIVE_STATUSES.has(run.status));
      if (cancelled || activeRuns.length === 0) {
        return;
      }

      try {
        const refreshedRuns = await Promise.all(activeRuns.map((run) => fetchRun(run.id)));
        if (!cancelled) {
          setRuns((previousRuns) => {
            const updates = new Map(
              refreshedRuns.filter((run): run is Run => run !== null).map((run) => [run.id, run])
            );
            const nextRuns = previousRuns.map((run) => updates.get(run.id) ?? run);
            runsRef.current = nextRuns;
            return nextRuns;
          });
        }
      } catch {
        // Ignore transient polling failures.
      } finally {
        if (!cancelled) {
          timeoutId = setTimeout(() => {
            void pollActiveRuns();
          }, POLL_INTERVAL_MS);
        }
      }
    }

    if (runsRef.current.some((run) => ACTIVE_STATUSES.has(run.status))) {
      timeoutId = setTimeout(() => {
        void pollActiveRuns();
      }, POLL_INTERVAL_MS);
    }

    return () => {
      cancelled = true;
      if (timeoutId) {
        clearTimeout(timeoutId);
      }
    };
  }, [initialRuns]);

  return runs;
}

/**
 * Poll updates for a single active run.
 */
export function useSingleRunUpdates(initialRun: Run): Run {
  const [run, setRun] = useState<Run>(initialRun);
  const runRef = useRef<Run>(initialRun);

  useEffect(() => {
    setRun(initialRun);
    runRef.current = initialRun;
  }, [initialRun]);

  useEffect(() => {
    let timeoutId: ReturnType<typeof setTimeout> | undefined;
    let cancelled = false;

    async function pollRun() {
      if (cancelled || !ACTIVE_STATUSES.has(runRef.current.status)) {
        return;
      }

      try {
        const refreshedRun = await fetchRun(initialRun.id);
        if (refreshedRun && !cancelled) {
          runRef.current = refreshedRun;
          setRun(refreshedRun);
        }
      } catch {
        // Ignore transient polling failures.
      } finally {
        if (!cancelled && ACTIVE_STATUSES.has(runRef.current.status)) {
          timeoutId = setTimeout(() => {
            void pollRun();
          }, POLL_INTERVAL_MS);
        }
      }
    }

    if (ACTIVE_STATUSES.has(runRef.current.status)) {
      timeoutId = setTimeout(() => {
        void pollRun();
      }, POLL_INTERVAL_MS);
    }

    return () => {
      cancelled = true;
      if (timeoutId) {
        clearTimeout(timeoutId);
      }
    };
  }, [initialRun.id, initialRun.status]);

  return run;
}
