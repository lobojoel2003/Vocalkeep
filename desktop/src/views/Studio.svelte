<script lang="ts">
  import { onDestroy, onMount, untrack } from 'svelte';
  import { api, errorMessage, onLevel } from '../lib/api';
  import { playWav, stopPlayback } from '../lib/audio';
  import Icon from '../lib/components/Icon.svelte';
  import LevelMeter from '../lib/components/LevelMeter.svelte';
  import { ENERGY_TEXT, topIssues, VERDICT_TEXT } from '../lib/feedback';
  import { clock, minutesText, plural } from '../lib/format';
  import { crossedMilestone, MILESTONE_TEXT } from '../lib/milestones';
  import { app } from '../lib/state.svelte';
  import type {
    Level,
    Milestone,
    PendingTake,
    QueuedPrompt,
    SessionEnd,
    SessionStart,
  } from '../lib/types';

  let { session }: { session: SessionStart } = $props();

  type Phase =
    'ready' | 'starting' | 'recording' | 'checking' | 'review' | 'break' | 'target' | 'summary';

  // The queue starts from the session's first prompts and then grows on its own.
  const initial = untrack(() => session.prompts);
  let queue = $state<QueuedPrompt[]>([...initial]);
  let index = $state(0);
  let phase = $state<Phase>(initial.length ? 'ready' : 'summary');
  let pending = $state<PendingTake | null>(null);
  let level = $state<Level | null>(null);
  let kept = $state(0);
  let extra = $state(0);
  let elapsedMs = $state(0);
  let playing = $state(false);
  let busy = $state(false);
  let summary = $state<SessionEnd | null>(null);
  let celebrated = $state<Milestone | null>(null);
  let autoKeepTimer: ReturnType<typeof setTimeout> | null = null;

  const keptBefore = app.overview?.progress?.kept ?? 0;
  const startedAt = Date.now();
  const sets = $derived(new Map((app.overview?.sets ?? []).map((s) => [s.id, s.title])));
  const prompt = $derived(queue[index] ?? null);
  const targetPrompts = $derived(session.length.prompts + extra);
  const targetMs = $derived(session.length.minutes * 60_000 + (extra > 0 ? 5 * 60_000 : 0));
  const setTitle = $derived(
    prompt
      ? prompt.setId === 'personal'
        ? 'Your own phrase'
        : (sets.get(prompt.setId) ?? '')
      : '',
  );

  let tick: ReturnType<typeof setInterval>;
  let unlisten: (() => void) | null = null;

  onMount(() => {
    tick = setInterval(() => (elapsedMs = Date.now() - startedAt), 1000);
    onLevel((l) => (level = l)).then((u) => (unlisten = u));
  });

  onDestroy(() => {
    clearInterval(tick);
    unlisten?.();
    stopPlayback();
    if (autoKeepTimer) clearTimeout(autoKeepTimer);
    if (phase === 'recording') void api.cancelRecording();
  });

  async function startRecording() {
    if (!prompt || busy) return;
    stopPlayback();
    phase = 'starting';
    level = null;
    try {
      await api.startRecording('take');
      phase = 'recording';
    } catch (e) {
      phase = 'ready';
      app.notify(errorMessage(e), 'error');
    }
  }

  async function stopRecording() {
    if (phase !== 'recording' || !prompt) return;
    phase = 'checking';
    try {
      pending = await api.stopRecording('take', prompt.text);
      phase = 'review';
      if (app.settings?.autoPlay) void listen();
      if (pending.analysis.verdict === 'good' && app.settings?.autoKeepGood) {
        autoKeepTimer = setTimeout(() => void keep(), 1200);
      }
    } catch (e) {
      phase = 'ready';
      app.notify(errorMessage(e), 'error');
    }
  }

  function clearAutoKeep() {
    if (autoKeepTimer) {
      clearTimeout(autoKeepTimer);
      autoKeepTimer = null;
    }
  }

  async function listen() {
    if (!pending) return;
    clearAutoKeep();
    playing = true;
    try {
      await playWav(await api.pendingAudio(pending.token));
    } catch (e) {
      app.notify(errorMessage(e), 'error');
    } finally {
      playing = false;
    }
  }

  async function retry() {
    clearAutoKeep();
    stopPlayback();
    if (pending) await api.discardTake(pending.token, session.sessionId, true).catch(() => {});
    pending = null;
    phase = 'ready';
  }

  async function keep() {
    clearAutoKeep();
    if (!pending || !prompt || busy) return;
    busy = true;
    stopPlayback();
    try {
      const result = await api.keepTake(pending.token, prompt.id, session.sessionId);
      if (app.overview) app.overview.progress = result.progress;
      kept += 1;
      pending = null;
      await advance();
    } catch (e) {
      app.notify(errorMessage(e), 'error');
    } finally {
      busy = false;
    }
  }

  async function skip() {
    clearAutoKeep();
    stopPlayback();
    if (pending) await api.discardTake(pending.token, session.sessionId, false).catch(() => {});
    pending = null;
    await advance(true);
  }

  async function advance(skipped = false) {
    index += 1;
    if (queue.length - index < 3) {
      try {
        const more = await api.morePrompts(
          session.energy,
          10,
          queue.map((p) => p.id),
        );
        queue = [...queue, ...more];
      } catch {
        // Keep going with what we have.
      }
    }
    if (index >= queue.length) {
      await finish();
      return;
    }
    if (!skipped && (kept >= targetPrompts || elapsedMs >= targetMs)) {
      phase = 'target';
    } else if (!skipped && session.breakEvery > 0 && kept > 0 && kept % session.breakEvery === 0) {
      phase = 'break';
    } else {
      phase = 'ready';
    }
  }

  function aFewMore() {
    extra += 5;
    phase = 'ready';
  }

  async function finish() {
    clearAutoKeep();
    stopPlayback();
    if (phase === 'recording') await api.cancelRecording().catch(() => {});
    if (pending) await api.discardTake(pending.token, null, false).catch(() => {});
    pending = null;
    busy = true;
    try {
      summary = await api.endSession(session.sessionId);
      if (app.overview) app.overview.progress = summary.progress;
      celebrated = crossedMilestone(
        keptBefore,
        summary.progress.kept,
        app.overview?.milestones ?? [],
      );
    } catch (e) {
      app.notify(errorMessage(e), 'error');
    } finally {
      busy = false;
      phase = 'summary';
    }
  }

  async function close() {
    app.session = null;
    await app.refresh();
    app.go('today');
  }

  function onKeydown(e: KeyboardEvent) {
    if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    const k = e.key.toLowerCase();
    if (k === ' ' || k === 'spacebar') {
      e.preventDefault();
      if (phase === 'ready') void startRecording();
      else if (phase === 'recording') void stopRecording();
      else if (phase === 'break' || phase === 'target') phase = 'ready';
    } else if (k === 'enter' && phase === 'review') {
      e.preventDefault();
      if (pending?.analysis.verdict === 'redo') void retry();
      else void keep();
    } else if (k === 'r' && phase === 'review') {
      void retry();
    } else if ((k === 'l' || k === 'p') && phase === 'review') {
      void listen();
    } else if (k === 's' && (phase === 'ready' || phase === 'review')) {
      void skip();
    } else if (k === 'escape' && phase === 'recording') {
      void api.cancelRecording();
      phase = 'ready';
    }
  }

  function summaryLine(s: SessionEnd): string {
    const spoken = s.speechMinutes >= 0.1 ? `, ${minutesText(s.speechMinutes)} of your voice` : '';
    return `You kept ${plural(s.kept, 'sentence')} today${spoken}. Rest now; your voice will be here tomorrow.`;
  }

  const minutesLeft = $derived(Math.max(0, Math.ceil((targetMs - elapsedMs) / 60_000)));
