'use client';

import { useEffect, useRef, useState } from 'react';
import React from 'react';
import type { Embedding, CellMetadata } from '@/lib/embedding-types';
import type { EmbeddingRenderer } from '@/lib/embedding-renderer';

interface LazyEmbeddingViewerProps {
  embedding: Embedding;
  metadata: CellMetadata[];
  availableFields: string[];
  continuousFields?: string[];
  fieldRanges?: Record<string, { min: number; max: number }>;
  rendererRef?: React.RefObject<EmbeddingRenderer | null>;
  activeColorField?: string;
  onActiveColorFieldChange?: (field: string) => void;
  /** When true, load the WebGL viewer immediately (skip intersection / dynamic import gate). */
  eager?: boolean;
  /** User-facing labels for categorical color-by legend (e.g. cluster aliases). */
  formatCategoryLegendLabel?: (field: string, rawValue: string) => string;
  formatCentroidLabel?: (field: string, rawValue: string) => string;
  /** User-facing values in the selected-cell metadata sidebar. */
  formatMetadataDisplayValue?: (field: string, rawValue: string) => string;
  labelMode?: 'none' | 'cluster' | 'cellType';
  onLabelModeChange?: (mode: 'none' | 'cluster' | 'cellType') => void;
  hideInternalLegend?: boolean;
  focusCategory?: { field: string; rawValue: string } | null;
  legendHoverRaw?: string | null;
  compactToolbar?: boolean;
}

/**
 * Lazy-loading wrapper for EmbeddingViewer.
 * Uses IntersectionObserver only to defer the initial WebGL load until the
 * block is near the viewport. After the first intersection, the real viewer
 * stays mounted so scrolling to content below (e.g. cluster summaries) does
 * not collapse layout and break page scroll.
 */
export default function LazyEmbeddingViewer(props: LazyEmbeddingViewerProps) {
  const { eager = false, ...viewerProps } = props;
  const containerRef = useRef<HTMLDivElement>(null);
  /** Once the explorer embedding has been in view, keep the real viewer mounted (do not swap back to the placeholder when the user scrolls down to cluster summaries). Toggling on viewport exit shrinks layout (~600px → ~400px) and fights the scroll position, making the page feel like it never reaches the bottom. */
  const [shouldLoadViewer, setShouldLoadViewer] = useState(!!eager);
  const [EmbeddingViewerComponent, setEmbeddingViewerComponent] =
    useState<React.ComponentType<LazyEmbeddingViewerProps> | null>(null);

  // One-way activation: first time the block intersects (or is near) the visible area, load WebGL viewer and keep it.
  // Dashboard layout scrolls `<main class="overflow-y-auto">`, not the document. IntersectionObserver's default root is
  // the viewport, which often never "sees" descendants of an internal scroll container — so we observe against `main`
  // when present, plus a synchronous visibility check after layout.
  useEffect(() => {
    const el = containerRef.current;
    if (!el || shouldLoadViewer) return;
    const host = el;

    const scrollRoot = host.closest('main');

    function visibleInScrollRoot(): boolean {
      const er = host.getBoundingClientRect();
      if (!scrollRoot) {
        return er.bottom > 0 && er.top < window.innerHeight;
      }
      const rr = scrollRoot.getBoundingClientRect();
      return er.bottom > rr.top && er.top < rr.bottom;
    }

    const tryActivate = () => {
      if (visibleInScrollRoot()) setShouldLoadViewer(true);
    };

    tryActivate();
    const raf = requestAnimationFrame(() => tryActivate());

    if (typeof IntersectionObserver === 'undefined') {
      return () => cancelAnimationFrame(raf);
    }

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setShouldLoadViewer(true);
        }
      },
      {
        root: scrollRoot,
        rootMargin: '400px',
        threshold: 0,
      }
    );

    observer.observe(host);
    return () => {
      cancelAnimationFrame(raf);
      observer.disconnect();
    };
  }, [shouldLoadViewer]);

  useEffect(() => {
    if (eager) setShouldLoadViewer(true);
  }, [eager]);

  // Dynamically import the real EmbeddingViewer once we decide to load
  useEffect(() => {
    if (!shouldLoadViewer || EmbeddingViewerComponent) return;

    let cancelled = false;
    void import('@/components/embedding/EmbeddingViewer')
      .then((mod) => {
        if (!cancelled) {
          setEmbeddingViewerComponent(() => mod.default);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setEmbeddingViewerComponent(null);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [shouldLoadViewer, EmbeddingViewerComponent]);

  return (
    <div ref={containerRef} className="min-h-[400px]" data-testid="lazy-embedding-viewer">
      {shouldLoadViewer && EmbeddingViewerComponent ? (
        <EmbeddingViewerComponent {...viewerProps} />
      ) : (
        <div
          className="flex items-center justify-center bg-gray-50 rounded border border-gray-200 animate-pulse"
          style={{ minHeight: 400 }}
          data-testid="lazy-embedding-placeholder"
        >
          <span className="text-sm text-gray-400">
            Embedding viewer will load when scrolled into view
          </span>
        </div>
      )}
    </div>
  );
}
