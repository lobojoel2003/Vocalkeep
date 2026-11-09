<script lang="ts">
  import { growth, shapeFraction, spokeLine, spokes } from '../shape';

  let {
    kept,
    complete,
    size = 320,
    count = 120,
    label = '',
    caption = '',
  }: {
    kept: number;
    complete: number;
    size?: number;
    count?: number;
    label?: string;
    caption?: string;
  } = $props();

  // Spokes that grew in with the most recent ~6% of the bank are shown in the accent colour.
  const RECENT = 0.06;

  const all = $derived(spokes(count));
  const fraction = $derived(shapeFraction(kept, complete));
  const c = $derived(size / 2);
  const inner = $derived(size * 0.29);
  const outer = $derived(size * 0.49);
  const stroke = $derived(Math.max(2, ((Math.PI * 2 * inner) / count) * 0.5));
  const lines = $derived(
    all.map((s, i) => {
      const g = growth(s.threshold, fraction);
      return {
        i,
        ghost: spokeLine(s, c, inner, outer, 1),
        grown: g > 0 ? spokeLine(s, c, inner, outer, g) : null,
        recent: s.threshold > fraction - RECENT,
      };
    }),
  );
</script>

<figure class="shape" style:width="{size}px" style:height="{size}px">
  <svg
    width={size}
    height={size}
    viewBox="0 0 {size} {size}"
    role="img"
    aria-label={`Your voice is ${Math.round(fraction * 100)}% of the way to complete.`}
  >
    <g stroke-linecap="round">
      {#each lines as l (l.i)}
        <line {...l.ghost} class="ghost" stroke-width={stroke} />
      {/each}
      {#each lines as l (l.i)}
        {#if l.grown}
          <line {...l.grown} class="grown" class:recent={l.recent} stroke-width={stroke} />
        {/if}
      {/each}
    </g>
    <circle cx={c} cy={c} r={inner * 0.88} class="core" />
  </svg>
  <figcaption>
    <span class="value">{label}</span>
    {#if caption}<span class="caption">{caption}</span>{/if}
  </figcaption>
</figure>

<style>
  .shape {
    position: relative;
    margin: 0;
    flex: none;
  }
  svg {
    display: block;
    overflow: visible;
  }
  .ghost {
    stroke: var(--border);
    opacity: 0.6;
  }
  .grown {
    stroke: var(--primary);
    transition: all calc(var(--speed) * 3) ease-out;
  }
  .grown.recent {
    stroke: var(--accent);
  }
  .core {
    fill: var(--surface);
  }
  :global(:root[data-theme='contrast']) .ghost {
    stroke: #444;
    opacity: 1;
  }
  figcaption {
    position: absolute;
    inset: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    text-align: center;
    pointer-events: none;
    padding: 0 22%;
  }
  .value {
    font-size: 1.9em;
    font-weight: 700;
    line-height: 1.1;
    letter-spacing: -0.02em;
  }
  .caption {
    font-size: 0.85em;
    color: var(--muted);
    line-height: 1.25;
    margin-top: 0.2rem;
  }
</style>
