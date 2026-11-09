// Types shared with the Rust side (camelCase JSON).

export type Theme = 'system' | 'light' | 'dark' | 'contrast';
export type TextSize = 'normal' | 'large' | 'larger' | 'largest';
export type Energy = 'strong' | 'okay' | 'tired';
export type Verdict = 'good' | 'okay' | 'redo';
export type Severity = 'warn' | 'redo';
export type IssueCode =
  | 'no-speech'
  | 'too-short'
  | 'clipping'
  | 'near-clipping'
  | 'too-quiet'
  | 'too-loud'
  | 'noisy'
  | 'low-snr'
  | 'cut-off-start'
  | 'cut-off-end'
  | 'long-pause'
  | 'too-fast'
  | 'too-slow'
  | 'dc-offset';
export type RoomLevel = 'quiet' | 'fine' | 'noisy' | 'too-noisy';
export type RecordingKind = 'take' | 'legacy';

export interface BuildInfo {
  version: string;
  buildNumber: string;
  gitSha: string;
  buildDate: string;
}

export interface AppInfo extends BuildInfo {
  platform: string;
  dataDir: string;
  bankDir: string;
  voicesDir: string;
}

export interface SessionLength {
  minutes: number;
  prompts: number;
}

export interface Settings {
  theme: Theme;
  textSize: TextSize;
  reduceMotion: boolean;
  inputDevice: string | null;
  sessions: Record<Energy, SessionLength>;
  breakEvery: number;
  autoPlay: boolean;
  autoKeepGood: boolean;
  enabledSets: string[];
  bankDir: string | null;
  pipelineCommand: string | null;
  onboarded: boolean;
}

export interface Speaker {
  name: string;
  language: string;
  gender?: string | null;
}

export interface Issue {
  code: IssueCode;
  severity: Severity;
}

export interface Analysis {
  verdict: Verdict;
  issues: Issue[];
  sampleRate: number;
  durationMs: number;
  peakDbfs: number;
  speechDbfs: number;
  noiseFloorDbfs: number;
  snrDb: number;
  clippedSamples: number;
  clipRuns: number;
  dcOffset: number;
  speechStartMs: number | null;
  speechEndMs: number | null;
  speechMs: number;
  longestPauseMs: number;
}

export interface RoomCheck {
  level: RoomLevel;
  noiseFloorDbfs: number;
  peakDbfs: number;
  sampleRate: number;
  checkedAt: string;
}

export interface Milestone {
  id: string;
  at: number;
}

export interface SetProgress {
  id: string;
  title: string;
  recorded: number;
  total: number;
}

export interface DayCount {
  date: string;
  kept: number;
}

export interface Progress {
  kept: number;
  good: number;
  okay: number;
  needsRedo: number;
  totalPrompts: number;
  speechMinutes: number;
  phonemesCovered: number;
  phonemesTotal: number;
  diphonesCovered: number;
  diphonesTotal: number;
  milestone: Milestone | null;
  nextMilestone: Milestone | null;
  toNext: number;
  recommended: number;
  sets: SetProgress[];
  sessions: number;
  daysRecorded: number;
  lastSessionAt: string | null;
  legacyMessages: number;
  legacyMinutes: number;
  recentDays: DayCount[];
}

export interface PromptSetInfo {
  id: string;
  language: string;
  title: string;
  description: string;
  license: string;
  source: string;
  attribution: string | null;
  count: number;
  weight: number;
}

export interface BankSummary {
  id: string;
  speaker: Speaker;
  room: RoomCheck | null;
  createdAt: string;
  path: string;
}

export interface Overview {
  bank: BankSummary | null;
  progress: Progress | null;
  sets: PromptSetInfo[];
  milestones: Milestone[];
}

export interface InputDevice {
  id: string;
  name: string;
  isDefault: boolean;
}

export interface Level {
  rmsDbfs: number;
  peakDbfs: number;
  clipping: boolean;
  elapsedMs: number;
  limitReached: boolean;
}

export interface QueuedPrompt {
  id: string;
  setId: string;
  text: string;
}

export interface SessionStart {
  sessionId: string;
  energy: Energy;
  length: SessionLength;
  breakEvery: number;
  prompts: QueuedPrompt[];
}

export interface SessionEnd {
  kept: number;
  retried: number;
  speechMinutes: number;
  progress: Progress;
}

export interface PendingTake {
  token: string;
  analysis: Analysis;
  durationMs: number;
}

export interface TakeSummary {
  promptId: string;
  setId: string;
  text: string;
  verdict: Verdict;
  issues: IssueCode[];
  recordedAt: string;
  durationMs: number;
  attempts: number;
}

export interface KeepResult {
  take: TakeSummary;
  progress: Progress;
}

export interface CustomPrompt {
  id: string;
  text: string;
  createdAt: string;
  recorded: boolean;
}

export interface LegacyDetails {
  title: string;
  recipient: string;
  occasion: string;
  recordedBy: string;
  note: string;
}

export interface LegacyMessage extends LegacyDetails {
  id: string;
  file: string;
  sampleRate: number;
  durationMs: number;
  recordedAt: string;
  quality?: Analysis | null;
}

export interface ExportSummary {
  path: string;
  files: number;
  bytes: number;
}

export interface PipelineStatus {
  found: boolean;
  command: string | null;
  version: string | null;
  doctor: Record<string, unknown> | null;
  error: string | null;
}

export type Commercial = 'yes' | 'no' | 'conditions' | 'unknown';

/** A base voice to fine-tune from, with its licence (from `vocalkeep bases --json`). */
export interface BaseVoice {
  id: string;
  name: string;
  language: string;
  quality: string;
  dataset: string;
  license: string;
  commercial: Commercial;
  lineage: string;
  recommended: boolean;
  notes: string;
}

export interface VoiceInfo {
  id: string;
  name: string;
  language: string;
  gender: string | null;
  sampleRate: number;
  base: { id: string; license: string; commercial: string; lineage: string };
  bank: { id: string; takes: number; minutes: number };
  createdAt: string;
  vocalkeepVersion: string;
  path: string;
  sizeBytes: number;
  modelCard: string | null;
}

/** Progress events from `vocalkeep build --progress json`. */
export type PipelineEvent =
  | { event: 'stage'; stage: string; message?: string }
  | { event: 'progress'; stage: string; fraction: number; message?: string }
  | { event: 'log'; message: string }
  | { event: 'done'; voice?: string; message?: string }
  | { event: 'error'; message: string };

export type View = 'today' | 'progress' | 'phrases' | 'messages' | 'voice' | 'settings';
