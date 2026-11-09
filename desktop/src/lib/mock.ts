// Development-only stand-in for the Rust backend. When the interface runs in a plain browser
// (`npm run dev`), this serves a demo voice bank, simulated microphone levels and generated
// audio, so the app can be worked on and screenshotted without a microphone. It is never part of
// the production build. No real person's voice or data is involved.
//
// URL options: ?view=progress  ?theme=dark|light|contrast  ?size=large  ?onboarding=1  ?empty=1

import { emit } from '@tauri-apps/api/event';
import { mockIPC, mockWindows } from '@tauri-apps/api/mocks';
import type {
  Analysis,
  BaseVoice,
  CustomPrompt,
  IssueCode,
  LegacyMessage,
  Milestone,
  Overview,
  Progress,
  QueuedPrompt,
  Settings,
  TakeSummary,
  VoiceInfo,
} from './types';

const params = new URLSearchParams(location.search);
const empty = params.has('empty') || params.has('onboarding');

const MILESTONES: Milestone[] = [
  { id: 'first-words', at: 10 },
  { id: 'preview', at: 100 },
  { id: 'recognisable', at: 300 },
  { id: 'natural', at: 600 },
  { id: 'rich', at: 1000 },
  { id: 'complete', at: 1500 },
];

const SAMPLE_PROMPTS: QueuedPrompt[] = [
  {
    id: 'everyday-0102',
    setId: 'everyday-en',
    text: 'Could you open the window a little? It feels warm in here.',
  },
  {
    id: 'arctic_a0031',
    setId: 'arctic-en',
    text: 'His face was strained and his eyes were bright with feverish light.',
  },
  {
    id: 'personal-0003',
    setId: 'personal',
    text: 'Leo, put your shoes on, we are going to see Grandma!',
  },
  { id: 'phrases-0042', setId: 'phrases-en', text: 'That made my day.' },
  {
    id: 'everyday-0217',
    setId: 'everyday-en',
    text: 'What time does the garden centre close on Sundays?',
  },
  {
    id: 'arctic_a0207',
    setId: 'arctic-en',
    text: 'The sun had set and the sky was a deep, cold blue.',
  },
  {
    id: 'everyday-0311',
    setId: 'everyday-en',
    text: 'Thank you for sitting with me this afternoon. It meant a lot.',
  },
  { id: 'phrases-0007', setId: 'phrases-en', text: 'Not right now, maybe later.' },
  {
    id: 'arctic_b0110',
    setId: 'arctic-en',
    text: 'There was no sound save the crackle of the fire.',
  },
  {
    id: 'everyday-0044',
    setId: 'everyday-en',
    text: 'Shall we watch the match together on Saturday?',
  },
  { id: 'arctic_a0412', setId: 'arctic-en', text: 'They walked on in silence for a few minutes.' },
  {
    id: 'everyday-0390',
    setId: 'everyday-en',
    text: 'I would love a cup of tea with a splash of milk, please.',
  },
];

const SETS = [
  {
    id: 'arctic-en',
    language: 'en',
    title: 'Sound-rich sentences',
    description:
      'Sentences from classic books, chosen by Carnegie Mellon University to cover the sounds of English quickly.',
    license: 'CMU-ARCTIC',
    source: 'CMU ARCTIC prompts (festvox), with 51 sentences left out by Vocalkeep',
    attribution: 'CMU ARCTIC databases, John Kominek and Alan W Black, Carnegie Mellon University.',
    count: 1081,
    weight: 3,
  },
  {
    id: 'everyday-en',
    language: 'en',
    title: 'Everyday conversation',
    description:
      'Natural sentences for everyday talk, so your voice sounds like you in conversation.',
    license: 'CC0-1.0',
    source: 'Written for Vocalkeep',
    attribution: null,
    count: 400,
    weight: 2,
  },
  {
    id: 'phrases-en',
    language: 'en',
    title: 'Short phrases',
    description:
      "Short phrases you'll say every day, in your own tone of voice. Good for tired days.",
    license: 'CC0-1.0',
    source: 'Written for Vocalkeep',
    attribution: null,
    count: 150,
    weight: 1,
  },
];

