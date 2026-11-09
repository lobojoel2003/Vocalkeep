import { describe, expect, it } from 'vitest';
import { crossedMilestone, MILESTONE_TEXT, milestoneTitle, progressLine } from './milestones';
import type { Milestone, Progress } from './types';

const ALL: Milestone[] = [
  { id: 'first-words', at: 10 },
  { id: 'preview', at: 100 },
  { id: 'recognisable', at: 300 },
  { id: 'natural', at: 600 },
  { id: 'rich', at: 1000 },
  { id: 'complete', at: 1500 },
];

function progress(kept: number): Progress {
  return {
    kept,
    good: kept,
    okay: 0,
    needsRedo: 0,
    totalPrompts: 1631,
    speechMinutes: kept / 20,
    phonemesCovered: 0,
    phonemesTotal: 64,
    diphonesCovered: 0,
    diphonesTotal: 2000,
    milestone: [...ALL].reverse().find((m) => kept >= m.at) ?? null,
    nextMilestone: ALL.find((m) => kept < m.at) ?? null,
    toNext: 0,
    recommended: 600,
    sets: [],
    sessions: 0,
    daysRecorded: 0,
    lastSessionAt: null,
    legacyMessages: 0,
    legacyMinutes: 0,
    recentDays: [],
  };
}

describe('milestones', () => {
  it('has words for every milestone id', () => {
    for (const m of ALL) expect(MILESTONE_TEXT[m.id]?.title).toBeTruthy();
    expect(milestoneTitle(null)).toBe('Just beginning');
  });

  it('describes what is next', () => {
    expect(progressLine(progress(0))).toMatch(/first sentence/);
    expect(progressLine(progress(299))).toBe('1 more sentence to “Recognisably you”.');
    expect(progressLine(progress(412))).toBe('188 more sentences to “Natural”.');
    expect(progressLine(progress(1600))).toMatch(/Thank you/);
  });

  it('celebrates the highest milestone crossed in a session', () => {
    expect(crossedMilestone(95, 120, ALL)?.id).toBe('preview');
    expect(crossedMilestone(5, 320, ALL)?.id).toBe('recognisable');
    expect(crossedMilestone(120, 130, ALL)).toBeNull();
  });
});
