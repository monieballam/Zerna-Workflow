import { describe, expect, it } from 'vitest';
import {
  METHOD_INFO,
  RUN_FORM_ADVANCED_GROUPS,
  RUN_FORM_MAIN_SECTIONS,
  filterMethodsForLaunchPreview,
} from '@/lib/pipeline-parameter-presentation';

describe('ambient RNA correction presentation', () => {
  it('is not listed in any main run form section', () => {
    for (const section of RUN_FORM_MAIN_SECTIONS) {
      expect(section.fields.some((f) => f.startsWith('ambient_'))).toBe(false);
    }
  });

  it('appears only in the dedicated advanced preprocessing group', () => {
    const ambientGroup = RUN_FORM_ADVANCED_GROUPS.find(
      (g) => g.id === 'ambient_preprocessing_advanced'
    );
    expect(ambientGroup?.fields).toEqual(['ambient_correction', 'ambient_method']);
    expect(ambientGroup?.description).toMatch(/Usually not needed/i);
    const featureAdv = RUN_FORM_ADVANCED_GROUPS.find((g) => g.id === 'feature_advanced');
    expect(featureAdv?.fields).toEqual([
      'n_top_genes',
      'hvg_flavor',
      'hvg_batch_key',
      'target_sum',
      'n_pcs',
    ]);
    expect(featureAdv?.title).toMatch(/hvg|normalization|pca/i);
    expect(featureAdv?.fields.some((f) => f.startsWith('ambient_'))).toBe(false);
  });

  it('launch catalog copy names the HVG step HVG Selection', () => {
    expect(METHOD_INFO.select_hvg.label).toBe('HVG Selection');
  });

  it('filterMethodsForLaunchPreview drops ambient when the flag is off', () => {
    const methods = [
      'qc_filter',
      { name: 'ambient_correction', enabled_if: 'ambient_correction' },
      'normalize',
    ] as const;
    const off = filterMethodsForLaunchPreview([...methods], { ambient_correction: false });
    expect(off.map((m) => (typeof m === 'string' ? m : m.name))).toEqual([
      'qc_filter',
      'normalize',
    ]);
    const on = filterMethodsForLaunchPreview([...methods], { ambient_correction: true });
    expect(on).toHaveLength(3);
  });
});
