<script lang="ts">
  import { app } from '../state.svelte';
  import Icon from './Icon.svelte';
</script>

<div class="region" aria-live="polite" role="status">
  {#if app.toast}
    {#key app.toast.id}
      <div class="toast fade-in" data-kind={app.toast.kind}>
        <Icon
          name={app.toast.kind === 'error'
            ? 'warn'
            : app.toast.kind === 'success'
              ? 'check'
              : 'info'}
        />
        <span>{app.toast.message}</span>
        <button class="btn quiet icon" aria-label="Dismiss" onclick={() => (app.toast = null)}>
          <Icon name="close" size={18} />
        </button>
      </div>
    {/key}
  {/if}
</div>

<style>
  .region {
    position: fixed;
    bottom: 1.25rem;
    left: 50%;
    transform: translateX(-50%);
    z-index: 50;
    width: min(36rem, calc(100vw - 2rem));
  }
  .toast {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 0.6rem 0.6rem 0.6rem 1rem;
    border-radius: var(--radius-sm);
    background: var(--text);
    color: var(--bg);
    box-shadow: var(--shadow-lift);
  }
  .toast span {
    flex: 1;
  }
  .toast[data-kind='error'] {
    background: var(--redo);
    color: #fff;
  }
  .toast .btn {
    color: inherit;
    min-height: 2.25rem;
    min-width: 2.25rem;
  }
</style>
