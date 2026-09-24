import { describe, expect, it } from 'vitest';
import {
  METHOD_INFO,
  PARAM_FIELD_HELP,
  PARAMETER_SECTIONS,
  RUN_FORM_ADVANCED_GROUPS,
  RUN_FORM_MAIN_SECTIONS,
  buildLrCommunicationGroupingSelectOptions,
  getParameterLabel,
  isFieldVisible,
  shouldOfferLineageSubclusterLrGrouping,
} from './pipeline-parameter-presentation';

describe('pipeline-parameter-presentation (annotation defaults copy)', () => {
  it('annotate step summary presents CellTypist as the dashboard default path', () => {
    expect(METHOD_INFO.annotate.description).toMatch(/CellTypist/i);
    expect(METHOD_INFO.annotate.description).toMatch(/Advanced settings/i);
    expect(METHOD_INFO.annotate.description).not.toMatch(/\bTissue\b/i);
  });

  it('annotation_method help documents default vs conservative fallback', () => {
    expect(PARAM_FIELD_HELP.annotation_method).toMatch(/CellTypist/i);
    expect(PARAM_FIELD_HELP.annotation_method).toMatch(/conservative/i);
  });

  it('exposes only cancer type and species on the main annotation form section', () => {
    const main = RUN_FORM_MAIN_SECTIONS.find((s) => s.id === 'annotation_context_main');
    expect(main?.fields).toEqual(['annotation_cancer_type', 'annotation_species']);
  });

  it('keeps engine and tuning fields under annotation advanced settings', () => {
    const adv = RUN_FORM_ADVANCED_GROUPS.find((g) => g.id === 'annotation_advanced');
    expect(adv?.fields).toContain('annotation_method');
    expect(adv?.fields).toContain('annotation_cluster_key');
    expect(adv?.fields).toContain('annotation_benchmark_reference_key');
    expect(adv?.fields).not.toContain('annotation_tissue_context');
  });

  it('orders PARAMETER_SECTIONS annotation fields with primary controls before legacy tissue', () => {
    const ann = PARAMETER_SECTIONS.find((s) => s.id === 'annotation');
    expect(ann?.fields).toEqual([
      'annotation_cancer_type',
      'annotation_species',
      'annotation_tissue_context',
    ]);
  });
});

describe('pipeline-parameter-presentation (clustering UI)', () => {
  it('surfaces resolution on the main run form; keeps k and algorithm in advanced', () => {
    const clusterMain = RUN_FORM_MAIN_SECTIONS.find((s) => s.id === 'cluster_main');
    expect(clusterMain?.fields).toEqual(['resolution']);
    const adv = RUN_FORM_ADVANCED_GROUPS.find((g) => g.id === 'cluster_embed_advanced');
    expect(adv?.fields).toContain('clustering_method');
    expect(adv?.fields).toContain('n_neighbors');
    expect(adv?.fields).not.toContain('resolution');
  });
});

describe('pipeline-parameter-presentation (batch integration UI)', () => {
  it('orders batch advanced as batch_key then integration and scVI tuning', () => {
    const batchAdv = RUN_FORM_ADVANCED_GROUPS.find((g) => g.id === 'batch_advanced');
    expect(batchAdv?.fields).toEqual(['batch_key', 'integration_mode', 'n_latent', 'max_epochs']);
  });

  it('does not place batch_method in batch advanced group (canonical selector is integration_mode)', () => {
    const batchAdv = RUN_FORM_ADVANCED_GROUPS.find((g) => g.id === 'batch_advanced');
    expect(batchAdv?.fields).toBeDefined();
    expect(batchAdv!.fields).toContain('integration_mode');
    expect(batchAdv!.fields).not.toContain('batch_method');
  });

  it('hides legacy batch_method from conditional visibility', () => {
    expect(isFieldVisible('batch_method', { batch_correction: true })).toBe(false);
  });

  it('shows batch_key only when batch correction is enabled', () => {
    expect(isFieldVisible('batch_key', { batch_correction: false })).toBe(false);
    expect(isFieldVisible('batch_key', { batch_correction: true })).toBe(true);
  });

  it('shows scVI-only tuning when integration_mode is scvi (or legacy batch_method only)', () => {
    expect(
      isFieldVisible('n_latent', { batch_correction: true, integration_mode: 'harmony' })
    ).toBe(false);
    expect(isFieldVisible('n_latent', { batch_correction: true, integration_mode: 'scvi' })).toBe(
      true
    );
    expect(
      isFieldVisible('n_latent', {
        batch_correction: true,
        batch_method: 'scvi',
      })
    ).toBe(true);
  });
});

describe('pipeline-parameter-presentation (ligand–receptor grouping copy)', () => {
  it('documents strict cci_* vs auto vs cluster for lr_communication_grouping', () => {
    expect(PARAM_FIELD_HELP.lr_communication_grouping).toMatch(/cci_celltype_minor/i);
    expect(PARAM_FIELD_HELP.lr_communication_grouping).toMatch(/no silent cluster fallback/i);
    expect(PARAM_FIELD_HELP.lr_communication_grouping).toMatch(/never lineage_subcluster/i);
  });
});

