<script lang="ts">
  import { open as openDialog, save as saveDialog } from '@tauri-apps/plugin-dialog';
  import { openUrl } from '@tauri-apps/plugin-opener';
  import { onDestroy, onMount } from 'svelte';
  import { api, errorMessage, onLevel } from '../lib/api';
  import Dialog from '../lib/components/Dialog.svelte';
  import Icon from '../lib/components/Icon.svelte';
  import LevelMeter from '../lib/components/LevelMeter.svelte';
  import { ENERGY_TEXT, ROOM_TEXT } from '../lib/feedback';
  import { bytesText, dateText, plural } from '../lib/format';
  import { app } from '../lib/state.svelte';
  import type {
    Energy,
    InputDevice,
    Level,
    PipelineStatus,
    Settings,
    TextSize,
    Theme,
  } from '../lib/types';

  let devices = $state<InputDevice[]>([]);
  let level = $state<Level | null>(null);
  let testing = $state(false);
  let checking = $state(false);
  let pipeline = $state<PipelineStatus | null>(null);
  let pipelineCommand = $state(app.settings?.pipelineCommand ?? '');
  let name = $state(app.overview?.bank?.speaker.name ?? '');
  let busy = $state(false);
  let restoreOpen = $state(false);
  let unlisten: (() => void) | null = null;

  const s = $derived(app.settings as Settings);
  const bank = $derived(app.overview?.bank ?? null);
  const info = $derived(app.info);
  const sets = $derived(app.overview?.sets ?? []);

  const themes: [Theme, string][] = [
    ['system', 'Match computer'],
    ['light', 'Light'],
    ['dark', 'Dark'],
    ['contrast', 'High contrast'],
  ];
  const sizes: [TextSize, string][] = [
    ['normal', 'Normal'],
    ['large', 'Large'],
    ['larger', 'Larger'],
    ['largest', 'Largest'],
  ];
  const energies: Energy[] = ['strong', 'okay', 'tired'];

  onMount(async () => {
    unlisten = await onLevel((l) => (level = l));
    try {
      devices = await api.listDevices();
    } catch (e) {
      app.notify(errorMessage(e), 'error');
    }
    pipeline = await api.pipelineStatus().catch(() => null);
  });
  onDestroy(() => {
    unlisten?.();
    if (testing) void api.cancelRecording();
  });

  async function toggleTest() {
    if (testing) {
      testing = false;
      await api.cancelRecording();
      return;
    }
    try {
      await api.startRecording('take');
      testing = true;
    } catch (e) {
      app.notify(errorMessage(e), 'error');
    }
  }

  async function checkRoom() {
    if (testing) await toggleTest();
    checking = true;
    try {
      const room = await api.checkRoom();
      app.notify(`${ROOM_TEXT[room.level].title}. ${ROOM_TEXT[room.level].body}`, 'success');
      await app.refresh();
    } catch (e) {
      app.notify(errorMessage(e), 'error');
    } finally {
      checking = false;
    }
  }

  function setLength(energy: Energy, key: 'minutes' | 'prompts', value: number) {
    if (!Number.isFinite(value) || value < 1) return;
    void app.updateSettings({
      sessions: { ...s.sessions, [energy]: { ...s.sessions[energy], [key]: Math.round(value) } },
    });
  }

  function toggleSet(id: string, on: boolean) {
    const all = sets.map((x) => x.id).concat('personal');
    const current = s.enabledSets.length ? s.enabledSets : all;
    const next = on ? [...new Set([...current, id])] : current.filter((x) => x !== id);
    if (next.length === 0) {
      app.notify('Keep at least one set of sentences switched on.', 'error');
      return;
    }
    void app.updateSettings({ enabledSets: next.length === all.length ? [] : next });
  }

  function setEnabled(id: string): boolean {
    return s.enabledSets.length === 0 || s.enabledSets.includes(id);
  }

  async function saveName() {
    if (!bank) return;
    try {
      app.overview = await api.updateSpeaker({ ...bank.speaker, name });
      app.notify('Saved.', 'success');
    } catch (e) {
      app.notify(errorMessage(e), 'error');
    }
  }

  async function backup() {
    const path = await saveDialog({
      title: 'Back up your voice bank',
      defaultPath: `${(bank?.speaker.name || 'My').replace(/[^\w -]/g, '')} voice bank.zip`,
      filters: [{ name: 'Zip archive', extensions: ['zip'] }],
    });
    if (!path) return;
    busy = true;
    try {
      const r = await api.exportBackup(path);
      app.notify(`Saved ${plural(r.files, 'file')} (${bytesText(r.bytes)}).`, 'success');
    } catch (e) {
      app.notify(errorMessage(e), 'error');
    } finally {
      busy = false;
    }
  }

  async function chooseBankFolder() {
    const dir = await openDialog({ directory: true, title: 'Choose a folder for your voice bank' });
    if (typeof dir === 'string') await app.updateSettings({ bankDir: dir });
  }

  async function restore() {
    restoreOpen = false;
    const path = await openDialog({
      title: 'Choose a voice bank backup',
      filters: [{ name: 'Zip archive', extensions: ['zip'] }],
    });
    if (typeof path !== 'string') return;
    busy = true;
    try {
      app.overview = await api.restoreBackup(path);
      app.notify('Your voice bank is restored.', 'success');
    } catch (e) {
      app.notify(errorMessage(e), 'error');
    } finally {
      busy = false;
    }
  }

  async function savePipelineCommand() {
    await app.updateSettings({ pipelineCommand: pipelineCommand.trim() || null });
    pipeline = await api.pipelineStatus().catch(() => null);
  }