const BASES: BaseVoice[] = [
  {
    id: 'en_US-ljspeech-medium',
    name: 'LJ Speech (US English)',
    language: 'en-US',
    quality: 'medium',
    dataset: 'LJ Speech',
    license: 'Public domain',
    commercial: 'yes',
    lineage: 'Trained from scratch',
    recommended: true,
    notes: 'A clear, neutral voice from public-domain audiobooks. The safest choice.',
  },
  {
    id: 'en_US-kristin-medium',
    name: 'Kristin (US English)',
    language: 'en-US',
    quality: 'medium',
    dataset: 'LibriVox',
    license: 'Public domain',
    commercial: 'yes',
    lineage: 'Trained from scratch',
    recommended: true,
    notes: 'Public-domain LibriVox recordings.',
  },
  {
    id: 'en_US-john-medium',
    name: 'John (US English)',
    language: 'en-US',
    quality: 'medium',
    dataset: 'LibriVox',
    license: 'Public domain',
    commercial: 'yes',
    lineage: 'Fine-tuned from Kristin',
    recommended: false,
    notes: 'A lower voice, built on Kristin.',
  },
  {
    id: 'en_GB-cori-medium',
    name: 'Cori (UK English)',
    language: 'en-GB',
    quality: 'medium',
    dataset: 'LibriVox',
    license: 'Public domain',
    commercial: 'yes',
    lineage: 'Trained from scratch',
    recommended: true,
    notes: 'Public-domain British English.',
  },
  {
    id: 'en_US-lessac-medium',
    name: 'Lessac (US English)',
    language: 'en-US',
    quality: 'medium',
    dataset: 'Blizzard 2013 Lessac',
    license: 'Research only',
    commercial: 'no',
    lineage: 'Trained from scratch',
    recommended: false,
    notes: 'Popular, but its recordings may not be used commercially.',
  },
  {
    id: 'en_US-libritts_r-medium',
    name: 'LibriTTS-R (US English)',
    language: 'en-US',
    quality: 'medium',
    dataset: 'LibriTTS-R',
    license: 'CC BY 4.0',
    commercial: 'no',
    lineage: 'Fine-tuned from Lessac (research only)',
    recommended: false,
    notes: 'Inherits the Lessac restriction.',
  },
];

function daysAgo(n: number, hour = 10): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  d.setHours(hour, 15, 0, 0);
  return d.toISOString();
}

let kept = empty ? 0 : 412;
const recentDays = empty
  ? []
  : [
      [13, 18],
      [12, 25],
      [10, 12],
      [9, 30],
      [8, 22],
      [6, 9],
      [5, 26],
      [4, 31],
      [3, 14],
      [1, 28],
      [0, 17],
    ].map(([ago, n]) => ({ date: daysAgo(ago!).slice(0, 10), kept: n! }));

function progress(): Progress {
  const milestone = [...MILESTONES].reverse().find((m) => kept >= m.at) ?? null;
  const next = MILESTONES.find((m) => kept < m.at) ?? null;
  const from = milestone?.at ?? 0;
  return {
    kept,
    good: Math.round(kept * 0.86),
    okay: kept - Math.round(kept * 0.86),
    needsRedo: empty ? 0 : 6,
    totalPrompts: 1631 + custom.length,
    speechMinutes: kept * 0.052,
    phonemesCovered: Math.min(64, Math.round(12 + Math.sqrt(kept) * 2.6)),
    phonemesTotal: 64,
    diphonesCovered: Math.min(2210, Math.round(kept * 3.1)),
    diphonesTotal: 2210,
    milestone,
    nextMilestone: next,
    toNext: next ? (kept - from) / (next.at - from) : 1,
    recommended: 600,
    sets: [
      {
        id: 'arctic-en',
        title: 'Sound-rich sentences',
        recorded: Math.round(kept * 0.52),
        total: 1081,
      },
      {
        id: 'everyday-en',
        title: 'Everyday conversation',
        recorded: Math.round(kept * 0.33),
        total: 400,
      },
      { id: 'phrases-en', title: 'Short phrases', recorded: Math.round(kept * 0.12), total: 150 },
      {
        id: 'personal',
        title: 'Your own phrases',
        recorded: custom.filter((c) => c.recorded).length,
        total: custom.length,
      },
    ],
    sessions: empty ? 0 : 23,
    daysRecorded: empty ? 0 : 19,
    lastSessionAt: empty ? null : daysAgo(1, 16),
    legacyMessages: legacy.length,
    legacyMinutes: legacy.reduce((a, m) => a + m.durationMs, 0) / 60000,
    recentDays,
  };
}

