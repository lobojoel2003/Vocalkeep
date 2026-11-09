import { describe, expect, it } from 'vitest';
import { ISSUE_TEXT, levelZone, meterFraction, topIssues, VERDICT_TEXT } from './feedback';
import type { Analysis, IssueCode } from './types';

const ALL_CODES: IssueCode[] = [
  'no-speech',
  'too-short',
  'clipping',
  'near-clipping',
  'too-quiet',
  'too-loud',
  'noisy',
  'low-snr',
  'cut-off-start',
  'cut-off-end',
  'long-pause',
  'too-fast',
  'too-slow',
  'dc-offset',
];

function analysis(issues: Analysis['issues']): Analysis {
  return {
    verdict: issues.some((i) => i.severity === 'redo') ? 'redo' : issues.length ? 'okay' : 'good',
    issues,
    sampleRate: 48000,
    durationMs: 3000,
    peakDbfs: -6,
    speechDbfs: -20,
    noiseFloorDbfs: -65,
    snrDb: 45,
    clippedSamples: 0,
    clipRuns: 0,
    dcOffset: 0,
    speechStartMs: 400,
    speechEndMs: 2600,
    speechMs: 2200,
    longestPauseMs: 200,
  };
}

describe('feedback', () => {
  it('has kind words for every issue the Rust checker reports', () => {
    for (const code of ALL_CODES) {
      expect(ISSUE_TEXT[code].title.length).toBeGreaterThan(3);
      expect(ISSUE_TEXT[code].tip).toMatch(/[.!?]$/);
    }
    expect(Object.keys(ISSUE_TEXT).sort()).toEqual([...ALL_CODES].sort());
  });

  it('never blames the person', () => {
    const words = Object.values(ISSUE_TEXT)
      .flatMap((t) => [t.title, t.tip])
      .concat(Object.values(VERDICT_TEXT).flatMap((v) => [v.title, v.body]))
      .join(' ')
      .toLowerCase();
    for (const harsh of ['wrong', 'bad', 'error', 'failed', 'mistake', 'you should']) {
      expect(words).not.toContain(harsh);
    }
  });

  it('puts problems before small notes', () => {
    const notes = topIssues(
      analysis([
        { code: 'cut-off-start', severity: 'warn' },
        { code: 'clipping', severity: 'redo' },
        { code: 'long-pause', severity: 'warn' },
      ]),
    );
    expect(notes).toHaveLength(2);
    expect(notes[0]).toBe(ISSUE_TEXT.clipping);
  });

  it('maps levels onto the meter', () => {
    expect(meterFraction(-60)).toBe(0);
    expect(meterFraction(0)).toBe(1);
    expect(meterFraction(-30)).toBeCloseTo(0.5);
    expect(meterFraction(-Infinity)).toBe(0);
    expect(levelZone(-50, false)).toBe('quiet');
    expect(levelZone(-20, false)).toBe('good');
    expect(levelZone(-20, true)).toBe('loud');
  });
});
