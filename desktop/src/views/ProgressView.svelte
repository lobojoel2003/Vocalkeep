<script lang="ts">
  import { onMount } from 'svelte';
  import { api, errorMessage } from '../lib/api';
  import { playWav, stopPlayback } from '../lib/audio';
  import Icon from '../lib/components/Icon.svelte';
  import VoiceShape from '../lib/components/VoiceShape.svelte';
  import { issueText } from '../lib/feedback';
  import { minutesText, percent, plural, relativeDay } from '../lib/format';
  import { MILESTONE_TEXT, milestoneTitle } from '../lib/milestones';
  import { app } from '../lib/state.svelte';
  import type { TakeSummary } from '../lib/types';

  const p = $derived(app.overview?.progress ?? null);
  const milestones = $derived(app.overview?.milestones ?? []);
  const complete = $derived(milestones.at(-1)?.at ?? 1500);
  let recent = $state<TakeSummary[]>([]);
  let playing = $state<string | null>(null);

  onMount(async () => {
    try {
      recent = await api.recentTakes(12);
    } catch (e) {
      app.notify(errorMessage(e), 'error');
    }
  });

  async function play(id: string) {
    if (playing === id) {
      stopPlayback();
      playing = null;
      return;
    }
    playing = id;
    try {
      await playWav(await api.takeAudio(id));
    } catch (e) {
      app.notify(errorMessage(e), 'error');
    } finally {
      if (playing === id) playing = null;
    }
  }

  async function remove(t: TakeSummary) {
    try {
      const progress = await api.deleteTake(t.promptId);
      if (app.overview) app.overview.progress = progress;
      recent = recent.filter((r) => r.promptId !== t.promptId);
      app.notify('Removed. That sentence will come round again in a later session.');
    } catch (e) {
      app.notify(errorMessage(e), 'error');
    }
  }

  const maxDay = $derived(Math.max(1, ...(p?.recentDays.map((d) => d.kept) ?? [1])));
</script>

