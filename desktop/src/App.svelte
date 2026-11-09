<script lang="ts">
  import { onMount } from 'svelte';
  import Sidebar from './lib/components/Sidebar.svelte';
  import Toast from './lib/components/Toast.svelte';
  import { app } from './lib/state.svelte';
  import Messages from './views/Messages.svelte';
  import MyVoice from './views/MyVoice.svelte';
  import Phrases from './views/Phrases.svelte';
  import ProgressView from './views/ProgressView.svelte';
  import SettingsView from './views/SettingsView.svelte';
  import Studio from './views/Studio.svelte';
  import Today from './views/Today.svelte';
  import Welcome from './views/Welcome.svelte';

  onMount(() => {
    void app.init();
  });

  // Theme, text size and motion live on <html> so every component can use them.
  $effect(() => {
    const root = document.documentElement;
    root.dataset.theme = app.settings?.theme ?? 'system';
    root.dataset.textSize = app.settings?.textSize ?? 'normal';
    root.dataset.reduceMotion = String(app.settings?.reduceMotion ?? false);
  });

  const onboarding = $derived(
    app.ready && !!app.settings && (!app.settings.onboarded || !app.hasBank),
  );
</script>

{#if !app.ready}
  <div class="loading" aria-busy="true">Opening your voice bank…</div>
{:else if app.loadError}
  <div class="loading">
    <h1>Vocalkeep couldn't start</h1>
    <p>{app.loadError}</p>
  </div>
{:else if onboarding}
  <Welcome />
{:else if app.session}
  <Studio session={app.session} />
{:else}
  <div class="shell">
    <Sidebar />
    <main class="content">
      {#key app.view}
        <div class="fade-in">
          {#if app.view === 'today'}
            <Today />
          {:else if app.view === 'progress'}
            <ProgressView />
          {:else if app.view === 'phrases'}
            <Phrases />
          {:else if app.view === 'messages'}
            <Messages />
          {:else if app.view === 'voice'}
            <MyVoice />
          {:else if app.view === 'settings'}
            <SettingsView />
          {/if}
        </div>
      {/key}
    </main>
  </div>
{/if}

<Toast />

<style>
  .shell {
    display: grid;
    grid-template-columns: 15.5rem 1fr;
    min-height: 100vh;
  }
  .content {
    padding: 2.25rem clamp(1.25rem, 4vw, 3.5rem) 4rem;
    max-width: 72rem;
    width: 100%;
  }
  .loading {
    min-height: 100vh;
    display: grid;
    place-content: center;
    text-align: center;
    color: var(--muted);
    padding: 2rem;
  }
  @media (max-width: 760px) {
    .shell {
      grid-template-columns: 1fr;
    }
  }
</style>
