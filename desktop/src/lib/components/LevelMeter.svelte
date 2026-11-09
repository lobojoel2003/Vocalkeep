<script lang="ts">
  import { untrack } from 'svelte';
  import { levelZone, meterFraction } from '../feedback';
  import type { Level } from '../types';

  let { level, active = true }: { level: Level | null; active?: boolean } = $props();

  // Smooth the bar so it breathes rather than flickers.
  let shown = $state(0);
  let peak = $state(0);
  $effect(() => {
    const target = active && level ? meterFraction(level.rmsDbfs + 6) : 0;
    const p = active && level ? meterFraction(level.peakDbfs) : 0;
    untrack(() => {
      shown = target > shown ? shown * 0.35 + target * 0.65 : shown * 0.8 + target * 0.2;
      peak = Math.max(p, peak * 0.94);
    });
  });
  const zone = $derived(level && active ? levelZone(level.rmsDbfs, level.clipping) : 'quiet');
  const words = $derived(
    !active || !level
      ? 'Microphone level'
      : zone === 'loud'
        ? 'Too loud'
        : zone === 'quiet'
          ? 'Quiet'
          : 'Good level',
  );
</script>

<div
  class="meter"
  data-zone={zone}
  role="meter"
  aria-label={words}
  aria-valuemin={0}
  aria-valuemax={100}
  aria-valuenow={Math.round(shown * 100)}
  aria-valuetext={words}
>
  <div class="track">
    <div class="target" aria-hidden="true"></div>
    <div class="fill" style:width="{shown * 100}%"></div>
    <div class="peak" style:left="{peak * 100}%" aria-hidden="true"></div>
  </div>
  <div class="labels" aria-hidden="true">
    <span>Quiet</span><span>Just right</span><span>Loud</span>
  </div>
</div>

<style>
  .meter {
    width: 100%;
  }
  .track {
    position: relative;
    height: 14px;
    border-radius: 999px;
    background: var(--surface);
    box-shadow: inset 0 0 0 1px var(--border);
    overflow: hidden;
  }
  /* The comfortable speaking range, about -30 to -12 dBFS. */
  .target {
    position: absolute;
    left: 50%;
    width: 30%;
    top: 0;
    bottom: 0;
    background: var(--primary-soft);
  }
  .fill {
    position: absolute;
    left: 0;
    top: 0;
    bottom: 0;
    border-radius: 999px;
    background: var(--primary);
    transition: width 60ms linear;
  }
  [data-zone='quiet'] .fill {
    background: var(--faint);
  }
  [data-zone='loud'] .fill {
    background: var(--redo);
  }
  .peak {
    position: absolute;
    top: 2px;
    bottom: 2px;
    width: 3px;
    border-radius: 2px;
    background: var(--text);
    opacity: 0.35;
    transform: translateX(-50%);
  }
  .labels {
    display: flex;
    justify-content: space-between;
    font-size: 0.75rem;
    color: var(--faint);
    margin-top: 0.3rem;
  }
  :global(:root[data-theme='contrast']) .track {
    border: 1px solid var(--border);
  }
</style>
