<script lang="ts">
  import { api, errorMessage } from '../lib/api';
  import Icon from '../lib/components/Icon.svelte';
  import VoiceShape from '../lib/components/VoiceShape.svelte';
  import { ENERGY_TEXT, ROOM_TEXT } from '../lib/feedback';
  import { greeting, minutesText, plural, relativeDay } from '../lib/format';
  import { milestoneTitle, progressLine } from '../lib/milestones';
  import { app } from '../lib/state.svelte';
  import type { Energy } from '../lib/types';

  const energies: Energy[] = ['strong', 'okay', 'tired'];
  let starting = $state<Energy | null>(null);

  const p = $derived(app.overview?.progress ?? null);
  const bank = $derived(app.overview?.bank ?? null);
  const complete = $derived(app.overview?.milestones.at(-1)?.at ?? 1500);
  const roomStale = $derived.by(() => {
    const at = bank?.room?.checkedAt;
    if (!at) return true;
    return Date.now() - new Date(at).getTime() > 1000 * 60 * 60 * 24 * 30;
  });

  async function start(energy: Energy) {
    starting = energy;
    try {
      app.session = await api.startSession(energy);
    } catch (e) {
      app.notify(errorMessage(e), 'error');
    } finally {
      starting = null;
    }
  }

  function describe(energy: Energy): string {
    const len = app.settings?.sessions[energy];
    if (!len) return ENERGY_TEXT[energy].body;
    return `About ${minutesText(len.minutes)}, up to ${plural(len.prompts, 'sentence')}.`;
  }
</script>

<section class="today">
  <header class="hero">
    <div class="intro">
      <div class="eyebrow">
        {new Date().toLocaleDateString('en', { weekday: 'long', day: 'numeric', month: 'long' })}
      </div>
      <h1>{greeting(bank?.speaker.name ?? '')}.</h1>
      {#if p}
        <p class="lede">{progressLine(p)}</p>
        {#if p.lastSessionAt}
          <p class="muted small">Last session {relativeDay(p.lastSessionAt)}.</p>
        {/if}
      {/if}
    </div>
    {#if p}
      <button class="shape-link" onclick={() => app.go('progress')} aria-label="See your progress">
        <VoiceShape
          kept={p.kept}
          {complete}
          size={250}
          label={p.kept.toLocaleString('en')}
          caption={milestoneTitle(p.milestone)}
        />
      </button>
    {/if}
  </header>

  <section class="card checkin" aria-labelledby="checkin-title">
    <h2 id="checkin-title">How does your voice feel today?</h2>
    <p class="muted">
      Pick one and Vocalkeep will size the session to suit. You can stop any time.
    </p>
    <div class="energies">
      {#each energies as energy (energy)}
        <button
          class="energy"
          data-energy={energy}
          onclick={() => start(energy)}
          disabled={starting !== null}
        >
          <span class="energy-title">{ENERGY_TEXT[energy].title}</span>
          <span class="energy-body">{ENERGY_TEXT[energy].body}</span>
          <span class="energy-len">{describe(energy)}</span>
          <span class="go"
            >{starting === energy ? 'Starting…' : 'Start'} <Icon name="mic" size={18} /></span
          >
        </button>
      {/each}
    </div>
  </section>

  <div class="grid">
    <button class="card tile" onclick={() => app.go('messages')}>
      <Icon name="messages" size={28} />
      <h3>Record a message</h3>
      <p class="muted">
        A birthday wish, advice or “I love you”, kept exactly as you say it.
        {#if p && p.legacyMessages > 0}You have {plural(p.legacyMessages, 'message')}.{/if}
      </p>
    </button>
    <button class="card tile" onclick={() => app.go('phrases')}>
      <Icon name="phrases" size={28} />
      <h3>Add your own phrases</h3>
      <p class="muted">Names of family and pets, places and sayings, so your voice can say them.</p>
    </button>
    {#if roomStale}
      <button class="card tile" onclick={() => app.go('settings')}>
        <Icon name="mic" size={28} />
        <h3>{bank?.room ? 'Check the room again' : 'Check your room'}</h3>
        <p class="muted">
          {#if bank?.room}
            Last result: {ROOM_TEXT[bank.room.level].title.toLowerCase()}. Rooms change; a quick
            check helps.
          {:else}
            Four seconds of quiet tells you whether the room is right for recording.
          {/if}
        </p>
      </button>
    {:else}
      <button class="card tile" onclick={() => app.go('voice')}>
        <Icon name="voice" size={28} />
        <h3>My voice</h3>
        <p class="muted">See when your voice is ready to build, and where you can use it.</p>
      </button>
    {/if}
  </div>
</section>

<style>
  .today {
    display: flex;
    flex-direction: column;
    gap: 1.75rem;
  }
  .hero {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 2rem;
    flex-wrap: wrap;
  }
  .intro {
    flex: 1 1 22rem;
  }
  .intro h1 {
    font-size: 2.3rem;
  }
  .shape-link {
    border: 0;
    background: none;
    padding: 0;
    cursor: pointer;
    border-radius: 50%;
    color: inherit;
    font: inherit;
  }
  .energies {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(13rem, 1fr));
    gap: 1rem;
    margin-top: 1rem;
  }
  .energy {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 0.3rem;
    text-align: left;
    padding: 1.2rem 1.3rem;
    border-radius: var(--radius);
    border: 2px solid var(--border);
    background: var(--surface);
    color: var(--text);
    font: inherit;
    cursor: pointer;
    transition:
      border-color var(--speed),
      transform var(--speed),
      box-shadow var(--speed);
  }
  .energy:hover:not(:disabled) {
    border-color: var(--primary);
    box-shadow: var(--shadow-lift);
    transform: translateY(-2px);
  }
  .energy:disabled {
    opacity: 0.6;
  }
  .energy-title {
    font-size: 1.3rem;
    font-weight: 700;
  }
  .energy-body {
    color: var(--muted);
  }
  .energy-len {
    font-size: 0.85rem;
    color: var(--faint);
  }
  .go {
    margin-top: 0.6rem;
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    font-weight: 700;
    color: var(--primary-strong);
  }
  [data-energy='tired'] .go {
    color: var(--accent);
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(15rem, 1fr));
    gap: 1rem;
  }
  .tile {
    border: 0;
    text-align: left;
    font: inherit;
    color: inherit;
    cursor: pointer;
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
    transition:
      transform var(--speed),
      box-shadow var(--speed);
  }
  .tile :global(svg) {
    color: var(--primary);
  }
  .tile:hover {
    transform: translateY(-2px);
    box-shadow: var(--shadow-lift);
  }
  .tile h3 {
    margin: 0.4rem 0 0;
  }
  .tile p {
    margin: 0;
  }
</style>
