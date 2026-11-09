// Typed wrappers around the Rust commands and events.

import { invoke } from '@tauri-apps/api/core';
import { listen, type UnlistenFn } from '@tauri-apps/api/event';
import type {
  AppInfo,
  BaseVoice,
  CustomPrompt,
  Energy,
  ExportSummary,
  InputDevice,
  KeepResult,
  LegacyDetails,
  LegacyMessage,
  Level,
  Overview,
  PendingTake,
  PipelineEvent,
  PipelineStatus,
  Progress,
  QueuedPrompt,
  RecordingKind,
  RoomCheck,
  SessionEnd,
  SessionStart,
  Settings,
  Speaker,
  TakeSummary,
  VoiceInfo,
} from './types';

/** Audio comes back from Rust as raw bytes. */
async function bytes(cmd: string, args: Record<string, unknown>): Promise<ArrayBuffer> {
  const result = await invoke<ArrayBuffer | number[]>(cmd, args);
  return result instanceof ArrayBuffer ? result : new Uint8Array(result).buffer;
}

export const api = {
  appInfo: () => invoke<AppInfo>('app_info'),
  getSettings: () => invoke<Settings>('get_settings'),
  saveSettings: (settings: Settings) => invoke<Settings>('save_settings', { settings }),
  overview: () => invoke<Overview>('get_overview'),
  createBank: (speaker: Speaker) => invoke<Overview>('create_bank', { speaker }),
  updateSpeaker: (speaker: Speaker) => invoke<Overview>('update_speaker', { speaker }),

  listDevices: () => invoke<InputDevice[]>('list_devices'),
  checkRoom: () => invoke<RoomCheck>('check_room'),

  startSession: (energy: Energy) => invoke<SessionStart>('start_session', { energy }),
  morePrompts: (energy: Energy, count: number, exclude: string[]) =>
    invoke<QueuedPrompt[]>('more_prompts', { energy, count, exclude }),
  endSession: (sessionId: string) => invoke<SessionEnd>('end_session', { sessionId }),

  startRecording: (kind: RecordingKind) => invoke<number>('start_recording', { kind }),
  stopRecording: (kind: RecordingKind, text: string | null) =>
    invoke<PendingTake>('stop_recording', { kind, text }),
  cancelRecording: () => invoke<boolean>('cancel_recording'),
  keepTake: (token: string, promptId: string, sessionId: string | null) =>
    invoke<KeepResult>('keep_take', { token, promptId, sessionId }),
  discardTake: (token: string, sessionId: string | null, retry: boolean) =>
    invoke<void>('discard_take', { token, sessionId, retry }),
  pendingAudio: (token: string) => bytes('pending_audio', { token }),
  takeAudio: (promptId: string) => bytes('take_audio', { promptId }),
  recentTakes: (limit: number) => invoke<TakeSummary[]>('recent_takes', { limit }),
  deleteTake: (promptId: string) => invoke<Progress>('delete_take', { promptId }),

  listCustomPrompts: () => invoke<CustomPrompt[]>('list_custom_prompts'),
  addCustomPrompt: (text: string) => invoke<CustomPrompt>('add_custom_prompt', { text }),
  removeCustomPrompt: (id: string) => invoke<void>('remove_custom_prompt', { id }),

  listLegacy: () => invoke<LegacyMessage[]>('list_legacy'),
  saveLegacy: (token: string, details: LegacyDetails) =>
    invoke<LegacyMessage>('save_legacy', { token, details }),
  updateLegacy: (id: string, details: LegacyDetails) =>
    invoke<LegacyMessage>('update_legacy', { id, details }),
  deleteLegacy: (id: string) => invoke<void>('delete_legacy', { id }),
  legacyAudio: (id: string) => bytes('legacy_audio', { id }),

  exportBackup: (path: string) => invoke<ExportSummary>('export_backup', { path }),
  restoreBackup: (path: string) => invoke<Overview>('restore_backup', { path }),
  exportLegacy: (dir: string) => invoke<ExportSummary>('export_legacy', { dir }),
  openFolder: (which: 'bank' | 'voices' | 'data') => invoke<void>('open_folder', { which }),

  pipelineStatus: () => invoke<PipelineStatus>('pipeline_status'),
  listBases: async (): Promise<BaseVoice[]> => {
    const raw = await invoke<unknown>('list_bases');
    return normaliseBases(raw);
  },
  buildVoice: (base: string, quick: boolean) => invoke<void>('build_voice', { base, quick }),
  cancelBuild: () => invoke<boolean>('cancel_build'),
  listVoices: () => invoke<VoiceInfo[]>('list_voices'),
  deleteVoice: (id: string) => invoke<void>('delete_voice', { id }),
  tryVoice: (id: string, text: string) => bytes('try_voice', { id, text }),
  packageVoice: (id: string, format: string, dir: string) =>
    invoke<string[]>('package_voice', { id, format, dir }),
  installVoice: (id: string, target: 'linux' | 'windows') =>
    invoke<string>('install_voice', { id, target }),
};

/**
 * Accepts the registry as a list or as `{ bases: [...] }`, with snake_case or camelCase keys.
 * Voices that can't be fine-tuned (multi-speaker models) are left out.
 */
export function normaliseBases(raw: unknown): BaseVoice[] {
  const list = Array.isArray(raw)
    ? raw
    : raw && typeof raw === 'object' && Array.isArray((raw as { bases?: unknown }).bases)
      ? (raw as { bases: unknown[] }).bases
      : [];
  return list
    .filter((b): b is Record<string, unknown> => !!b && typeof b === 'object')
    .filter((b) => b.canFineTune !== false && b.can_fine_tune !== false)
    .map((b) => {
      const s = (k: string, alt?: string) => String(b[k] ?? (alt ? b[alt] : '') ?? '');
      const commercial = s('commercial');
      return {
        id: s('id'),
        name: s('name') || s('id'),
        language: s('language'),
        quality: s('quality'),
        dataset: s('dataset'),
        license: s('license', 'dataset_license') || s('datasetLicense'),
        commercial: (['yes', 'no', 'conditions'].includes(commercial)
          ? commercial
          : 'unknown') as BaseVoice['commercial'],
        lineage: s('lineage'),
        recommended: b.recommended === true,
        notes: s('notes'),
      };
    })
    .filter((b) => b.id);
}

export function onLevel(handler: (level: Level) => void): Promise<UnlistenFn> {
  return listen<Level>('level', (e) => handler(e.payload));
}

export function onPipeline(handler: (event: PipelineEvent) => void): Promise<UnlistenFn> {
  return listen<PipelineEvent>('pipeline', (e) => handler(e.payload));
}

/** Error messages from commands arrive as strings. */
export function errorMessage(e: unknown): string {
  if (typeof e === 'string') return e;
  if (e instanceof Error) return e.message;
  return String(e);
}
