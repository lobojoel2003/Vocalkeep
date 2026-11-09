<script lang="ts">
  import type { Snippet } from 'svelte';

  let {
    open = $bindable(false),
    title,
    children,
    actions,
    onclose,
  }: {
    open?: boolean;
    title: string;
    children: Snippet;
    actions?: Snippet;
    onclose?: () => void;
  } = $props();

  let dialog = $state<HTMLDialogElement | null>(null);

  $effect(() => {
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  });
</script>

<dialog
  bind:this={dialog}
  aria-labelledby="dialog-title"
  onclose={() => {
    open = false;
    onclose?.();
  }}
>
  <h2 id="dialog-title">{title}</h2>
  <div class="body">{@render children()}</div>
  {#if actions}<div class="actions">{@render actions()}</div>{/if}
</dialog>

<style>
  dialog {
    border: 0;
    border-radius: var(--radius);
    padding: 1.6rem 1.75rem;
    width: min(34rem, calc(100vw - 2rem));
    background: var(--surface);
    color: var(--text);
    box-shadow: var(--shadow-lift);
  }
  :global(:root[data-theme='contrast']) dialog {
    border: 2px solid var(--border);
  }
  dialog::backdrop {
    background: rgba(18, 24, 25, 0.45);
  }
  .body {
    display: flex;
    flex-direction: column;
    gap: 0.9rem;
    margin: 0.75rem 0 1.25rem;
  }
  .actions {
    display: flex;
    justify-content: flex-end;
    gap: 0.6rem;
    flex-wrap: wrap;
  }
</style>
