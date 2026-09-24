import { describe, expect, it } from 'vitest';
import {
  DOUBLET_PROGRAMMATIC_ONLY_FIELDS,
  PARAMETER_SECTIONS,
  RUN_FORM_ADVANCED_GROUPS,
  RUN_FORM_MAIN_SECTIONS,
  getRunFormManagedFieldNames,
} from '@/lib/pipeline-parameter-presentation';

describe('doublet parameter presentation', () => {
  it('exposes only doublet_method on the main doublet section', () => {
    const main = RUN_FORM_MAIN_SECTIONS.find((s) => s.id === 'doublets_main');
    expect(main?.fields).toEqual(['doublet_method']);
  });

  it('keeps fine-tuning and legacy doublet fields out of the main section', () => {
    const main = RUN_FORM_MAIN_SECTIONS.find((s) => s.id === 'doublets_main');
    for (const f of DOUBLET_PROGRAMMATIC_ONLY_FIELDS) {
      expect(main?.fields.includes(f)).toBe(false);
    }
  });

  it('places doublet tuning and legacy backend knobs in advanced (not on main)', () => {
    const adv = RUN_FORM_ADVANCED_GROUPS.find((g) => g.id === 'doublet_advanced');
    expect(adv?.fields).toContain('expected_doublet_rate');
    expect(adv?.fields).toContain('doublet_mode');
    expect(adv?.fields).toContain('doublet_sample_key');
    expect(adv?.fields).toContain('doublet_threshold');
    expect(adv?.fields).toContain('solo_batch_size');
    expect(adv?.fields).not.toContain('doublet_method');
  });

  it('treats legacy-only doublet fields as managed so they are not “additional parameters”', () => {
    const managed = new Set(getRunFormManagedFieldNames());
    for (const f of DOUBLET_PROGRAMMATIC_ONLY_FIELDS) {
      expect(managed.has(f)).toBe(true);
    }
  });

  it('PARAMETER_SECTIONS doublet group lists primary controls before fine-tuning', () => {
    const sec = PARAMETER_SECTIONS.find((s) => s.id === 'doublets');
    expect(sec?.fields[0]).toBe('doublet_method');
    expect(sec?.fields).toContain('doublet_mode');
    expect(sec?.fields).not.toContain('batch_key');
  });
});