let custom: CustomPrompt[] = empty
  ? []
  : [
      {
        id: 'personal-0001',
        text: 'Hello, Priya! How was school today?',
        createdAt: daysAgo(20),
        recorded: true,
      },
      {
        id: 'personal-0002',
        text: 'Biscuit, come here, good boy!',
        createdAt: daysAgo(20),
        recorded: true,
      },
      {
        id: 'personal-0003',
        text: 'Leo, put your shoes on, we are going to see Grandma!',
        createdAt: daysAgo(12),
        recorded: false,
      },
      {
        id: 'personal-0004',
        text: 'Right then, who wants a cup of tea?',
        createdAt: daysAgo(3),
        recorded: false,
      },
    ];

let legacy: LegacyMessage[] = empty
  ? []
  : [
      {
        id: 'm1',
        title: 'Happy 18th birthday',
        recipient: 'Leo',
        occasion: 'Birthday',
        recordedBy: 'Maya',
        note: 'For the morning of your eighteenth.',
        file: 'legacy/m1.wav',
        sampleRate: 48000,
        durationMs: 124000,
        recordedAt: daysAgo(2, 18),
      },
      {
        id: 'm2',
        title: 'For your wedding day',
        recipient: 'Ana',
        occasion: 'Wedding day',
        recordedBy: 'Maya',
        note: '',
        file: 'legacy/m2.wav',
        sampleRate: 48000,
        durationMs: 241000,
        recordedAt: daysAgo(9, 11),
      },
      {
        id: 'm3',
        title: 'The lighthouse story',
        recipient: 'The grandchildren',
        occasion: 'A story',
        recordedBy: 'Maya',
        note: 'The one I tell at bedtime.',
        file: 'legacy/m3.wav',
        sampleRate: 48000,
        durationMs: 412000,
        recordedAt: daysAgo(15, 20),
      },
      {
        id: 'm4',
        title: 'Mum, from both of us',
        recipient: 'Maya',
        occasion: 'Just because',
        recordedBy: 'Sam and Ana',
        note: 'Recorded by the family.',
        file: 'legacy/m4.wav',
        sampleRate: 48000,
        durationMs: 58000,
        recordedAt: daysAgo(17, 19),
      },
    ];

const voices: VoiceInfo[] = empty
  ? []
  : [
      {
        id: 'en_GB-maya-medium',
        name: 'Maya',
        language: 'en-GB',
        gender: 'female',
        sampleRate: 22050,
        base: {
          id: 'en_GB-cori-medium',
          license: 'Public domain',
          commercial: 'yes',
          lineage: 'Trained from scratch',
        },
        bank: { id: 'demo', takes: 380, minutes: 19.8 },
        createdAt: daysAgo(4, 9),
        vocalkeepVersion: '0.1.0',
        path: '/home/maya/.local/share/io.github.lobojoel2003.vocalkeep/voices/en_GB-maya-medium',
        sizeBytes: 63_201_442,
        modelCard:
          "Maya's voice, made with Vocalkeep from 380 recorded sentences (about 20 minutes).\nStarting voice: en_GB-cori-medium (LibriVox, public domain).\nThis voice belongs to the person who recorded it.",
      },
    ];

