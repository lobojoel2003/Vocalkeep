<script lang="ts">
  import { open as openDialog, save as saveDialog } from '@tauri-apps/plugin-dialog';
  import { onDestroy, onMount } from 'svelte';
  import { api, errorMessage, onPipeline } from '../lib/api';
  import { playWav } from '../lib/audio';
  import Icon, { type IconName } from '../lib/components/Icon.svelte';
  import { bytesText, dateText, minutesText, percent, plural } from '../lib/format';
  import { app } from '../lib/state.svelte';
  import type { BaseVoice, PipelineEvent, PipelineStatus, VoiceInfo } from '../lib/types';
  import { commercialText, pickDefaultBase, sortBases, stageText } from '../lib/voice';

  let status = $state<PipelineStatus | null>(null);
  let bases = $state<BaseVoice[]>([]);
  let voices = $state<VoiceInfo[]>([]);
  let base = $state<string>(localStorage.getItem('vocalkeep.base') ?? '');
  let freeOnly = $state(true);
  let building = $state(false);
  let stage = $state('');
  let fraction = $state<number | null>(null);
  let message = $state('');
  let log = $state<string[]>([]);
  let buildError = $state<string | null>(null);
  let tryText = $state('Hello, it is so good to hear my own voice again.');
  let speaking = $state<string | null>(null);
  let busy = $state<string | null>(null);
  let unlisten: (() => void) | null = null;

  const p = $derived(app.overview?.progress ?? null);
  const speaker = $derived(app.overview?.bank?.speaker ?? null);
  const platform = $derived(app.info?.platform ?? '');
  const shownBases = $derived(
    sortBases(bases, speaker?.language ?? 'en-US').filter(
      (b) => !freeOnly || b.commercial === 'yes',
    ),
  );
  const ready = $derived((p?.kept ?? 0) >= (p?.recommended ?? 600));

  onMount(async () => {
    unlisten = await onPipeline(onEvent);
    await Promise.all([loadStatus(), loadBases(), loadVoices()]);
  });
  onDestroy(() => unlisten?.());

  async function loadStatus() {
    try {
      status = await api.pipelineStatus();
    } catch (e) {
      status = { found: false, command: null, version: null, doctor: null, error: errorMessage(e) };
    }
  }

  async function loadBases() {
    try {
      bases = await api.listBases();
      if (!bases.some((b) => b.id === base))
        base = pickDefaultBase(bases, speaker?.language ?? 'en-US');
    } catch (e) {
      app.notify(errorMessage(e), 'error');
    }
  }

  async function loadVoices() {
    try {
      voices = await api.listVoices();
    } catch (e) {
      app.notify(errorMessage(e), 'error');
    }
  }

  function chooseBase(id: string) {
    base = id;
    localStorage.setItem('vocalkeep.base', id);
  }

  function onEvent(e: PipelineEvent) {
    if (e.event === 'stage') {
      stage = e.stage;
      fraction = null;
      message = e.message ?? '';
    } else if (e.event === 'progress') {
      stage = e.stage;
      fraction = e.fraction;
      message = e.message ?? message;
    } else if (e.event === 'log') {
      log = [...log.slice(-7), e.message];
    } else if (e.event === 'done') {
      message = e.message ?? 'Your voice is ready.';
    } else if (e.event === 'error') {
      buildError = e.message;
    }
  }

  async function build(quick: boolean) {
    if (!base) return;
    building = true;
    buildError = null;
    log = [];
    stage = 'prepare';
    fraction = null;
    message = '';
    try {
      await api.buildVoice(base, quick);
      app.notify('Your voice is ready. Try it below.', 'success');
      await loadVoices();
    } catch (e) {
      buildError = errorMessage(e);
    } finally {
      building = false;
    }
  }

  async function cancel() {
    await api.cancelBuild();
  }

  async function backup() {
    const name = (speaker?.name || 'voice').replace(/[^\w -]/g, '').trim() || 'voice';
    const path = await saveDialog({
      title: 'Back up your voice bank',
      defaultPath: `${name} voice bank.zip`,
      filters: [{ name: 'Zip archive', extensions: ['zip'] }],
    });
    if (!path) return;
    busy = 'backup';
    try {
      const s = await api.exportBackup(path);
      app.notify(
        `Saved ${plural(s.files, 'file')} (${bytesText(s.bytes)}) to ${s.path}`,
        'success',
      );
    } catch (e) {
      app.notify(errorMessage(e), 'error');
    } finally {
      busy = null;
    }
  }

  async function speak(v: VoiceInfo) {
    speaking = v.id;
    try {
      await playWav(await api.tryVoice(v.id, tryText));
    } catch (e) {
      app.notify(errorMessage(e), 'error');
    } finally {
      speaking = null;
    }
  }

  async function exportTo(v: VoiceInfo, format: string, what: string) {
    const dir = await openDialog({ directory: true, title: `Choose where to save ${what}` });
    if (typeof dir !== 'string') return;
    busy = `${v.id}:${format}`;
    try {
      const files = await api.packageVoice(v.id, format, dir);
      app.notify(`Saved ${files.map((f) => f.split(/[\\/]/).pop()).join(', ')}`, 'success');
    } catch (e) {
      app.notify(errorMessage(e), 'error');
    } finally {
      busy = null;
    }
  }

  async function install(v: VoiceInfo, target: 'linux' | 'windows') {
    busy = `${v.id}:install`;
    try {
      const out = await api.installVoice(v.id, target);
      app.notify(out.trim().split('\n').slice(-1)[0] || 'Installed.', 'success');
    } catch (e) {
      app.notify(errorMessage(e), 'error');
    } finally {
      busy = null;
    }
  }

  async function remove(v: VoiceInfo) {
    try {
      await api.deleteVoice(v.id);
      await loadVoices();
    } catch (e) {
      app.notify(errorMessage(e), 'error');
    }
  }

  const targets: { format: string; icon: IconName; title: string; body: string }[] = [
    {
      format: 'saywell',
      icon: 'phone',
      title: 'Saywell',
      body: 'Copy the file to the phone or tablet, then Settings › Saywell voices › Install from a file.',
    },
    {
      format: 'sherpatts',
      icon: 'phone',
      title: 'Android system voice',
      body: 'For the free SherpaTTS app, so every Android app can speak with your voice.',
    },
    {
      format: 'nvda',
      icon: 'computer',
      title: 'NVDA screen reader',
      body: 'Install with the Sonata add-on’s voice manager: Install from local file.',
    },
    {
      format: 'voicegarden',
      icon: 'computer',
      title: 'Windows (SAPI)',
      body: 'For VoiceGarden, which makes the voice available to Windows apps and AAC software like Grid.',
    },
    {
      format: 'piper',
      icon: 'archive',
      title: 'Piper files',
      body: 'The plain voice files, for Piper apps on Android, macOS and iPhone, and Home Assistant.',
    },
  ];
