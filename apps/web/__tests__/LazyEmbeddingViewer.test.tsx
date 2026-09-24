import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import React from 'react';
import LazyEmbeddingViewer from '@/components/embedding/LazyEmbeddingViewer';
import type { Embedding, CellMetadata } from '@/lib/embedding-types';

// ---------------------------------------------------------------------------
// Mock IntersectionObserver
// ---------------------------------------------------------------------------

let observerCallback: IntersectionObserverCallback;
let observerInstance: { observe: ReturnType<typeof vi.fn>; disconnect: ReturnType<typeof vi.fn> };

beforeEach(() => {
  observerInstance = { observe: vi.fn(), disconnect: vi.fn() };

  vi.stubGlobal(
    'IntersectionObserver',
    vi.fn((cb: IntersectionObserverCallback) => {
      observerCallback = cb;
      return observerInstance;
    })
  );
});

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const embedding: Embedding = {
  cells: [
    { id: 'c1', x: 0, y: 0 },
    { id: 'c2', x: 1, y: 1 },
  ],
  bounds: { minX: 0, maxX: 1, minY: 0, maxY: 1 },
};

const metadata: CellMetadata[] = [
  { cellId: 'c1', cluster: 'A' },
  { cellId: 'c2', cluster: 'B' },
];

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('LazyEmbeddingViewer', () => {
  it('renders a placeholder when not visible', () => {
    render(
      <LazyEmbeddingViewer
        embedding={embedding}
        metadata={metadata}
        availableFields={['cluster']}
      />
    );

    expect(screen.getByTestId('lazy-embedding-placeholder')).toBeInTheDocument();
  });

  it('observes the container element', () => {
    render(
      <LazyEmbeddingViewer
        embedding={embedding}
        metadata={metadata}
        availableFields={['cluster']}
      />
    );

    expect(observerInstance.observe).toHaveBeenCalledTimes(1);
  });

  it('loads the viewer when it becomes visible', async () => {
    render(
      <LazyEmbeddingViewer
        embedding={embedding}
        metadata={metadata}
        availableFields={['cluster']}
      />
    );

    // Simulate intersection
    await act(async () => {
      observerCallback(
        [{ isIntersecting: true } as IntersectionObserverEntry],
        {} as IntersectionObserver
      );
      // Allow dynamic import to resolve
      await new Promise((r) => setTimeout(r, 50));
    });

    // The wrapper div should still be present
    expect(screen.getByTestId('lazy-embedding-viewer')).toBeInTheDocument();
  });

  it('disconnects observer on unmount', () => {
    const { unmount } = render(
      <LazyEmbeddingViewer
        embedding={embedding}
        metadata={metadata}
        availableFields={['cluster']}
      />
    );

    unmount();
    expect(observerInstance.disconnect).toHaveBeenCalled();
  });
});