describe('buildLrCommunicationGroupingSelectOptions', () => {
  it('hides lineage_subcluster unless allowed and omits it from the ordered list otherwise', () => {
    const full = ['auto', 'cci_major', 'cci_minor', 'cci_fine', 'cluster', 'lineage_subcluster'];
    const without = buildLrCommunicationGroupingSelectOptions({
      schemaEnum: full,
      showLineageSubcluster: false,
    });
    expect(without.some((o) => o.value === 'lineage_subcluster')).toBe(false);
    const withLineage = buildLrCommunicationGroupingSelectOptions({
      schemaEnum: full,
      showLineageSubcluster: true,
    });
    expect(withLineage.some((o) => o.value === 'lineage_subcluster')).toBe(true);
    expect(withLineage.find((o) => o.value === 'lineage_subcluster')?.label).toMatch(
      /exploratory|advanced/i
    );
  });

  it('shouldOfferLineageSubclusterLrGrouping is true with annotate on path or dataset column', () => {
    expect(
      shouldOfferLineageSubclusterLrGrouping({
        datasetObsColumns: ['orig.ident'],
        launchPreviewMethodNames: ['qc_filter', 'annotate'],
      })
    ).toBe(true);
    expect(
      shouldOfferLineageSubclusterLrGrouping({
        datasetObsColumns: ['orig.ident', 'lineage_subcluster'],
        launchPreviewMethodNames: ['cluster'],
      })
    ).toBe(true);
    expect(
      shouldOfferLineageSubclusterLrGrouping({
        datasetObsColumns: ['orig.ident'],
        launchPreviewMethodNames: ['cluster'],
      })
    ).toBe(false);
  });
});

describe('pipeline-parameter-presentation (pathway activity scoring copy)', () => {
  it('frames pathway_scoring as per-cell activity scoring, not enrichment', () => {
    expect(METHOD_INFO.pathway_scoring.label).toMatch(/Pathway Activity Scoring/i);
    expect(METHOD_INFO.pathway_scoring.description).toMatch(/per-cell/i);
    expect(METHOD_INFO.pathway_scoring.description).toMatch(/not DE-contrast|enrichment/i);
    expect(getParameterLabel('pathway_scoring')).toMatch(/pathway activity scoring/i);
  });

  it('keeps pathway resource and method on advanced only (main is toggle + LR)', () => {
    const main = RUN_FORM_MAIN_SECTIONS.find((s) => s.id === 'optional_main');
    expect(main?.fields).toEqual(['pathway_scoring', 'ligand_receptor']);
    const adv = RUN_FORM_ADVANCED_GROUPS.find((g) => g.id === 'pathway_lr_advanced');
    expect(adv?.fields).toContain('pathway_database');
    expect(adv?.fields).toContain('pathway_method');
  });
});

describe('pipeline-parameter-presentation (HVG Selection)', () => {
  it('labels the select_hvg step HVG Selection with non-subsetting copy', () => {
    expect(METHOD_INFO.select_hvg.label).toBe('HVG Selection');
    expect(METHOD_INFO.select_hvg.description).toMatch(/marks HVGs/i);
    expect(METHOD_INFO.select_hvg.description).toMatch(/does not subset/i);
  });

  it('documents HVG batch key visibility when batch correction is on or a batch column is set', () => {
    expect(
      isFieldVisible('hvg_batch_key', { batch_correction: false, doublet_method: 'solo' })
    ).toBe(false);
    expect(isFieldVisible('hvg_batch_key', { batch_correction: true })).toBe(true);
    expect(
      isFieldVisible('hvg_batch_key', {
        batch_correction: false,
        doublet_method: 'doubletdetection',
        batch_key: 'orig.ident',
        hvg_batch_key: '',
      })
    ).toBe(true);
    expect(
      isFieldVisible('hvg_batch_key', {
        batch_correction: false,
        doublet_method: 'doubletdetection',
        batch_key: '',
        hvg_batch_key: '',
      })
    ).toBe(false);
  });
});

describe('pipeline-parameter-presentation (simplified main form)', () => {
  it('keeps core qc thresholds on the main form without qc_species', () => {
    const qc = RUN_FORM_MAIN_SECTIONS.find((s) => s.id === 'qc_main');
    expect(qc?.fields).toEqual(['min_genes', 'max_genes', 'min_cells', 'max_mito_pct']);
    expect(qc?.defaultExpanded).toBe(true);
  });

  it('surfaces only de_mode on the main DE section', () => {
    const de = RUN_FORM_MAIN_SECTIONS.find((s) => s.id === 'de_main');
    expect(de?.fields).toEqual(['de_mode']);
    expect(de?.defaultExpanded).toBe(false);
  });

  it('shows doublet_sample_key only for scrublet', () => {
    expect(isFieldVisible('doublet_sample_key', { doublet_method: 'scrublet' })).toBe(true);
    expect(isFieldVisible('doublet_sample_key', { doublet_method: 'solo' })).toBe(false);
  });

  it('hides marker DE fields for pseudobulk modes', () => {
    expect(isFieldVisible('de_method', { de_mode: 'pseudobulk_sample_level_contrast' })).toBe(
      false
    );
    expect(isFieldVisible('de_n_genes', { de_mode: 'condition_de_within_celltype' })).toBe(false);
    expect(isFieldVisible('de_method', { de_mode: 'marker_ranking' })).toBe(true);
  });

  it('hides de_padj_method for marker ranking', () => {
    expect(isFieldVisible('de_padj_method', { de_mode: 'marker_ranking' })).toBe(false);
    expect(isFieldVisible('de_padj_method', { de_mode: 'pseudobulk_sample_level_contrast' })).toBe(
      true
    );
  });
});
