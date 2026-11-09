<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { api, errorMessage, onLevel } from '../lib/api';
  import Icon from '../lib/components/Icon.svelte';
  import LevelMeter from '../lib/components/LevelMeter.svelte';
  import { ROOM_TEXT } from '../lib/feedback';
  import { app } from '../lib/state.svelte';
  import type { InputDevice, Level, RoomCheck } from '../lib/types';

  let step = $state(0);
  let name = $state('');
  let language = $state('en-US');
  let gender = $state<string>('');
  let devices = $state<InputDevice[]>([]);
  let device = $state<string>('');
  let level = $state<Level | null>(null);
  let testing = $state(false);
  let room = $state<RoomCheck | null>(null);
  let checking = $state(false);
  let busy = $state(false);
  let unlisten: (() => void) | null = null;

  onMount(async () => {
    // If setup was interrupted after the voice bank was created, carry on from the microphone.
    const existing = app.overview?.bank?.speaker;
    if (existing) {
      name = existing.name;
      language = existing.language;
      gender = existing.gender ?? '';
      step = 2;
    }
    unlisten = await onLevel((l) => (level = l));
    try {
      devices = await api.listDevices();
      device = app.settings?.inputDevice ?? devices.find((d) => d.isDefault)?.id ?? '';
    } catch (e) {
      app.notify(errorMessage(e), 'error');
    }
  });

  onDestroy(() => {
    unlisten?.();
    if (testing) void api.cancelRecording();
  });

  async function createBank() {
    busy = true;
    try {
      app.overview = await api.createBank({ name, language, gender: gender || null });
      step = 2;
    } catch (e) {
      app.notify(errorMessage(e), 'error');
    } finally {
      busy = false;
    }
  }

  async function chooseDevice(id: string) {
    device = id;
    await app.updateSettings({ inputDevice: id || null });
  }

  async function toggleTest() {
    if (testing) {
      testing = false;
      await api.cancelRecording();
      level = null;
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
    room = null;
    try {
      room = await api.checkRoom();
    } catch (e) {
      app.notify(errorMessage(e), 'error');
    } finally {
      checking = false;
    }
  }

  async function finish() {
    await app.updateSettings({ onboarded: true });
    await app.refresh();
    app.go('today');
  }

  const steps = ['Welcome', 'About you', 'Microphone', 'Room', 'Ready'];
</script>

<div class="welcome">
  <ol class="steps" aria-label="Setup steps">
    {#each steps as label, i (label)}
      <li
        class:done={i < step}
        class:current={i === step}
        aria-current={i === step ? 'step' : undefined}
      >
        <span class="num">{i + 1}</span><span class="label">{label}</span>
      </li>
    {/each}
  </ol>

  <div class="card panel fade-in">
    {#if step === 0}
      <div class="hero-icon"><Icon name="heart" size={44} /></div>
      <h1>Bank your voice, in your own time.</h1>
      <p class="lede">
        Vocalkeep is a quiet place to record your voice. A few sentences at a time, whenever you
        feel up to it. Later, those recordings become a computer voice that sounds like you, for
        your communication app.
      </p>
      <ul class="points">
        <li><Icon name="leaf" size={20} /> Short, gentle sessions. Stop whenever you like.</li>
        <li><Icon name="check" size={20} /> Each recording is checked, with friendly tips.</li>
        <li><Icon name="messages" size={20} /> Record messages for the people you love, too.</li>
        <li>
          <Icon name="computer" size={20} /> Everything stays on this computer. No account, no cloud.
        </li>
      </ul>
      <div class="row end">
        <button class="btn primary big" onclick={() => (step = 1)}>Let's begin</button>
      </div>
    {:else if step === 1}
      <h1>Whose voice are we keeping?</h1>
      <p class="lede">This names your voice bank and, later, your voice.</p>
      <div class="stack form">
        <label class="field">
          Your name
          <input
            type="text"
            bind:value={name}
            autocomplete="name"
            placeholder="For example, Jane"
          />
        </label>
        <label class="field">
          The English you speak
          <select bind:value={language}>
            <option value="en-US">English (United States)</option>
            <option value="en-GB">English (United Kingdom)</option>
          </select>
          <span class="hint">More languages can be added to Vocalkeep in future.</span>
        </label>
        <fieldset class="field-set">
          <legend
            >How should system voice lists describe your voice? <span class="hint">(optional)</span
            ></legend
          >
          <div class="segmented">
            {#each [['', 'Skip'], ['female', 'Female'], ['male', 'Male'], ['neutral', 'Neutral']] as [value, label] (value)}
              <button
                type="button"
                aria-pressed={gender === value}
                onclick={() => (gender = value!)}>{label}</button
              >
            {/each}
          </div>
        </fieldset>
      </div>
      <div class="row end">
        <button class="btn quiet" onclick={() => (step = 0)}>Back</button>
        <button class="btn primary big" onclick={createBank} disabled={busy}>Continue</button>
      </div>
    {:else if step === 2}
      <h1>Choose your microphone</h1>
      <p class="lede">
        A headset or desk microphone works well. Use the same one every time, so your voice sounds
        the same in every recording.
      </p>
      <div class="stack form">
        <label class="field">
          Microphone
          <select value={device} onchange={(e) => chooseDevice(e.currentTarget.value)}>
            <option value="">The computer's default microphone</option>
            {#each devices as d (d.id)}
              <option value={d.id}>{d.name}{d.isDefault ? ' (default)' : ''}</option>
            {/each}
          </select>
        </label>
        <div class="card soft">
          <p>
            <strong>Try it:</strong> press Test and say “Hello, this is my voice.” The bar should sit
            in the shaded middle.
          </p>
          <LevelMeter {level} active={testing} />
          <div class="row" style="margin-top: 0.8rem">
            <button class="btn ghost" onclick={toggleTest}>
              <Icon name={testing ? 'stop' : 'mic'} size={18} />
              {testing ? 'Stop test' : 'Test'}
            </button>
          </div>
        </div>
      </div>
      <div class="row end">
        <button class="btn quiet" onclick={() => (step = 1)}>Back</button>
        <button
          class="btn primary big"
          onclick={() => {
            if (testing) void toggleTest();
            step = 3;
          }}>Continue</button
        >
      </div>
    {:else if step === 3}
      <h1>Let's listen to the room</h1>
      <p class="lede">
        Stay quiet for four seconds while Vocalkeep listens to the background. Fans, fridges and
        traffic all sneak into recordings.
      </p>
      <div class="room card soft">
        {#if checking}
          <p class="big-status">Listening… <span class="muted">stay quiet for a moment.</span></p>
          <LevelMeter {level} active />
        {:else if room}
          <div class="room-result" data-level={room.level}>
            <h2>{ROOM_TEXT[room.level].title}</h2>
            <p>{ROOM_TEXT[room.level].body}</p>
            <p class="muted small">Background level: {room.noiseFloorDbfs.toFixed(0)} dBFS</p>
          </div>
        {:else}
          <p>When you're ready, press the button and stay quiet.</p>
        {/if}
        <button class="btn ghost" onclick={checkRoom} disabled={checking}>
          <Icon name="mic" size={18} />
          {room ? 'Check again' : 'Check the room'}
        </button>
      </div>
      <div class="row end">
        <button class="btn quiet" onclick={() => (step = 2)}>Back</button>
        <button class="btn primary big" onclick={() => (step = 4)} disabled={checking}>
          {room ? 'Continue' : 'Skip for now'}
        </button>
      </div>
    {:else}
      <div class="hero-icon"><Icon name="sparkle" size={44} /></div>
      <h1>You're ready.</h1>
      <p class="lede">A few things that help:</p>
      <ul class="points">
        <li><Icon name="water" size={20} /> Keep water nearby and rest when you need to.</li>
        <li>
          <Icon name="mic" size={20} /> Same microphone, same spot, similar distance each time.
        </li>
        <li>
          <Icon name="heart" size={20} /> Read in your everyday voice. It doesn't need to be perfect.
        </li>
        <li><Icon name="leaf" size={20} /> Ten minutes most days beats an hour once a week.</li>
      </ul>
      <div class="row end">
        <button class="btn primary big" onclick={finish}>Go to today</button>
      </div>
    {/if}
  </div>
</div>

<style>
  .welcome {
    max-width: 46rem;
    margin: 0 auto;
    padding: 2.5rem 1.5rem 4rem;
    display: flex;
    flex-direction: column;
    gap: 1.5rem;
  }
  .steps {
    list-style: none;
    padding: 0;
    margin: 0;
    display: flex;
    gap: 0.4rem;
    flex-wrap: wrap;
  }
  .steps li {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    padding: 0.25rem 0.7rem 0.25rem 0.3rem;
    border-radius: 999px;
    color: var(--faint);
    font-size: 0.85rem;
    font-weight: 700;
  }
  .steps li.current {
    background: var(--surface);
    color: var(--text);
    box-shadow: var(--shadow);
  }
  .steps li.done {
    color: var(--primary-strong);
  }
  .num {
    display: grid;
    place-items: center;
    width: 1.6rem;
    height: 1.6rem;
    border-radius: 50%;
    background: var(--surface-2);
    font-size: 0.8rem;
  }
  .current .num {
    background: var(--primary);
    color: var(--on-primary);
  }
  .panel {
    padding: 2.2rem 2.4rem;
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }
  .hero-icon {
    color: var(--accent);
  }
  .points {
    list-style: none;
    padding: 0;
    margin: 0.5rem 0 1rem;
    display: flex;
    flex-direction: column;
    gap: 0.7rem;
  }
  .points li {
    display: flex;
    gap: 0.75rem;
    align-items: flex-start;
  }
  .points :global(svg) {
    color: var(--primary);
    flex: none;
    margin-top: 0.15rem;
  }
  .form {
    margin: 0.75rem 0 1.25rem;
  }
  .field-set {
    border: 0;
    padding: 0;
    margin: 0;
  }
  .field-set legend {
    font-weight: 700;
    font-size: 0.95rem;
    margin-bottom: 0.4rem;
  }
  .hint {
    font-weight: 400;
    color: var(--muted);
  }
  .end {
    justify-content: flex-end;
    margin-top: 0.5rem;
  }
  .room {
    display: flex;
    flex-direction: column;
    gap: 0.8rem;
    align-items: flex-start;
    margin: 0.5rem 0 1rem;
  }
  .room-result h2 {
    color: var(--good);
  }
  .room-result[data-level='noisy'] h2 {
    color: var(--okay);
  }
  .room-result[data-level='too-noisy'] h2 {
    color: var(--redo);
  }
  .big-status {
    font-size: 1.15rem;
    font-weight: 700;
  }
</style>
