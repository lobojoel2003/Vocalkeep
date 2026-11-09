import { describe, expect, it } from 'vitest';
import { normaliseBases } from './api';
import { commercialText, pickDefaultBase, sameLanguage, sortBases, stageText } from './voice';
import type { BaseVoice } from './types';

const base = (over: Partial<BaseVoice>): BaseVoice => ({
  id: 'x',
  name: 'X',
  language: 'en-US',
  quality: 'medium',
  dataset: '',
  license: '',
  commercial: 'unknown',
  lineage: '',
  recommended: false,
  notes: '',
  ...over,
});

describe('voice helpers', () => {
  it('explains licences plainly', () => {
    expect(commercialText('yes').label).toBe('Free for any use');
    expect(commercialText('no').tone).toBe('redo');
    expect(commercialText('unknown').label).toBe('Licence unclear');
  });

  it('prefers recommended, permissive voices in the right language', () => {
    const bases = [
      base({ id: 'gb', language: 'en-GB', recommended: true, commercial: 'yes', name: 'Cori' }),
      base({ id: 'lessac', commercial: 'no', name: 'Lessac' }),
      base({ id: 'lj', recommended: true, commercial: 'yes', name: 'LJ' }),
    ];
    expect(sortBases(bases, 'en-US').map((b) => b.id)).toEqual(['lj', 'lessac', 'gb']);
    expect(pickDefaultBase(bases, 'en-GB')).toBe('gb');
    expect(pickDefaultBase([], 'en-US')).toBe('');
    expect(sameLanguage('en_US', 'en-us')).toBe(true);
  });

  it('accepts the registry in either shape', () => {
    const raw = [{ id: 'a', name: 'A', commercial: 'no', recommended: true, dataset_license: 'X' }];
    expect(normaliseBases(raw)[0]).toMatchObject({
      id: 'a',
      commercial: 'no',
      recommended: true,
      license: 'X',
    });
    expect(normaliseBases({ bases: raw })).toHaveLength(1);
    expect(normaliseBases({ bases: [{ commercial: 'maybe' }] })).toEqual([]);
    expect(normaliseBases([{ id: 'b', commercial: 'maybe' }])[0]!.commercial).toBe('unknown');
    expect(normaliseBases(null)).toEqual([]);
    expect(normaliseBases([{ id: 'vctk', canFineTune: false }])).toEqual([]);
  });

  it('names build stages', () => {
    expect(stageText('train')).toMatch(/sound like you/);
    expect(stageText('custom')).toBe('Custom');
    expect(stageText('')).toBe('Starting');
  });
});