</script>

<section class="my-voice">
  <div class="eyebrow">My voice</div>
  <h1>From recordings to your voice</h1>
  <p class="lede">
    Vocalkeep teaches an open text-to-speech voice to sound like you, using your recordings.
    Building takes a few hours on a computer with a graphics card. It can be this computer, or a
    friend's: your voice bank backup is all it needs.
  </p>

  {#if p}
    <div class="card readiness" data-ready={ready}>
      <Icon name={ready ? 'sparkle' : 'leaf'} size={30} />
      <div>
        <h2>{ready ? 'Your voice bank is ready to build' : 'Still growing'}</h2>
        <p class="muted">
          You have {plural(p.kept, 'sentence')} ({minutesText(p.speechMinutes)}).
          {#if ready}
            That's enough for an everyday voice. More recordings still make it better.
          {:else}
            We suggest at least {p.recommended.toLocaleString('en')} for an everyday voice.
            {#if p.kept >= 100}You can build a preview now to hear how it's going.{/if}
          {/if}
        </p>
        <div class="bar"><div style:width={percent(p.kept / p.recommended)}></div></div>
      </div>
    </div>
  {/if}

  <div class="card">
    <div class="spread">
      <h2>1. Choose a starting voice</h2>
      <label class="check small">
        <input type="checkbox" bind:checked={freeOnly} />
        <span>Only voices free for any use</span>
      </label>
    </div>
    <p class="muted">
      Your voice is built on top of an existing open voice. Its licence comes with it, so this
      matters if your voice might ever be used commercially (for example in a paid product). Voices
      recorded from public-domain audio are the safest choice.
    </p>
    <div class="bases" role="radiogroup" aria-label="Starting voice">
      {#each shownBases as b (b.id)}
        {@const c = commercialText(b.commercial)}
        <button
          class="base"
          role="radio"
          aria-checked={base === b.id}
          onclick={() => chooseBase(b.id)}
        >
          <div class="spread">
            <strong>{b.name}</strong>
            <span class="row">
              {#if b.recommended}<span class="pill primary">Recommended</span>{/if}
              <span class="pill {c.tone}">{c.label}</span>
            </span>
          </div>
          <span class="muted small"
            >{b.language} · {b.dataset}{b.license ? ` · ${b.license}` : ''}</span
          >
          {#if b.notes}<span class="small">{b.notes}</span>{/if}
        </button>
      {:else}
        <p class="muted">
          {bases.length
            ? 'No voices match. Untick the box to see all of them.'
            : 'Loading starting voices…'}
        </p>
      {/each}
    </div>
  </div>

  <div class="card">
    <h2>2. Build</h2>
    {#if building}
      <div class="building" aria-live="polite">
        <div class="spread">
          <strong>{stageText(stage)}</strong>
          {#if fraction !== null}<span class="muted">{percent(fraction)}</span>{/if}
        </div>
        <div class="bar" class:indeterminate={fraction === null}>
          <div style:width={fraction === null ? '35%' : percent(fraction)}></div>
        </div>
        {#if message}<p class="muted small">{message}</p>{/if}
        {#if log.length}<pre aria-label="Recent output">{log.join('\n')}</pre>{/if}
        <p class="muted small">You can keep using Vocalkeep. Closing it stops the build.</p>
        <button class="btn danger" onclick={cancel}>Stop building</button>
      </div>
    {:else if status?.found}
      <p class="muted">
        Voice builder {status.version ?? ''} found{status.doctor && status.doctor['gpuName']
          ? `, using ${status.doctor['gpuName']}`
          : ''}. A preview takes about an hour; a full voice several hours.
      </p>
      {#if status.doctor && status.doctor['canTrain'] === false}
        <p class="note">
          <Icon name="info" size={18} /><span
            >{String(
              status.doctor['nextStep'] ??
                'The builder is installed, but training isn’t set up yet. Run “vocalkeep doctor” for the steps.',
            )}</span
          >
        </p>
      {/if}
      {#if buildError}<p class="note error">
          <Icon name="warn" size={18} /><span>{buildError}</span>
        </p>{/if}
      <div class="row">
        <button
          class="btn ghost big"
          onclick={() => build(true)}
          disabled={!base || (p?.kept ?? 0) < 10}
        >
          Build a preview
        </button>
        <button
          class="btn primary big"
          onclick={() => build(false)}
          disabled={!base || (p?.kept ?? 0) < 10}
        >
          <Icon name="sparkle" size={18} /> Build my voice
        </button>
      </div>
    {:else}
      <p>The voice builder isn't installed on this computer. You have two options:</p>
      <div class="options">
        <div class="card soft">
          <h3><Icon name="computer" size={20} /> Build on this computer</h3>
          <p class="muted small">
            Needs an NVIDIA graphics card and Python 3.10 or newer. Install the builder, then reopen
            this page:
          </p>
          <pre>pip install "vocalkeep[runtime] @ git+https://github.com/lobojoel2003/Vocalkeep#subdirectory=pipeline"
vocalkeep doctor</pre>
          <p class="muted small">
            <code>vocalkeep doctor</code> lists anything else training needs.
          </p>
        </div>
        <div class="card soft">
          <h3><Icon name="archive" size={20} /> Build on another computer</h3>
          <p class="muted small">
            Save a backup of your voice bank and give it to whoever is helping. They run:
          </p>
          <pre>vocalkeep build "voice bank.zip" --base {base ||
              'en_US-ljspeech-medium'} -o voices</pre>
          <button class="btn ghost" onclick={backup} disabled={busy === 'backup'}>
            <Icon name="download" size={18} /> Back up voice bank
          </button>
        </div>
      </div>
      {#if status?.error}<p class="muted small">({status.error})</p>{/if}
    {/if}
  </div>

  <div class="card">
    <h2>3. Use your voice</h2>
    {#if voices.length === 0}
      <p class="muted">Voices you build will appear here, ready to try and to install.</p>
    {/if}
    {#each voices as v (v.id)}
      <article class="voice">
        <div class="spread">
          <div>
            <h3>{v.name}</h3>
            <p class="muted small">
              Built {dateText(v.createdAt)} from {plural(v.bank.takes, 'sentence')} · starting voice {v
                .base.id}
              ({commercialText(v.base.commercial as BaseVoice['commercial']).label.toLowerCase()})
            </p>
          </div>
          <button class="btn icon quiet" onclick={() => remove(v)} aria-label={`Delete ${v.name}`}
            ><Icon name="trash" size={18} /></button
          >
        </div>
        <div class="try">
          <input type="text" bind:value={tryText} aria-label="Something for your voice to say" />
          <button
            class="btn primary"
            onclick={() => speak(v)}
            disabled={speaking !== null || !status?.found}
          >
            <Icon name="play" size={16} />
            {speaking === v.id ? 'Speaking…' : 'Say it'}
          </button>
        </div>
        <div class="targets">
          {#if platform === 'linux' || platform === 'windows'}
            <div class="target highlight">
              <div class="t-head">
                <Icon name="computer" size={20} /><strong>This computer</strong>
              </div>
              <p class="muted small">
                {platform === 'linux'
                  ? 'Adds your voice to speech-dispatcher, so Orca and other Linux apps can use it.'
                  : 'Copies your voice to VoiceGarden. Then choose “Install to SAPI” in VoiceGarden.'}
              </p>
              <button
                class="btn primary"
                disabled={busy !== null || !status?.found}
                onclick={() => install(v, platform as 'linux' | 'windows')}
              >
                {busy === `${v.id}:install` ? 'Installing…' : 'Install'}
              </button>
            </div>
          {/if}
          {#each targets as t (t.format)}
            <div class="target">
              <div class="t-head"><Icon name={t.icon} size={20} /><strong>{t.title}</strong></div>
              <p class="muted small">{t.body}</p>
              <button
                class="btn ghost"
                disabled={busy !== null || !status?.found}
                onclick={() => exportTo(v, t.format, `the ${t.title} files`)}
              >
                {busy === `${v.id}:${t.format}` ? 'Saving…' : 'Save files'}
              </button>
            </div>
          {/each}
        </div>
        {#if v.modelCard}
          <details>
            <summary>About this voice (model card)</summary>
            <pre>{v.modelCard}</pre>
          </details>
        {/if}
      </article>
    {/each}
  </div>
</section>

<style>
  .my-voice {
    display: flex;
    flex-direction: column;
    gap: 1.25rem;
  }
  .readiness {
    display: flex;
    gap: 1rem;
    align-items: flex-start;
  }
  .readiness > :global(svg) {
    color: var(--accent);
    flex: none;
  }
  .readiness > div {
    flex: 1;
  }
  .bar {
    position: relative;
    height: 10px;
    border-radius: 999px;
    background: var(--surface-2);
    overflow: hidden;
    margin: 0.5rem 0;
  }
  .bar div {
    height: 100%;
    border-radius: 999px;
    background: linear-gradient(90deg, var(--primary), var(--accent));
    transition: width calc(var(--speed) * 3);
  }
  .bar.indeterminate div {
    position: absolute;
    animation: slide 1.8s ease-in-out infinite;
  }
  @keyframes slide {
    from {
      left: -35%;
    }
    to {
      left: 100%;
    }
  }
  .bases {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(18rem, 1fr));
    gap: 0.75rem;
    margin-top: 0.75rem;
  }
  .base {
    display: flex;
    flex-direction: column;
    gap: 0.3rem;
    text-align: left;
    font: inherit;
    color: inherit;
    padding: 0.9rem 1rem;
    border-radius: var(--radius-sm);
    border: 2px solid var(--border);
    background: var(--surface);
    cursor: pointer;
  }
  .base[aria-checked='true'] {
    border-color: var(--primary);
    background: var(--primary-soft);
  }
  .options {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 1rem;
    margin-top: 0.5rem;
  }
  .options h3 {
    display: flex;
    gap: 0.5rem;
    align-items: center;
  }
  .options pre {
    background: var(--surface);
    margin: 0.5rem 0;
    white-space: pre-wrap;
    word-break: break-all;
  }
  .note {
    display: flex;
    gap: 0.5rem;
    background: var(--okay-soft);
    padding: 0.6rem 0.8rem;
    border-radius: var(--radius-sm);
  }
  .note.error {
    background: var(--redo-soft);
  }
  .note span {
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }
  .building pre {
    margin: 0.5rem 0;
    max-height: 10rem;
  }
  .voice {
    border-top: 1px solid var(--border);
    padding-top: 1rem;
    margin-top: 1rem;
    display: flex;
    flex-direction: column;
    gap: 0.9rem;
  }
  .voice h3 {
    margin: 0;
  }
  .voice p {
    margin: 0.15rem 0 0;
  }
  .try {
    display: flex;
    gap: 0.6rem;
  }
  .targets {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(15rem, 1fr));
    gap: 0.75rem;
  }
  .target {
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
    align-items: flex-start;
    padding: 0.9rem 1rem;
    border-radius: var(--radius-sm);
    background: var(--surface-2);
  }
  .target.highlight {
    background: var(--primary-soft);
  }
  .target p {
    flex: 1;
  }
  .t-head {
    display: flex;
    gap: 0.5rem;
    align-items: center;
  }
  details pre {
    white-space: pre-wrap;
    margin-top: 0.5rem;
  }
  summary {
    cursor: pointer;
    color: var(--muted);
  }
  @media (max-width: 860px) {
    .options {
      grid-template-columns: 1fr;
    }
  }
</style>