let settings: Settings = {
  theme: (params.get('theme') as Settings['theme']) ?? 'system',
  textSize: (params.get('size') as Settings['textSize']) ?? 'normal',
  reduceMotion: false,
  inputDevice: null,
  sessions: {
    strong: { minutes: 20, prompts: 40 },
    okay: { minutes: 12, prompts: 25 },
    tired: { minutes: 5, prompts: 10 },
  },
  breakEvery: 10,
  autoPlay: false,
  autoKeepGood: false,
  enabledSets: [],
  bankDir: null,
  pipelineCommand: null,
  onboarded: !empty,
};

let bankExists = !empty;
let speakerName = empty ? '' : 'Maya';

function overview(): Overview {
  return {
    bank: bankExists
      ? {
          id: 'demo',
          speaker: { name: speakerName, language: 'en-GB', gender: 'female' },
          room: {
            level: 'quiet',
            noiseFloorDbfs: -63.2,
            peakDbfs: -41.0,
            sampleRate: 48000,
            checkedAt: daysAgo(6),
          },
          createdAt: daysAgo(40),
          path: '/home/maya/.local/share/io.github.lobojoel2003.vocalkeep/voice-bank',
        }
      : null,
    progress: bankExists ? progress() : null,
    sets: SETS,
    milestones: MILESTONES,
  };
}

// ----- Simulated audio -----

let meter: ReturnType<typeof setInterval> | null = null;
let recordStart = 0;
let take = 0;

function startMeter(silent = false) {
  stopMeter();
  recordStart = performance.now();
  meter = setInterval(() => {
    const t = (performance.now() - recordStart) / 1000;
    const syllable = Math.abs(Math.sin(t * Math.PI * 3.2)) * (0.6 + 0.4 * Math.sin(t * 1.3));
    const rms = silent
      ? -64 + Math.random() * 2
      : t < 0.4
        ? -62
        : -34 + syllable * 18 + Math.random() * 3;
    void emit('level', {
      rmsDbfs: rms,
      peakDbfs: rms + 9,
      clipping: false,
      elapsedMs: Math.round(t * 1000),
      limitReached: false,
    });
  }, 50);
}

function stopMeter() {
  if (meter) clearInterval(meter);
  meter = null;
}

function analysis(issues: IssueCode[] = []): Analysis {
  return {
    verdict: issues.length === 0 ? 'good' : issues.includes('clipping') ? 'redo' : 'okay',
    issues: issues.map((code) => ({ code, severity: code === 'clipping' ? 'redo' : 'warn' })),
    sampleRate: 48000,
    durationMs: 3400,
    peakDbfs: -6.1,
    speechDbfs: -21.4,
    noiseFloorDbfs: -64.8,
    snrDb: 43.4,
    clippedSamples: 0,
    clipRuns: 0,
    dcOffset: 0,
    speechStartMs: 420,
    speechEndMs: 3080,
    speechMs: 2480,
    longestPauseMs: 260,
  };
}

/** A soft, voice-like hum, so Listen does something in the browser. */
function toneWav(seconds: number): ArrayBuffer {
  const rate = 22050;
  const n = Math.floor(rate * seconds);
  const buf = new ArrayBuffer(44 + n * 2);
  const v = new DataView(buf);
  const str = (o: number, s: string) =>
    [...s].forEach((c, i) => v.setUint8(o + i, c.charCodeAt(0)));
  str(0, 'RIFF');
  v.setUint32(4, 36 + n * 2, true);
  str(8, 'WAVE');
  str(12, 'fmt ');
  v.setUint32(16, 16, true);
  v.setUint16(20, 1, true);
  v.setUint16(22, 1, true);
  v.setUint32(24, rate, true);
  v.setUint32(28, rate * 2, true);
  v.setUint16(32, 2, true);
  v.setUint16(34, 16, true);
  str(36, 'data');
  v.setUint32(40, n * 2, true);
  for (let i = 0; i < n; i++) {
    const t = i / rate;
    const env = Math.abs(Math.sin(Math.PI * 3 * t)) ** 0.6 * Math.min(1, t * 8, (seconds - t) * 8);
    let s = 0;
    for (let h = 1; h <= 5; h++) s += Math.sin(2 * Math.PI * 160 * h * t) / h;
    v.setInt16(44 + i * 2, Math.round(s * env * 3000), true);
  }
  return buf;
}

