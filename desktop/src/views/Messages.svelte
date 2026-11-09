<script lang="ts">
  import { open as openDialog } from '@tauri-apps/plugin-dialog';
  import { onDestroy, onMount } from 'svelte';
  import { api, errorMessage, onLevel } from '../lib/api';
  import { playWav, stopPlayback } from '../lib/audio';
  import Dialog from '../lib/components/Dialog.svelte';
  import Icon from '../lib/components/Icon.svelte';
  import LevelMeter from '../lib/components/LevelMeter.svelte';
  import { topIssues } from '../lib/feedback';
  import { clock, dateText, plural } from '../lib/format';
  import { app } from '../lib/state.svelte';
  import type { LegacyDetails, LegacyMessage, Level, PendingTake } from '../lib/types';

  const OCCASIONS = [
    'Just because',
    'Birthday',
    'Wedding day',
    'Graduation',
    'A new baby',
    'Advice for later',
    'A story',
    'Comfort',
    'Holidays',
  ];

  let messages = $state<LegacyMessage[]>([]);
  let mode = $state<'list' | 'recording' | 'details'>('list');
  let level = $state<Level | null>(null);
  let pending = $state<PendingTake | null>(null);
  let details = $state<LegacyDetails>(blank());
  let editing = $state<LegacyMessage | null>(null);
  let editOpen = $state(false);
  let confirmDelete = $state<LegacyMessage | null>(null);
  let deleteOpen = $state(false);
  let playing = $state<string | null>(null);
  let busy = $state(false);
  let unlisten: (() => void) | null = null;

  function describe(m: LegacyMessage): string {
    return [
      m.recipient && `For ${m.recipient}`,
      m.occasion,
      m.recordedBy && `recorded by ${m.recordedBy}`,
    ]
      .filter(Boolean)
      .join(' · ');
  }

  function blank(): LegacyDetails {
    return {
      title: '',
      recipient: '',
      occasion: 'Just because',
      recordedBy: app.overview?.bank?.speaker.name ?? '',
      note: '',
    };
  }

  onMount(async () => {
    unlisten = await onLevel((l) => (level = l));
    await load();
  });

  onDestroy(() => {
    unlisten?.();
    stopPlayback();
    if (mode === 'recording') void api.cancelRecording();
  });

  async function load() {
    try {
      messages = await api.listLegacy();
    } catch (e) {
      app.notify(errorMessage(e), 'error');
    }
  }

  async function startRecording() {
    stopPlayback();
    level = null;
    try {
      await api.startRecording('legacy');
      mode = 'recording';
    } catch (e) {
      app.notify(errorMessage(e), 'error');
    }
  }

  async function stopRecording() {
    busy = true;
    try {
      pending = await api.stopRecording('legacy', null);
      details = blank();
      mode = 'details';
    } catch (e) {
      app.notify(errorMessage(e), 'error');
      mode = 'list';
    } finally {
      busy = false;
    }
  }

  async function cancelRecording() {
    await api.cancelRecording();
    mode = 'list';
  }

  async function discardPending() {
    stopPlayback();
    if (pending) await api.discardTake(pending.token, null, false).catch(() => {});
    pending = null;
    mode = 'list';
  }

  async function save(e: SubmitEvent) {
    e.preventDefault();
    if (!pending) return;
    busy = true;
    stopPlayback();
    try {
      await api.saveLegacy(pending.token, details);
      pending = null;
      mode = 'list';
      app.notify('Message saved.', 'success');
      await Promise.all([load(), app.refresh()]);
    } catch (err) {
      app.notify(errorMessage(err), 'error');
    } finally {
      busy = false;
    }
  }

  async function playMessage(id: string) {
    if (playing === id) {
      stopPlayback();
      playing = null;
      return;
    }
    playing = id;
    try {
      await playWav(
        id === 'pending' && pending
          ? await api.pendingAudio(pending.token)
          : await api.legacyAudio(id),
      );
    } catch (e) {
      app.notify(errorMessage(e), 'error');
    } finally {
      if (playing === id) playing = null;
    }
  }

  function startEdit(m: LegacyMessage) {
    editing = { ...m };
    editOpen = true;
  }

  async function saveEdit() {
    if (!editing) return;
    try {
      const { title, recipient, occasion, recordedBy, note } = editing;
      await api.updateLegacy(editing.id, { title, recipient, occasion, recordedBy, note });
      editOpen = false;
      await load();
    } catch (e) {
      app.notify(errorMessage(e), 'error');
    }
  }

  async function doDelete() {
    if (!confirmDelete) return;
    try {
      await api.deleteLegacy(confirmDelete.id);
      deleteOpen = false;
      await Promise.all([load(), app.refresh()]);
    } catch (e) {
      app.notify(errorMessage(e), 'error');
    }
  }

  async function exportAll() {
    const dir = await openDialog({ directory: true, title: 'Choose where to save the messages' });
    if (typeof dir !== 'string') return;
    busy = true;
    try {
      const summary = await api.exportLegacy(dir);
      app.notify(`Saved ${plural(summary.files, 'message')} to ${summary.path}`, 'success');
    } catch (e) {
      app.notify(errorMessage(e), 'error');
    } finally {
      busy = false;
    }
  }
