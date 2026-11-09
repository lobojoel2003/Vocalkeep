<script lang="ts" module>
  // Simple line icons drawn for Vocalkeep (24×24, round strokes).
  const PATHS = {
    today:
      'M12 3v2M12 19v2M5.6 5.6l1.4 1.4M17 17l1.4 1.4M3 12h2M19 12h2M5.6 18.4 7 17M17 7l1.4-1.4M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8Z',
    progress: 'M4 20V10M10 20V4M16 20v-7M22 20H2',
    phrases: 'M4 6h16M4 12h10M4 18h7M17 15l2 2 4-4',
    messages:
      'M20 12a8 8 0 0 1-11.9 7L3 20l1.1-4.6A8 8 0 1 1 20 12ZM9 10.5c.8-1.2 2.6-1.2 3 .1.4-1.3 2.2-1.3 3-.1.6 1-.2 2.2-3 4.1-2.8-1.9-3.6-3.1-3-4.1Z',
    voice: 'M3 12h2M7 8v8M11 5v14M15 9v6M19 11v2M21 12h0',
    settings:
      'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z',
    mic: 'M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3ZM5 11a7 7 0 0 0 14 0M12 18v3',
    play: 'M7 4.5v15l12-7.5-12-7.5Z',
    stop: 'M7 7h10v10H7z',
    check: 'M5 12.5l4.5 4.5L19 7.5',
    redo: 'M4 12a8 8 0 1 0 2.4-5.7L4 8.5M4 4v4.5h4.5',
    skip: 'M5 5l8 7-8 7V5ZM17 5v14',
    close: 'M6 6l12 12M18 6 6 18',
    folder: 'M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z',
    download: 'M12 4v11M7 10l5 5 5-5M5 20h14',
    upload: 'M12 20V9M7 14l5-5 5 5M5 4h14',
    plus: 'M12 5v14M5 12h14',
    trash: 'M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3',
    edit: 'M4 20h4L19 9l-4-4L4 16v4ZM14 6l4 4',
    water: 'M12 3s6 6.5 6 11a6 6 0 0 1-12 0c0-4.5 6-11 6-11Z',
    sparkle:
      'M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3ZM19 16l.7 2.3L22 19l-2.3.7L19 22l-.7-2.3L16 19l2.3-.7L19 16Z',
    info: 'M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20ZM12 16v-5M12 8h0',
    warn: 'M12 3 2 20h20L12 3ZM12 10v4M12 17h0',
    heart:
      'M12 20s-7-4.4-9.2-8.6C1.2 8.3 3 5 6.3 5c2 0 3.2 1.1 3.9 2.2h3.6C14.5 6.1 15.7 5 17.7 5 21 5 22.8 8.3 21.2 11.4 19 15.6 12 20 12 20Z',
    computer: 'M3 5h18v11H3zM8 20h8M12 16v4',
    phone: 'M8 2h8a2 2 0 0 1 2 2v16a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2ZM11 18h2',
    archive: 'M3 4h18v4H3zM5 8v11a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8M10 12h4',
    leaf: 'M5 19c0-8 5-14 15-15-1 10-7 15-15 15ZM5 19 13 11',
    back: 'M15 5l-7 7 7 7',
  } as const;
  export type IconName = keyof typeof PATHS;
</script>

<script lang="ts">
  let {
    name,
    size = 22,
    label,
  }: {
    name: IconName;
    size?: number;
    label?: string;
  } = $props();

  const filled = $derived(name === 'play' || name === 'stop');
</script>

<svg
  width={size}
  height={size}
  viewBox="0 0 24 24"
  fill={filled ? 'currentColor' : 'none'}
  stroke="currentColor"
  stroke-width="1.9"
  stroke-linecap="round"
  stroke-linejoin="round"
  role={label ? 'img' : undefined}
  aria-label={label}
  aria-hidden={label ? undefined : 'true'}
  focusable="false"
>
  <path d={PATHS[name]} />
</svg>