function takes(): TakeSummary[] {
  return SAMPLE_PROMPTS.slice(0, 8).map((p, i) => ({
    promptId: p.id,
    setId: p.setId,
    text: p.text,
    verdict: i === 2 ? 'okay' : 'good',
    issues: i === 2 ? ['too-quiet'] : [],
    recordedAt: daysAgo(i < 4 ? 0 : 1, 15 - i),
    durationMs: 3000 + i * 200,
    attempts: 1,
  }));
}

let queueIndex = 0;
function nextPrompts(count: number): QueuedPrompt[] {
  const out: QueuedPrompt[] = [];
  for (let i = 0; i < count; i++) {
    const p = SAMPLE_PROMPTS[(queueIndex + i) % SAMPLE_PROMPTS.length]!;
    out.push({ ...p, id: `${p.id}-${queueIndex + i}` });
  }
  queueIndex += count;
  return out;
}

function simulateBuild(quick: boolean) {
  const stages: [string, string][] = [
    ['prepare', 'Preparing 412 recordings'],
    ['download', 'Downloading en_GB-cori-medium'],
    ['train', 'Epoch 700 of 1640'],
  ];
  let step = 0;
  const timer = setInterval(() => {
    step += 1;
    if (step <= 3) {
      const [stage, message] = stages[step - 1]!;
      void emit('pipeline', { event: 'stage', stage, message });
      return;
    }
    const fraction = Math.min(1, (step - 3) / (quick ? 12 : 30));
    void emit('pipeline', {
      event: 'progress',
      stage: 'train',
      fraction,
      message: `Epoch ${Math.round(640 + fraction * 1000)} of 1640`,
    });
    void emit('pipeline', {
      event: 'log',
      message: `loss_gen_all=${(28 - fraction * 4).toFixed(2)}`,
    });
    if (fraction >= 1) {
      clearInterval(timer);
      void emit('pipeline', {
        event: 'done',
        voice: voices[0]?.path,
        message: 'Your voice is ready.',
      });
      buildDone?.();
    }
  }, 700);
}
let buildDone: (() => void) | null = null;

