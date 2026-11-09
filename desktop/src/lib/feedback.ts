// Plain, kind words for what the quality checks found. Each note says what happened and what
// to try, without blame. People using Vocalkeep are often tired; the wording should never be.

import type { Analysis, Energy, IssueCode, RoomLevel, Verdict } from './types';

export interface IssueText {
  /** What happened, in a few words. */
  title: string;
  /** What to try next time. */
  tip: string;
}

export const ISSUE_TEXT: Record<IssueCode, IssueText> = {
  'no-speech': {
    title: "We didn't hear anything",
    tip: 'Check the microphone is the right one and not muted, then try again.',
  },
  'too-short': {
    title: 'That was very short',
    tip: 'Read the whole sentence after you press record.',
  },
  clipping: {
    title: 'A little too loud',
    tip: 'Part of it crackled. Move back a hand-width from the microphone, or turn its level down.',
  },
  'near-clipping': {
    title: 'Close to too loud',
    tip: 'It was fine this time. Moving back a little gives some room to spare.',
  },
  'too-quiet': {
    title: 'A little quiet',
    tip: 'Move a little closer to the microphone, or turn its level up.',
  },
  'too-loud': {
    title: 'Quite loud',
    tip: 'You can speak at your normal, comfortable volume.',
  },
  noisy: {
    title: 'Background noise',
    tip: 'Something in the room is making noise (a fan, a television, traffic). A quieter moment or room will help.',
  },
  'low-snr': {
    title: 'Your voice is close to the background',
    tip: 'Moving closer to the microphone makes your voice stand out from the room.',
  },
  'cut-off-start': {
    title: 'It may have started early',
    tip: 'Wait a moment after pressing record before you speak.',
  },
  'cut-off-end': {
    title: 'The end may be cut off',
    tip: 'Finish the sentence, then press stop.',
  },
  'long-pause': {
    title: 'A long pause',
    tip: "That's fine to keep. If you lost your place, you can try again.",
  },
  'too-fast': {
    title: 'Some words may be missing',
    tip: 'It was shorter than the sentence usually takes. Was the whole sentence read?',
  },
  'too-slow': {
    title: 'Longer than expected',
    tip: 'Read just the sentence on the screen, at a relaxed pace.',
  },
  'dc-offset': {
    title: 'The microphone signal is offset',
    tip: 'Usually harmless. If it keeps happening, try another USB port or microphone.',
  },
};

export const VERDICT_TEXT: Record<Verdict, { title: string; body: string }> = {
  good: { title: "Lovely, that's a keeper", body: 'Clear and clean.' },
  okay: { title: 'Good, and one small note', body: 'This one is fine to keep.' },
  redo: { title: "Let's try that one again", body: 'This take would not help your voice much.' },
};

export function issueText(code: IssueCode): IssueText {
  return ISSUE_TEXT[code] ?? { title: 'Something to check', tip: 'You can try again.' };
}

/** The most useful notes first: problems before small notes, at most `max`. */
export function topIssues(analysis: Analysis, max = 2): IssueText[] {
  return [...analysis.issues]
    .sort((a, b) => (a.severity === b.severity ? 0 : a.severity === 'redo' ? -1 : 1))
    .slice(0, max)
    .map((i) => issueText(i.code));
}

export const ROOM_TEXT: Record<RoomLevel, { title: string; body: string }> = {
  quiet: {
    title: 'Beautifully quiet',
    body: 'This room is perfect for recording.',
  },
  fine: {
    title: 'Quiet enough',
    body: 'This room will work well.',
  },
  noisy: {
    title: 'A bit of background noise',
    body: 'Recordings will work, but a quieter room or moment will make your voice clearer. Fans, fridges and open windows are common causes.',
  },
  'too-noisy': {
    title: 'Quite noisy',
    body: 'It would be worth finding a quieter room, or turning off fans, music or the television, before recording.',
  },
};

export const ENERGY_TEXT: Record<Energy, { title: string; body: string }> = {
  strong: { title: 'Strong', body: 'A good day for a longer session.' },
  okay: { title: 'Okay', body: 'A comfortable, steady session.' },
  tired: { title: 'Tired', body: 'Just a few short sentences. Every one counts.' },
};

/** Meter zone for a live level reading, for the colour of the bar. */
export function levelZone(rmsDbfs: number, clipping: boolean): 'quiet' | 'good' | 'loud' {
  if (clipping || rmsDbfs > -9) return 'loud';
  if (rmsDbfs < -42) return 'quiet';
  return 'good';
}

/** Maps a dBFS level onto 0..1 for a meter (-60 dB is empty, 0 dB is full). */
export function meterFraction(dbfs: number): number {
  if (!Number.isFinite(dbfs)) return 0;
  return Math.min(1, Math.max(0, (dbfs + 60) / 60));
}