</script>

<section class="messages">
  <div class="spread">
    <div>
      <div class="eyebrow">Messages</div>
      <h1>Messages to keep</h1>
    </div>
    {#if mode === 'list' && messages.length > 0}
      <button class="btn ghost" onclick={exportAll} disabled={busy}>
        <Icon name="download" size={18} /> Save all to a folder
      </button>
    {/if}
  </div>
  <p class="lede">
    Some things should be heard exactly as you say them: a birthday wish, advice for a wedding day,
    a story, “I love you”. Messages are kept as they are, never turned into a computer voice. Family
    members can record messages here too.
  </p>

  {#if mode === 'recording'}
    <div class="card recorder fade-in" aria-live="polite">
      <div class="rec-dot" aria-hidden="true"></div>
      <h2>Recording</h2>
      <p class="clock">{clock(level?.elapsedMs ?? 0)}</p>
      <div class="meter"><LevelMeter {level} /></div>
      {#if level?.limitReached}
        <p class="muted">That's the 15-minute limit for one message. Press Stop to keep it.</p>
      {:else}
        <p class="muted">Take your time. Pauses are fine.</p>
      {/if}
      <div class="row center">
        <button class="btn primary big" onclick={stopRecording} disabled={busy}>
          <Icon name="stop" size={18} /> Stop
        </button>
        <button class="btn quiet" onclick={cancelRecording}>Cancel</button>
      </div>
    </div>
  {:else if mode === 'details' && pending}
    <form class="card stack fade-in" onsubmit={save}>
      <div class="spread">
        <h2>About this message</h2>
        <button type="button" class="btn ghost" onclick={() => playMessage('pending')}>
          <Icon name={playing === 'pending' ? 'stop' : 'play'} size={16} />
          {playing === 'pending' ? 'Stop' : `Listen (${clock(pending.durationMs)})`}
        </button>
      </div>
      {#each topIssues(pending.analysis) as note (note.title)}
        <p class="note">
          <Icon name="info" size={18} /> <span><strong>{note.title}.</strong> {note.tip}</span>
        </p>
      {/each}
      <div class="form-grid">
        <label class="field">
          Title
          <input
            type="text"
            bind:value={details.title}
            placeholder="Happy 18th birthday"
            required
          />
        </label>
        <label class="field">
          For
          <input type="text" bind:value={details.recipient} placeholder="Mia" />
        </label>
        <label class="field">
          Occasion
          <select bind:value={details.occasion}>
            {#each OCCASIONS as o (o)}<option>{o}</option>{/each}
          </select>
        </label>
        <label class="field">
          Recorded by
          <input type="text" bind:value={details.recordedBy} />
        </label>
      </div>
      <label class="field">
        Note <span class="hint">Optional: when to play it, or what it's about.</span>
        <textarea bind:value={details.note} rows="3"></textarea>
      </label>
      <div class="row">
        <button class="btn primary" type="submit" disabled={busy}
          ><Icon name="check" size={18} /> Save message</button
        >
        <button class="btn ghost" type="button" onclick={startRecording}
          ><Icon name="redo" size={18} /> Record again</button
        >
        <button class="btn quiet" type="button" onclick={discardPending}>Discard</button>
      </div>
    </form>
  {:else}
    <button class="card new" onclick={startRecording}>
      <span class="mic"><Icon name="mic" size={30} /></span>
      <span>
        <strong>Record a new message</strong>
        <span class="muted">Up to 15 minutes. You'll name it afterwards.</span>
      </span>
    </button>
  {/if}

  {#if messages.length}
    <ul class="list">
      {#each messages as m (m.id)}
        <li class="card item">
          <button
            class="play"
            onclick={() => playMessage(m.id)}
            aria-label={playing === m.id ? 'Stop' : `Play “${m.title}”`}
          >
            <Icon name={playing === m.id ? 'stop' : 'play'} size={20} />
          </button>
          <div class="info">
            <h3>{m.title}</h3>
            <p class="muted small">{describe(m)}</p>
            {#if m.note}<p class="small">{m.note}</p>{/if}
          </div>
          <div class="meta muted small">
            <span>{clock(m.durationMs)}</span>
            <span>{dateText(m.recordedAt)}</span>
          </div>
          <div class="row">
            <button
              class="btn icon quiet"
              onclick={() => startEdit(m)}
              aria-label={`Edit “${m.title}”`}><Icon name="edit" size={18} /></button
            >
            <button
              class="btn icon quiet"
              onclick={() => {
                confirmDelete = m;
                deleteOpen = true;
              }}
              aria-label={`Delete “${m.title}”`}><Icon name="trash" size={18} /></button
            >
          </div>
        </li>
      {/each}
    </ul>
  {:else if mode === 'list'}
    <p class="muted">Your messages will appear here.</p>
  {/if}
</section>

<Dialog bind:open={editOpen} title="Edit message">
  {#if editing}
    <label class="field">Title <input type="text" bind:value={editing.title} /></label>
    <label class="field">For <input type="text" bind:value={editing.recipient} /></label>
    <label class="field">
      Occasion
      <select bind:value={editing.occasion}>
        {#each [...new Set([editing.occasion, ...OCCASIONS])] as o (o)}<option>{o}</option>{/each}
      </select>
    </label>
    <label class="field">Recorded by <input type="text" bind:value={editing.recordedBy} /></label>
    <label class="field">Note <textarea bind:value={editing.note} rows="3"></textarea></label>
  {/if}
  {#snippet actions()}
    <button class="btn quiet" onclick={() => (editOpen = false)}>Cancel</button>
    <button class="btn primary" onclick={saveEdit}>Save</button>
  {/snippet}
</Dialog>

<Dialog bind:open={deleteOpen} title="Delete this message?">
  <p>“{confirmDelete?.title}” will be deleted from this computer. This can't be undone.</p>
  {#snippet actions()}
    <button class="btn quiet" onclick={() => (deleteOpen = false)}>Keep it</button>
    <button class="btn danger" onclick={doDelete}>Delete</button>
  {/snippet}
</Dialog>

<style>
  .messages {
    display: flex;
    flex-direction: column;
    gap: 1rem;
  }
  .new {
    display: flex;
    align-items: center;
    gap: 1.1rem;
    border: 2px dashed var(--border);
    box-shadow: none;
    font: inherit;
    color: inherit;
    text-align: left;
    cursor: pointer;
    transition: border-color var(--speed);
  }
  .new:hover {
    border-color: var(--primary);
  }
  .new > span:last-child {
    display: flex;
    flex-direction: column;
  }
  .mic {
    display: grid;
    place-items: center;
    width: 3.6rem;
    height: 3.6rem;
    border-radius: 50%;
    background: var(--primary);
    color: var(--on-primary);
    flex: none;
  }
  .recorder {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.5rem;
    text-align: center;
    padding: 2rem;
  }
  .rec-dot {
    width: 14px;
    height: 14px;
    border-radius: 50%;
    background: var(--redo);
    animation: blink 1.6s ease-in-out infinite;
  }
  @keyframes blink {
    50% {
      opacity: 0.3;
    }
  }
  .clock {
    font-size: 2.4rem;
    font-weight: 700;
    font-variant-numeric: tabular-nums;
    margin: 0;
  }
  .meter {
    width: min(26rem, 100%);
  }
  .center {
    justify-content: center;
  }
  .form-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 1rem;
  }
  .note {
    display: flex;
    gap: 0.5rem;
    background: var(--okay-soft);
    padding: 0.6rem 0.8rem;
    border-radius: var(--radius-sm);
    margin: 0;
  }
  .list {
    list-style: none;
    margin: 0.5rem 0 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
  }
  .item {
    display: flex;
    align-items: center;
    gap: 1rem;
    padding: 1rem 1.2rem;
  }
  .play {
    display: grid;
    place-items: center;
    width: 3rem;
    height: 3rem;
    border-radius: 50%;
    border: 0;
    background: var(--primary-soft);
    color: var(--primary-strong);
    cursor: pointer;
    flex: none;
  }
  .info {
    flex: 1;
    min-width: 0;
  }
  .info h3 {
    margin: 0;
  }
  .info p {
    margin: 0.1rem 0 0;
  }
  .meta {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    white-space: nowrap;
  }
  @media (max-width: 760px) {
    .form-grid {
      grid-template-columns: 1fr;
    }
    .meta {
      display: none;
    }
  }
</style>