</script>

<svelte:window onkeydown={onKeydown} />

<div class="studio">
  <header class="top">
    <div class="row">
      <span class="pill primary">{ENERGY_TEXT[session.energy].title} day</span>
      <span class="muted small" aria-live="polite">{plural(kept, 'sentence')} kept</span>
    </div>
    <div class="session-bar" aria-hidden="true">
      <div style:width="{Math.min(100, (kept / Math.max(1, targetPrompts)) * 100)}%"></div>
    </div>
    <div class="row">
      <span class="muted small" title="Time in this session">{clock(elapsedMs)}</span>
      {#if phase !== 'summary'}
        <button class="btn ghost" onclick={finish} disabled={busy}>End session</button>
      {/if}
    </div>
  </header>

  <main class="stage">
    {#if phase === 'summary'}
      <section class="summary card fade-in" aria-labelledby="summary-title">
        <Icon name="heart" size={40} />
        <h1 id="summary-title">
          Well done{app.overview?.bank?.speaker.name
            ? `, ${app.overview.bank.speaker.name.split(' ')[0]}`
            : ''}.
        </h1>
        {#if summary}
          <p class="lede">{summaryLine(summary)}</p>
          {#if celebrated}
            <div class="milestone">
              <Icon name="sparkle" size={28} />
              <div>
                <strong
                  >You reached “{MILESTONE_TEXT[celebrated.id]?.title ?? celebrated.id}”</strong
                >
                <p class="muted">{MILESTONE_TEXT[celebrated.id]?.body ?? ''}</p>
              </div>
            </div>
          {/if}
          <p class="muted">
            In total: {plural(summary.progress.kept, 'sentence')} and
            {summary.progress.phonemesCovered} of {summary.progress.phonemesTotal} speech sounds.
          </p>
        {/if}
        <button class="btn primary big" onclick={close} disabled={busy}>Back to today</button>
      </section>
    {:else if phase === 'break'}
      <section class="pause card fade-in" aria-labelledby="break-title">
        <Icon name="water" size={44} />
        <h1 id="break-title">Time for a sip of water?</h1>
        <p class="lede">
          Your voice is working hard. Take a breath, have a drink, and carry on when you're ready.
        </p>
        <div class="row center">
          <button class="btn primary big" onclick={() => (phase = 'ready')}>I'm ready</button>
          <button class="btn ghost big" onclick={finish}>Stop for today</button>
        </div>
      </section>
    {:else if phase === 'target'}
      <section class="pause card fade-in" aria-labelledby="target-title">
        <Icon name="leaf" size={44} />
        <h1 id="target-title">That's a good place to stop</h1>
        <p class="lede">
          Short sessions protect your voice. You've kept {plural(kept, 'sentence')}.
          {#if minutesLeft > 0}You can keep going if you feel strong.{/if}
        </p>
        <div class="row center">
          <button class="btn primary big" onclick={finish}>Finish for today</button>
          <button class="btn ghost big" onclick={aFewMore}>A few more</button>
        </div>
      </section>
    {:else if prompt}
      <section class="prompt-card card" aria-labelledby="prompt-text">
        <div class="eyebrow">{setTitle}</div>
        <p id="prompt-text" class="prompt" class:dim={phase === 'review'}>{prompt.text}</p>
      </section>

      <div class="controls">
        {#if phase === 'review' && pending}
          {@const verdict = pending.analysis.verdict}
          {@const notes = topIssues(pending.analysis)}
          <section class="verdict fade-in" data-verdict={verdict} aria-live="polite">
            <div class="verdict-head">
              <span class="dot" aria-hidden="true"
                ><Icon name={verdict === 'redo' ? 'redo' : 'check'} size={20} /></span
              >
              <div>
                <h2>{VERDICT_TEXT[verdict].title}</h2>
                {#if notes.length === 0}
                  <p class="muted">{VERDICT_TEXT[verdict].body}</p>
                {/if}
              </div>
            </div>
            {#if notes.length}
              <ul class="notes">
                {#each notes as note (note.title)}
                  <li><strong>{note.title}.</strong> {note.tip}</li>
                {/each}
              </ul>
            {/if}
            <div class="row center actions">
              <button class="btn ghost big" onclick={listen} disabled={playing}>
                <Icon name="play" size={18} />
                {playing ? 'Playing…' : 'Listen'}
              </button>
              {#if verdict === 'redo'}
                <button class="btn primary big" onclick={retry}
                  ><Icon name="redo" size={18} /> Try again</button
                >
                <button class="btn quiet" onclick={keep} disabled={busy}>Keep anyway</button>
              {:else}
                <button class="btn ghost big" onclick={retry}
                  ><Icon name="redo" size={18} /> Try again</button
                >
                <button class="btn primary big" onclick={keep} disabled={busy}>
                  <Icon name="check" size={18} /> Keep and continue
                </button>
              {/if}
            </div>
          </section>
        {:else}
          <button
            class="record"
            data-state={phase}
            onclick={() => (phase === 'recording' ? stopRecording() : startRecording())}
            disabled={phase === 'starting' || phase === 'checking'}
            aria-label={phase === 'recording' ? 'Stop recording' : 'Start recording'}
          >
            <span class="ring" aria-hidden="true"></span>
            <Icon name={phase === 'recording' ? 'stop' : 'mic'} size={38} />
          </button>
          <p class="status" aria-live="polite">
            {#if phase === 'ready'}
              Press <kbd>Space</kbd> or the button, take a breath, then read the sentence.
            {:else if phase === 'starting'}
              Getting ready…
            {:else if phase === 'recording'}
              Listening. Press <kbd>Space</kbd> when you've finished.
            {:else if phase === 'checking'}
              Checking the recording…
            {/if}
          </p>
          <div class="meter-wrap"><LevelMeter {level} active={phase === 'recording'} /></div>
        {/if}
      </div>
    {/if}
  </main>

  {#if phase === 'ready' || phase === 'review'}
    <footer class="keys muted small" aria-label="Keyboard shortcuts">
      <span><kbd>Space</kbd> record / stop</span>
      <span><kbd>Enter</kbd> keep</span>
      <span><kbd>R</kbd> try again</span>
      <span><kbd>L</kbd> listen</span>
      <span><kbd>S</kbd> skip</span>
      <button class="btn quiet" onclick={skip}
        ><Icon name="skip" size={16} /> Skip this sentence</button
      >
    </footer>
  {/if}
</div>

<style>
  .studio {
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    background: radial-gradient(ellipse at 50% 0%, var(--bg-tint), var(--bg) 70%);
  }
  .top {
    display: grid;
    grid-template-columns: 1fr minmax(8rem, 22rem) 1fr;
    align-items: center;
    gap: 1.5rem;
    padding: 1rem 1.5rem;
  }
  .top > .row:last-child {
    justify-content: flex-end;
  }
  .session-bar {
    height: 6px;
    border-radius: 999px;
    background: var(--surface-2);
    overflow: hidden;
  }
  .session-bar div {
    height: 100%;
    background: var(--primary);
    border-radius: 999px;
    transition: width calc(var(--speed) * 3) ease-out;
  }
  .stage {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 2rem;
    padding: 1rem 1.5rem 2rem;
  }
  .prompt-card {
    width: min(56rem, 100%);
    padding: 2.5rem 3rem;
    text-align: center;
  }
  .prompt {
    font-size: 2.2rem;
    line-height: 1.35;
    font-weight: 700;
    letter-spacing: -0.01em;
    margin: 0;
    text-wrap: balance;
    transition: opacity var(--speed);
  }
  .prompt.dim {
    opacity: 0.55;
  }
  .controls {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 1rem;
    width: min(44rem, 100%);
  }
  .record {
    position: relative;
    width: 108px;
    height: 108px;
    border-radius: 50%;
    border: 0;
    background: var(--primary);
    color: var(--on-primary);
    display: grid;
    place-items: center;
    cursor: pointer;
    box-shadow: var(--shadow-lift);
    transition:
      transform var(--speed),
      background var(--speed);
  }
  .record:hover:not(:disabled) {
    transform: scale(1.04);
  }
  .record[data-state='recording'] {
    background: var(--redo);
  }
  .record:disabled {
    opacity: 0.7;
    cursor: wait;
  }
  .ring {
    position: absolute;
    inset: -10px;
    border-radius: 50%;
    border: 3px solid var(--redo);
    opacity: 0;
  }
  .record[data-state='recording'] .ring {
    animation: breathe 2.4s ease-in-out infinite;
  }
  @keyframes breathe {
    0%,
    100% {
      opacity: 0.15;
      transform: scale(0.96);
    }
    50% {
      opacity: 0.6;
      transform: scale(1.06);
    }
  }
  :global(:root[data-reduce-motion='true']) .ring {
    animation: none !important;
    opacity: 0.6 !important;
  }
  @media (prefers-reduced-motion: reduce) {
    .record[data-state='recording'] .ring {
      animation: none;
      opacity: 0.6;
    }
  }
  .status {
    min-height: 1.6em;
    text-align: center;
    color: var(--muted);
    margin: 0;
  }
  .meter-wrap {
    width: min(26rem, 100%);
  }
  .verdict {
    width: 100%;
    background: var(--surface);
    border-radius: var(--radius);
    box-shadow: var(--shadow);
    padding: 1.4rem 1.6rem;
    border-left: 6px solid var(--good);
  }
  .verdict[data-verdict='okay'] {
    border-left-color: var(--okay);
  }
  .verdict[data-verdict='redo'] {
    border-left-color: var(--redo);
  }
  .verdict-head {
    display: flex;
    gap: 0.9rem;
    align-items: flex-start;
  }
  .verdict h2 {
    margin: 0.1rem 0 0.2rem;
  }
  .dot {
    display: grid;
    place-items: center;
    width: 2.2rem;
    height: 2.2rem;
    border-radius: 50%;
    flex: none;
    background: var(--good-soft);
    color: var(--good);
  }
  [data-verdict='okay'] .dot {
    background: var(--okay-soft);
    color: var(--okay);
  }
  [data-verdict='redo'] .dot {
    background: var(--redo-soft);
    color: var(--redo);
  }
  .notes {
    margin: 0.5rem 0 0 3.1rem;
    padding: 0;
    list-style: none;
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
  }
  .actions {
    margin-top: 1.1rem;
  }
  .center {
    justify-content: center;
  }
  .pause,
  .summary {
    width: min(40rem, 100%);
    text-align: center;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.6rem;
    padding: 2.5rem 2rem;
    color: var(--primary-strong);
  }
  .pause h1,
  .summary h1 {
    color: var(--text);
  }
  .pause .lede,
  .summary .lede {
    margin-bottom: 1rem;
  }
  .milestone {
    display: flex;
    gap: 0.9rem;
    text-align: left;
    align-items: flex-start;
    background: var(--accent-soft);
    color: var(--text);
    border-radius: var(--radius-sm);
    padding: 1rem 1.2rem;
    margin-bottom: 0.75rem;
  }
  .milestone :global(svg) {
    color: var(--accent);
    flex: none;
  }
  .milestone p {
    margin: 0.2rem 0 0;
  }
  .keys {
    display: flex;
    gap: 1.25rem;
    justify-content: center;
    align-items: center;
    flex-wrap: wrap;
    padding: 0 1.5rem 1.25rem;
  }
  @media (max-width: 760px) {
    .top {
      grid-template-columns: 1fr;
    }
    .prompt-card {
      padding: 1.5rem;
    }
    .prompt {
      font-size: 1.6rem;
    }
  }
</style>
