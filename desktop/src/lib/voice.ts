// Helpers for the My voice page: licences in plain words, base voice order, build stages.

import type { BaseVoice, Commercial } from './types';

export function commercialText(c: Commercial): {
  label: string;
  tone: 'good' | 'okay' | 'redo' | '';
} {
  switch (c) {
    case 'yes':
      return { label: 'Free for any use', tone: 'good' };
    case 'conditions':
      return { label: 'Conditions apply', tone: 'okay' };
    case 'no':
      return { label: 'Personal and research use only', tone: 'redo' };
    default:
      return { label: 'Licence unclear', tone: '' };
  }
}

/** Matches "en-US" with "en_US", "en-us" and so on. */
export function sameLanguage(a: string, b: string): boolean {
  const norm = (s: string) => s.replace('_', '-').toLowerCase();
  return norm(a) === norm(b);
}

/** Recommended voices in the person's language first, then the rest of that language. */
export function sortBases(bases: BaseVoice[], language: string): BaseVoice[] {
  const rank = (b: BaseVoice) =>
    (sameLanguage(b.language, language) ? 0 : 4) +
    (b.recommended ? 0 : 2) +
    (b.commercial === 'yes' ? 0 : 1);
  return [...bases].sort((a, b) => rank(a) - rank(b) || a.name.localeCompare(b.name));
}

export function pickDefaultBase(bases: BaseVoice[], language: string): string {
  return sortBases(bases, language)[0]?.id ?? '';
}

const STAGES: Record<string, string> = {
  prepare: 'Preparing your recordings',
  download: 'Downloading the starting voice',
  train: 'Teaching the voice to sound like you',
  export: 'Saving your voice',
  package: 'Packaging',
  done: 'Done',
};

export function stageText(stage: string): string {
  return STAGES[stage] ?? (stage ? stage[0]!.toUpperCase() + stage.slice(1) : 'Starting');
}