</script>

{#if s}
  <section class="settings">
    <div class="eyebrow">Settings</div>
    <h1>Settings</h1>

    <div class="card stack">
      <h2>Display</h2>
      <div class="setting">
        <span class="label">Theme</span>
        <div class="segmented" role="group" aria-label="Theme">
          {#each themes as [value, label] (value)}
            <button
              aria-pressed={s.theme === value}
              onclick={() => app.updateSettings({ theme: value })}>{label}</button
            >
          {/each}
        </div>
      </div>
      <div class="setting">
        <span class="label">Text size</span>
        <div class="segmented" role="group" aria-label="Text size">
          {#each sizes as [value, label] (value)}
            <button
              aria-pressed={s.textSize === value}
              onclick={() => app.updateSettings({ textSize: value })}>{label}</button
            >
          {/each}
        </div>
      </div>
      <label class="check">
        <input
          type="checkbox"
          checked={s.reduceMotion}
          onchange={(e) => app.updateSettings({ reduceMotion: e.currentTarget.checked })}
        />
        <span>Reduce motion <span class="muted small">(no pulsing or sliding)</span></span>
      </label>
    </div>

    <div class="card stack">
      <h2>Microphone and room</h2>
      <label class="field">
        Microphone
        <select
          value={s.inputDevice ?? ''}
          onchange={(e) => app.updateSettings({ inputDevice: e.currentTarget.value || null })}
        >
          <option value="">The computer's default microphone</option>
          {#each devices as d (d.id)}<option value={d.id}
              >{d.name}{d.isDefault ? ' (default)' : ''}</option
            >{/each}
        </select>
      </label>
      <LevelMeter {level} active={testing || checking} />
      <div class="row">
        <button class="btn ghost" onclick={toggleTest} disabled={checking}>
          <Icon name={testing ? 'stop' : 'mic'} size={18} />
          {testing ? 'Stop test' : 'Test microphone'}
        </button>
        <button class="btn ghost" onclick={checkRoom} disabled={checking}>
          {checking ? 'Listening… stay quiet' : 'Check the room'}
        </button>
        {#if bank?.room}
          <span class="muted small"
            >Last check: {ROOM_TEXT[bank.room.level].title.toLowerCase()} ({dateText(
              bank.room.checkedAt,
            )})</span
          >
        {/if}
      </div>
    </div>

    <div class="card stack">
      <h2>Sessions</h2>
      <p class="muted">
        How long a session lasts for each answer to “How does your voice feel today?”
      </p>
      <div class="lengths">
        {#each energies as energy (energy)}
          <div class="length">
            <strong>{ENERGY_TEXT[energy].title}</strong>
            <label class="field small"
              >Minutes
              <input
                type="number"
                min="1"
                max="90"
                value={s.sessions[energy].minutes}
                onchange={(e) => setLength(energy, 'minutes', e.currentTarget.valueAsNumber)}
              />
            </label>
            <label class="field small"
              >Sentences
              <input
                type="number"
                min="1"
                max="200"
                value={s.sessions[energy].prompts}
                onchange={(e) => setLength(energy, 'prompts', e.currentTarget.valueAsNumber)}
              />
            </label>
          </div>
        {/each}
      </div>
      <label class="field">
        Suggest a sip of water every
        <select
          value={String(s.breakEvery)}
          onchange={(e) => app.updateSettings({ breakEvery: Number(e.currentTarget.value) })}
        >
          <option value="0">Never</option>
          {#each [5, 10, 15, 20] as n (n)}<option value={String(n)}>{n} sentences</option>{/each}
        </select>
      </label>
      <label class="check">
        <input
          type="checkbox"
          checked={s.autoPlay}
          onchange={(e) => app.updateSettings({ autoPlay: e.currentTarget.checked })}
        />
        <span>Play each recording back straight away</span>
      </label>
      <label class="check">
        <input
          type="checkbox"
          checked={s.autoKeepGood}
          onchange={(e) => app.updateSettings({ autoKeepGood: e.currentTarget.checked })}
        />
        <span>Keep recordings that pass every check and move on without a click</span>
      </label>
    </div>

    <div class="card stack">
      <h2>Sentences</h2>
      {#each sets as set (set.id)}
        <label class="check">
          <input
            type="checkbox"
            checked={setEnabled(set.id)}
            onchange={(e) => toggleSet(set.id, e.currentTarget.checked)}
          />
          <span>
            <strong>{set.title}</strong>
            <span class="muted small">({set.count.toLocaleString('en')})</span><br />
            <span class="muted small">{set.description}</span><br />
            <span class="faint small"
              >{set.source}. Licence: {set.license}.{#if set.attribution}
                {set.attribution}{/if}</span
            >
          </span>
        </label>
      {/each}
      <label class="check">
        <input
          type="checkbox"
          checked={setEnabled('personal')}
          onchange={(e) => toggleSet('personal', e.currentTarget.checked)}
        />
        <span
          ><strong>Your own phrases</strong><br /><span class="muted small"
            >The phrases you add yourself.</span
          ></span
        >
      </label>
    </div>

    <div class="card stack">
      <h2>Voice bank</h2>
      {#if bank}
        <div class="row name-row">
          <label class="field grow"
            >Name on your voice <input type="text" bind:value={name} /></label
          >
          <button class="btn ghost" onclick={saveName} disabled={name === bank.speaker.name}
            >Save</button
          >
        </div>
      {/if}
      <p class="muted small">Stored in <code>{bank?.path ?? info?.bankDir}</code></p>
      <div class="row">
        <button class="btn ghost" onclick={backup} disabled={busy || !bank}
          ><Icon name="download" size={18} /> Back up…</button
        >
        <button class="btn ghost" onclick={() => (restoreOpen = true)} disabled={busy}
          ><Icon name="upload" size={18} /> Restore a backup…</button
        >
        <button class="btn ghost" onclick={() => api.openFolder('bank')}
          ><Icon name="folder" size={18} /> Open folder</button
        >
        <button class="btn quiet" onclick={chooseBankFolder}>Use a different folder…</button>
      </div>
      <p class="muted small">
        Back up after each week of recording, to a USB stick or another computer. Your voice bank is
        irreplaceable.
      </p>
    </div>

    <div class="card stack">
      <h2>Voice builder</h2>
      {#if pipeline?.found}
        <p>
          <span class="pill good"><Icon name="check" size={14} /> Found</span>
          {pipeline.command}
          {pipeline.version ? `(${pipeline.version})` : ''}
        </p>
      {:else}
        <p class="muted">
          Not found. Vocalkeep looks for the <code>vocalkeep</code> command. If you installed it somewhere
          else, enter its full path.
        </p>
      {/if}
      <div class="row name-row">
        <label class="field grow"
          >Command
          <input
            type="text"
            bind:value={pipelineCommand}
            placeholder="vocalkeep"
            spellcheck="false"
          />
        </label>
        <button class="btn ghost" onclick={savePipelineCommand}>Save and check</button>
      </div>
    </div>

    <div class="card stack about">
      <h2>About Vocalkeep</h2>
      {#if info}
        <p>
          Version <strong>{info.version}</strong> · build {info.buildNumber} · {info.gitSha}
          · {info.buildDate}
        </p>
      {/if}
      <p class="muted">
        Free software under the GNU General Public License, version 3 or later. Voices are built
        with <a
          href="https://github.com/OHF-Voice/piper1-gpl"
          onclick={(e) => {
            e.preventDefault();
            void openUrl('https://github.com/OHF-Voice/piper1-gpl');
          }}>Piper</a
        >. Sound-rich sentences are from CMU ARCTIC (Carnegie Mellon University). The typeface is
        Atkinson Hyperlegible Next from the Braille Institute.
      </p>
      <div class="row">
        <button
          class="btn ghost"
          onclick={() => openUrl('https://github.com/lobojoel2003/Vocalkeep')}>Project page</button
        >
        <button
          class="btn ghost"
          onclick={() => openUrl('https://github.com/lobojoel2003/Vocalkeep/issues')}
          >Report a problem</button
        >
      </div>
    </div>
  </section>
{/if}

<Dialog bind:open={restoreOpen} title="Restore a backup">
  <p>
    A backup can only be restored into an empty voice bank folder, so nothing is ever overwritten.
    If you already have recordings here, first choose a different (empty) folder above.
  </p>
  {#snippet actions()}
    <button class="btn quiet" onclick={() => (restoreOpen = false)}>Cancel</button>
    <button class="btn primary" onclick={restore}>Choose backup…</button>
  {/snippet}
</Dialog>

<style>
  .settings {
    display: flex;
    flex-direction: column;
    gap: 1.25rem;
    max-width: 52rem;
  }
  .setting {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
    flex-wrap: wrap;
  }
  .label {
    font-weight: 700;
  }
  .lengths {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 1rem;
  }
  .length {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    background: var(--surface-2);
    border-radius: var(--radius-sm);
    padding: 0.9rem 1rem;
  }
  .name-row {
    align-items: flex-end;
  }
  .grow {
    flex: 1;
  }
  .faint {
    color: var(--faint);
  }
  code {
    word-break: break-all;
  }
  @media (max-width: 760px) {
    .lengths {
      grid-template-columns: 1fr;
    }
  }
</style>