{#if p}
  <section class="progress-view">
    <header class="head">
      <div>
        <div class="eyebrow">Progress</div>
        <h1>Your voice is taking shape</h1>
        <p class="lede">
          Each sentence you keep fills in a little more. There are no streaks and no deadlines: rest
          days are good days.
        </p>
      </div>
    </header>

    <div class="top">
      <div class="card shape-card">
        <VoiceShape
          kept={p.kept}
          {complete}
          size={340}
          count={150}
          label={p.kept.toLocaleString('en')}
          caption={`${p.kept === 1 ? 'sentence' : 'sentences'} kept`}
        />
        <p class="muted center">
          {[
            `${minutesText(p.speechMinutes)} of your voice`,
            p.needsRedo > 0 ? `${plural(p.needsRedo, 'take')} worth another try` : '',
          ]
            .filter(Boolean)
            .join(' · ')}
        </p>
      </div>

      <div class="card ladder" aria-labelledby="ladder-title">
        <h2 id="ladder-title">Milestones</h2>
        <ol>
          {#each milestones as m (m.id)}
            {@const reached = p.kept >= m.at}
            {@const isNext = p.nextMilestone?.id === m.id}
            <li class:reached class:next={isNext}>
              <span class="mark" aria-hidden="true"
                >{#if reached}<Icon name="check" size={16} />{/if}</span
              >
              <div class="m-body">
                <div class="spread">
                  <strong>{MILESTONE_TEXT[m.id]?.title ?? m.id}</strong>
                  <span class="muted small">{m.at.toLocaleString('en')}</span>
                </div>
                <span class="muted small">{MILESTONE_TEXT[m.id]?.body}</span>
                {#if isNext}
                  <div
                    class="bar"
                    role="progressbar"
                    aria-valuenow={Math.round(p.toNext * 100)}
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-label={`Progress to ${milestoneTitle(m)}`}
                  >
                    <div style:width={percent(p.toNext)}></div>
                  </div>
                {/if}
              </div>
            </li>
          {/each}
        </ol>
      </div>
    </div>

    <div class="stats">
      <div class="card stat">
        <span class="value">{p.phonemesCovered}<span class="of"> / {p.phonemesTotal}</span></span>
        <span class="label">speech sounds recorded</span>
      </div>
      <div class="card stat">
        <span class="value"
          >{p.diphonesCovered.toLocaleString('en')}<span class="of">
            / {p.diphonesTotal.toLocaleString('en')}</span
          ></span
        >
        <span class="label">sound pairs, for smooth joins</span>
      </div>
      <div class="card stat">
        <span class="value">{p.sessions}</span>
        <span class="label"
          >{p.sessions === 1 ? 'session' : 'sessions'} over {plural(p.daysRecorded, 'day')}</span
        >
      </div>
      <div class="card stat">
        <span class="value">{p.legacyMessages}</span>
        <span class="label">{p.legacyMessages === 1 ? 'message' : 'messages'} kept for family</span>
      </div>
    </div>

    <div class="bottom">
      <div class="card">
        <h2>Sentence sets</h2>
        <div class="sets">
          {#each p.sets as s (s.id)}
            <div class="set">
              <div class="spread">
                <strong>{s.title}</strong>
                <span class="muted small"
                  >{s.recorded.toLocaleString('en')} of {s.total.toLocaleString('en')}</span
                >
              </div>
              <div class="bar">
                <div style:width={percent(s.recorded / Math.max(1, s.total))}></div>
              </div>
            </div>
          {/each}
        </div>
      </div>

      <div class="card">
        <h2>Last two weeks</h2>
        {#if p.recentDays.length === 0}
          <p class="muted">Your sessions will show here.</p>
        {:else}
          <div
            class="chart"
            role="img"
            aria-label={`Sentences kept on each of the last ${p.recentDays.length} days you recorded`}
          >
            {#each p.recentDays as d (d.date)}
              <div class="col" title={`${d.date}: ${d.kept}`}>
                <div class="col-bar" style:height="{(d.kept / maxDay) * 100}%"></div>
                <span class="col-label"
                  >{new Date(d.date + 'T12:00').toLocaleDateString('en', {
                    day: 'numeric',
                    month: 'short',
                  })}</span
                >
              </div>
            {/each}
          </div>
        {/if}
      </div>
    </div>

    {#if recent.length}
      <div class="card">
        <h2>Recent recordings</h2>
        <ul class="takes">
          {#each recent as t (t.promptId)}
            <li>
              <button
                class="btn icon ghost"
                onclick={() => play(t.promptId)}
                aria-label={playing === t.promptId ? 'Stop' : `Play “${t.text}”`}
              >
                <Icon name={playing === t.promptId ? 'stop' : 'play'} size={16} />
              </button>
              <div class="take-text">
                <span>{t.text}</span>
                <span class="muted small">
                  {[
                    relativeDay(t.recordedAt),
                    t.issues.length ? issueText(t.issues[0]!).title.toLowerCase() : '',
                  ]
                    .filter(Boolean)
                    .join(' · ')}
                </span>
              </div>
              <span class="pill {t.verdict}">{t.verdict === 'redo' ? 'try again' : t.verdict}</span>
              <button
                class="btn icon quiet"
                onclick={() => remove(t)}
                aria-label={`Remove “${t.text}” and record it again later`}
              >
                <Icon name="trash" size={16} />
              </button>
            </li>
          {/each}
        </ul>
      </div>
    {/if}
  </section>
{/if}

<style>
  .progress-view {
    display: flex;
    flex-direction: column;
    gap: 1.5rem;
  }
  .top {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 1.5rem;
    align-items: start;
  }
  .shape-card {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.75rem;
  }
  .center {
    text-align: center;
    margin: 0;
  }
  .ladder ol {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 0.9rem;
  }
  .ladder li {
    display: flex;
    gap: 0.8rem;
    align-items: flex-start;
    opacity: 0.6;
  }
  .ladder li.reached,
  .ladder li.next {
    opacity: 1;
  }
  .mark {
    flex: none;
    display: grid;
    place-items: center;
    width: 1.6rem;
    height: 1.6rem;
    border-radius: 50%;
    border: 2px solid var(--border);
    margin-top: 0.1rem;
  }
  .reached .mark {
    background: var(--primary);
    border-color: var(--primary);
    color: var(--on-primary);
  }
  .next .mark {
    border-color: var(--accent);
  }
  .m-body {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
  }
  .bar {
    height: 8px;
    border-radius: 999px;
    background: var(--surface-2);
    overflow: hidden;
    margin-top: 0.35rem;
  }
  .bar div {
    height: 100%;
    background: linear-gradient(90deg, var(--primary), var(--accent));
    border-radius: 999px;
  }
  .stats {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(12rem, 1fr));
    gap: 1rem;
  }
  .stat {
    display: flex;
    flex-direction: column;
    gap: 0.2rem;
  }
  .value {
    font-size: 1.9rem;
    font-weight: 700;
    letter-spacing: -0.02em;
  }
  .of {
    font-size: 1rem;
    color: var(--faint);
    font-weight: 400;
  }
  .label {
    color: var(--muted);
    font-size: 0.9rem;
  }
  .bottom {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 1.5rem;
  }
  .sets {
    display: flex;
    flex-direction: column;
    gap: 0.9rem;
  }
  .chart {
    display: flex;
    align-items: flex-end;
    gap: 0.5rem;
    height: 10rem;
    padding-top: 0.5rem;
  }
  .col {
    flex: 1;
    height: 100%;
    display: flex;
    flex-direction: column;
    justify-content: flex-end;
    align-items: center;
    gap: 0.3rem;
    min-width: 0;
  }
  .col-bar {
    width: 100%;
    max-width: 2.2rem;
    min-height: 4px;
    border-radius: 8px 8px 3px 3px;
    background: var(--primary);
    opacity: 0.85;
  }
  .col-label {
    font-size: 0.7rem;
    color: var(--faint);
    white-space: nowrap;
  }
  .takes {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
  }
  .takes li {
    display: flex;
    align-items: center;
    gap: 0.8rem;
    padding: 0.6rem 0;
    border-bottom: 1px solid var(--border);
  }
  .takes li:last-child {
    border-bottom: 0;
  }
  .take-text {
    flex: 1;
    display: flex;
    flex-direction: column;
    min-width: 0;
  }
  @media (max-width: 980px) {
    .top,
    .bottom {
      grid-template-columns: 1fr;
    }
  }
</style>
