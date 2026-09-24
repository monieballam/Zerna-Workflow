import { describe, it, expect } from 'vitest';
import { shortenPlotLabel } from './embedding-label-short';

describe('shortenPlotLabel', () => {
  it('takes the last hierarchy segment for pipe-separated labels', () => {
    expect(shortenPlotLabel('Immune | T cells')).toBe('T cells');
    expect(shortenPlotLabel('Stromal | Fibroblasts')).toBe('Fibroblasts');
  });

  it('handles slash-separated paths', () => {
    expect(shortenPlotLabel('Blood / Endothelial / Capillary')).toBe('Capillary');
  });

  it('uses first comma-separated fragment when still long', () => {
    const s = shortenPlotLabel('Very long single string without separators that exceeds');
    expect(s.length).toBeLessThanOrEqual(32);
  });
});
