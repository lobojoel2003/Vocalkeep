<script lang="ts">
  import { onMount } from 'svelte';
  import { api, errorMessage } from '../lib/api';
  import Icon from '../lib/components/Icon.svelte';
  import { plural } from '../lib/format';
  import { app } from '../lib/state.svelte';
  import type { CustomPrompt } from '../lib/types';

  let phrases = $state<CustomPrompt[]>([]);
  let text = $state('');
  let busy = $state(false);
  const placeholder = 'Hello, Priya, how was school?\nBiscuit, come here, good boy!';

  const ideas = [
    'The names of your family, friends and pets',
    'Places: your street, town, favourite café',
    'Things you always say: “Bless you, love”, “Right then!”',
    'Words for your hobbies, work or faith',
    'How you answer the phone',
  ];

  onMount(load);

  async function load() {
    try {
      phrases = await api.listCustomPrompts();
    } catch (e) {
      app.notify(errorMessage(e), 'error');
    }
  }

  async function add(e: SubmitEvent) {
    e.preventDefault();
    const lines = text
      .split('\n')
      .map((l) => l.trim())
      .filter(Boolean);
    if (!lines.length) return;
    busy = true;
    let added = 0;
    for (const line of lines) {
      try {
        await api.addCustomPrompt(line);
        added += 1;
      } catch (err) {
        app.notify(`“${line}”: ${errorMessage(err)}`, 'error');
      }
    }
    busy = false;
    if (added) {
      text = '';
      app.notify(
        `Added ${plural(added, 'phrase')}. They'll be mixed into your sessions.`,
        'success',
      );
      await Promise.all([load(), app.refresh()]);
    }
  }

  async function remove(p: CustomPrompt) {
    try {
      await api.removeCustomPrompt(p.id);
      phrases = phrases.filter((x) => x.id !== p.id);
      await app.refresh();
    } catch (e) {
      app.notify(errorMessage(e), 'error');
    }
  }
</script>

<section class="phrases">
  <div class="eyebrow">Your phrases</div>
  <h1>Words that are yours</h1>
  <p class="lede">
    Ready-made sentences can't know your grandchildren's names or how you say “cheerio”. Add them
    here. They're mixed into your sessions, so your voice learns to say them, and each recording is
    kept just as you said it.
  </p>

  <div class="layout">
    <form class="card stack" onsubmit={add}>
      <label class="field">
        Add phrases
        <span class="hint">One per line. Write them the way you say them.</span>
        <textarea bind:value={text} rows="5" {placeholder}></textarea>
      </label>
      <div class="row">
        <button class="btn primary" type="submit" disabled={busy || !text.trim()}>
          <Icon name="plus" size={18} /> Add
        </button>
      </div>
    </form>
    <aside class="card soft ideas">
      <h3>Ideas</h3>
      <ul>
        {#each ideas as idea (idea)}<li>{idea}</li>{/each}
      </ul>
    </aside>
  </div>

  <div class="card">
    <div class="spread">
      <h2>{plural(phrases.length, 'phrase')}</h2>
      {#if phrases.length}
        <span class="muted small">{phrases.filter((p) => p.recorded).length} recorded</span>
      {/if}
    </div>
    {#if phrases.length === 0}
      <p class="muted">Nothing here yet. Phrases you add will appear here.</p>
    {:else}
      <ul class="list">
        {#each phrases as p (p.id)}
          <li>
            <span class="text">{p.text}</span>
            {#if p.recorded}
              <span class="pill good"><Icon name="check" size={14} /> Recorded</span>
            {:else}
              <span class="pill">Not yet</span>
            {/if}
            <button
              class="btn icon quiet"
              onclick={() => remove(p)}
              aria-label={`Remove “${p.text}”`}
            >
              <Icon name="trash" size={16} />
            </button>
          </li>
        {/each}
      </ul>
    {/if}
  </div>
</section>

<style>
  .phrases {
    display: flex;
    flex-direction: column;
    gap: 1rem;
  }
  .layout {
    display: grid;
    grid-template-columns: 1.4fr 1fr;
    gap: 1.25rem;
    margin-top: 0.5rem;
  }
  .ideas ul {
    margin: 0;
    padding-left: 1.2rem;
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
    color: var(--muted);
  }
  .list {
    list-style: none;
    margin: 0.5rem 0 0;
    padding: 0;
  }
  .list li {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 0.55rem 0;
    border-bottom: 1px solid var(--border);
  }
  .list li:last-child {
    border-bottom: 0;
  }
  .text {
    flex: 1;
  }
  @media (max-width: 860px) {
    .layout {
      grid-template-columns: 1fr;
    }
  }
</style>