export function installMockBackend(): void {
  mockWindows('main');
  mockIPC(
    async (cmd, args) => {
      const a = (args ?? {}) as Record<string, unknown>;
      switch (cmd) {
        case 'app_info':
          return {
            version: '0.1.0',
            buildNumber: 'dev',
            gitSha: 'demo',
            buildDate: new Date().toISOString().slice(0, 10),
            platform: 'linux',
            dataDir: '/home/maya/.local/share/io.github.lobojoel2003.vocalkeep',
            bankDir: '/home/maya/.local/share/io.github.lobojoel2003.vocalkeep/voice-bank',
            voicesDir: '/home/maya/.local/share/io.github.lobojoel2003.vocalkeep/voices',
          };
        case 'get_settings':
          return settings;
        case 'save_settings':
          settings = a.settings as Settings;
          return settings;
        case 'get_overview':
          return overview();
        case 'create_bank':
        case 'update_speaker':
          bankExists = true;
          speakerName = (a.speaker as { name: string }).name;
          return overview();
        case 'list_devices':
          return [
            { id: 'alsa:usb-mic', name: 'USB Desk Microphone', isDefault: true },
            { id: 'alsa:laptop', name: 'Built-in Microphone', isDefault: false },
          ];
        case 'check_room':
          startMeter(true);
          await new Promise((r) => setTimeout(r, 2500));
          stopMeter();
          return {
            level: 'quiet',
            noiseFloorDbfs: -63.2,
            peakDbfs: -41,
            sampleRate: 48000,
            checkedAt: new Date().toISOString(),
          };
        case 'start_session': {
          const energy = a.energy as 'strong' | 'okay' | 'tired';
          const length = settings.sessions[energy];
          return {
            sessionId: 'demo-session',
            energy,
            length,
            breakEvery: settings.breakEvery,
            prompts: nextPrompts(Math.min(length.prompts, 12)),
          };
        }
        case 'more_prompts':
          return nextPrompts(Number(a.count ?? 10));
        case 'end_session':
          return { kept: 25, retried: 3, speechMinutes: 1.4, progress: progress() };
        case 'start_recording':
          startMeter();
          return 48000;
        case 'cancel_recording':
          stopMeter();
          return true;
        case 'stop_recording': {
          stopMeter();
          await new Promise((r) => setTimeout(r, 350));
          take += 1;
          const forced = params.get('verdict');
          const issues: IssueCode[] =
            forced === 'okay'
              ? ['too-quiet']
              : forced === 'redo'
                ? ['clipping']
                : take % 5 === 3
                  ? ['too-quiet']
                  : [];
          return {
            token: `t${take}`,
            analysis: analysis(a.kind === 'legacy' ? [] : issues),
            durationMs: 3400,
          };
        }
        case 'keep_take':
          kept += 1;
          return { take: takes()[0], progress: progress() };
        case 'discard_take':
          return null;
        case 'pending_audio':
        case 'take_audio':
        case 'legacy_audio':
        case 'try_voice':
          return toneWav(cmd === 'try_voice' ? 2.5 : 1.8);
        case 'recent_takes':
          return takes();
        case 'delete_take':
          kept = Math.max(0, kept - 1);
          return progress();
        case 'list_custom_prompts':
          return custom;
        case 'add_custom_prompt': {
          const p = {
            id: `personal-${custom.length + 1}`,
            text: String(a.text),
            createdAt: new Date().toISOString(),
            recorded: false,
          };
          custom = [...custom, p];
          return p;
        }
        case 'remove_custom_prompt':
          custom = custom.filter((c) => c.id !== a.id);
          return null;
        case 'list_legacy':
          return legacy;
        case 'save_legacy': {
          const d = a.details as LegacyMessage;
          const m: LegacyMessage = {
            ...d,
            id: `m${legacy.length + 1}`,
            file: '',
            sampleRate: 48000,
            durationMs: 65000,
            recordedAt: new Date().toISOString(),
          };
          legacy = [m, ...legacy];
          return m;
        }
        case 'update_legacy':
          legacy = legacy.map((m) => (m.id === a.id ? { ...m, ...(a.details as object) } : m));
          return legacy.find((m) => m.id === a.id);
        case 'delete_legacy':
          legacy = legacy.filter((m) => m.id !== a.id);
          return null;
        case 'export_backup':
          return { path: String(a.path), files: kept + legacy.length + 1, bytes: kept * 310_000 };
        case 'restore_backup':
          return overview();
        case 'export_legacy':
          return {
            path: `${a.dir}/Legacy messages from Maya`,
            files: legacy.length,
            bytes: 80_000_000,
          };
        case 'open_folder':
          return null;
        case 'pipeline_status':
          return {
            found: !params.has('nopipeline'),
            command: '/home/maya/.local/bin/vocalkeep',
            version: '0.1.0',
            doctor: {
              version: '0.1.0',
              canTrain: true,
              canSpeak: true,
              gpuName: 'NVIDIA GeForce RTX 3060',
            },
            error: null,
          };
        case 'list_bases':
          return BASES;
        case 'build_voice':
          return new Promise((resolve) => {
            buildDone = () => resolve(null);
            simulateBuild(Boolean(a.quick));
          });
        case 'cancel_build':
          return true;
        case 'list_voices':
          return voices;
        case 'delete_voice':
          return null;
        case 'package_voice':
          return [`${a.dir}/vits-piper-en_GB-maya-medium.tar.bz2`];
        case 'install_voice':
          return 'Installed. Test it with: spd-say -o vocalkeep-generic "Hello"';
        case 'self_test':
          return analysis();
        case 'plugin:dialog|open':
          return '/home/maya/Documents';
        case 'plugin:dialog|save':
          return '/home/maya/Documents/Maya voice bank.zip';
        case 'plugin:opener|open_url':
          window.open(String(a.url), '_blank', 'noopener');
          return null;
        default:
          console.warn('mock: unhandled command', cmd, args);
          return null;
      }
    },
    { shouldMockEvents: true },
  );
}
