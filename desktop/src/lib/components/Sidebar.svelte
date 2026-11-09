<script lang="ts">
  import { app } from '../state.svelte';
  import type { View } from '../types';
  import Icon, { type IconName } from './Icon.svelte';

  const items: { view: View; label: string; icon: IconName }[] = [
    { view: 'today', label: 'Today', icon: 'today' },
    { view: 'progress', label: 'Progress', icon: 'progress' },
    { view: 'phrases', label: 'Your phrases', icon: 'phrases' },
    { view: 'messages', label: 'Messages', icon: 'messages' },
    { view: 'voice', label: 'My voice', icon: 'voice' },
    { view: 'settings', label: 'Settings', icon: 'settings' },
  ];
</script>

<nav class="sidebar" aria-label="Main">
  <div class="brand">
    <svg viewBox="0 0 1024 1024" width="36" height="36" aria-hidden="true">
      <rect x="64" y="64" width="896" height="896" rx="216" fill="var(--primary)" />
      <path
        d="M 282 540 A 230 230 0 0 0 742 540"
        fill="none"
        stroke="var(--accent)"
        stroke-width="64"
        stroke-linecap="round"
      />
      <g fill="var(--on-primary)">
        <rect x="326" y="410" width="52" height="120" rx="26" />
        <rect x="406" y="350" width="52" height="240" rx="26" />
        <rect x="486" y="290" width="52" height="360" rx="26" />
        <rect x="566" y="350" width="52" height="240" rx="26" />
        <rect x="646" y="410" width="52" height="120" rx="26" />
      </g>
    </svg>
    <span class="name">Vocalkeep</span>
  </div>
  <ul>
    {#each items as item (item.view)}
      <li>
        <button
          class:active={app.view === item.view}
          aria-current={app.view === item.view ? 'page' : undefined}
          onclick={() => app.go(item.view)}
        >
          <Icon name={item.icon} />
          <span>{item.label}</span>
        </button>
      </li>
    {/each}
  </ul>
  <p class="privacy">
    <Icon name="leaf" size={16} />
    <span>Your recordings stay on this computer.</span>
  </p>
</nav>

<style>
  .sidebar {
    display: flex;
    flex-direction: column;
    gap: 1.25rem;
    padding: 1.4rem 1rem;
    height: 100vh;
    position: sticky;
    top: 0;
    background: var(--bg-tint);
    border-right: 1px solid var(--border);
  }
  .brand {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    padding: 0 0.5rem;
  }
  .name {
    font-weight: 700;
    font-size: 1.2rem;
    letter-spacing: -0.01em;
  }
  ul {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
  }
  button {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    width: 100%;
    min-height: 2.9rem;
    padding: 0.55rem 0.85rem;
    border: 0;
    border-radius: 14px;
    background: transparent;
    color: var(--muted);
    font: inherit;
    font-weight: 700;
    text-align: left;
    cursor: pointer;
    transition:
      background var(--speed),
      color var(--speed);
  }
  button:hover {
    background: var(--surface-2);
    color: var(--text);
  }
  button.active {
    background: var(--surface);
    color: var(--primary-strong);
    box-shadow: var(--shadow);
  }
  :global(:root[data-theme='contrast']) button.active {
    background: var(--primary);
    color: var(--on-primary);
  }
  .privacy {
    margin-top: auto;
    display: flex;
    gap: 0.5rem;
    align-items: flex-start;
    font-size: 0.8rem;
    color: var(--muted);
    padding: 0 0.5rem;
  }
  @media (max-width: 760px) {
    .sidebar {
      height: auto;
      position: static;
      flex-direction: row;
      align-items: center;
      padding: 0.5rem;
      border-right: 0;
      border-bottom: 1px solid var(--border);
      overflow-x: auto;
    }
    .name,
    .privacy,
    button span {
      display: none;
    }
    ul {
      flex-direction: row;
    }
  }
</style>
