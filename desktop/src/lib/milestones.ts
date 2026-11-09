// Words for each milestone on the way to a full voice (thresholds come from the Rust side).

import type { Milestone, Progress } from './types';

export const MILESTONE_TEXT: Record<string, { title: string; body: string }> = {
  'first-words': {
    title: 'First words',
    body: "You've started. Your microphone and room are working.",
  },
  preview: {
    title: 'A first sketch',
    body: 'Enough to build a rough preview and hear the idea.',
  },
  recognisable: {
    title: 'Recognisably you',
    body: 'A preview starts to sound like you.',
  },
  natural: {
    title: 'Natural',
    body: 'Enough for an everyday voice. This is the point we suggest building.',
  },
  rich: {
    title: 'Rich and expressive',
    body: 'More sounds and rhythms make a smoother, more expressive voice.',
  },
  complete: {
    title: 'Complete',
    body: 'Every built-in sentence set is nearly done. Your voice is well kept.',
  },
};

export function milestoneTitle(m: Milestone | null): string {
  return m ? (MILESTONE_TEXT[m.id]?.title ?? m.id) : 'Just beginning';
}

/** One sentence about where the bank stands, for the Today view. */
export function progressLine(p: Progress): string {
  if (p.kept === 0) return 'Your first sentence is the hardest. The rest are gentler.';
  if (!p.nextMilestone) return 'Every built-in sentence is recorded. Thank you.';
  const left = p.nextMilestone.at - p.kept;
  const next = milestoneTitle(p.nextMilestone);
  return `${left.toLocaleString('en')} more ${left === 1 ? 'sentence' : 'sentences'} to “${next}”.`;
}

/** Whether a newly reached milestone should be celebrated after a session. */
export function crossedMilestone(
  before: number,
  after: number,
  all: Milestone[],
): Milestone | null {
  return [...all].reverse().find((m) => before < m.at && after >= m.at) ?? null;
}
