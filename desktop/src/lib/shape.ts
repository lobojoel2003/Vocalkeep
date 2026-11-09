// Geometry for the "voice taking shape" picture: a ring of spokes, like a sound wave drawn in a
// circle. Every spoke has a place in the finished shape; spokes grow in, in a scattered order,
// as sentences are recorded, so the picture fills up the way a voice does.

export interface Spoke {
  /** Radians, starting at the top and going clockwise. */
  angle: number;
  /** Final length, 0..1 of the available radius. */
  length: number;
  /** Fraction of the voice bank at which this spoke grows in. */
  threshold: number;
}

/** A small deterministic random generator (mulberry32). */
export function random(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function spokes(count: number, seed = 7): Spoke[] {
  const rnd = random(seed);
  // A few slow waves make an organic outline, with small per-spoke variation on top.
  const waves = [1, 2, 3, 5].map((k) => ({ k, phase: rnd() * Math.PI * 2, amp: 0.5 / k }));
  const out: Spoke[] = [];
  for (let i = 0; i < count; i++) {
    const angle = (i / count) * Math.PI * 2;
    let v = 0;
    for (const w of waves) v += w.amp * Math.sin(w.k * angle + w.phase);
    const jitter = (rnd() - 0.5) * 0.14;
    const length = Math.min(1, Math.max(0.35, 0.7 + v * 0.34 + jitter));
    out.push({ angle, length, threshold: 0 });
  }
  // Shuffle the order spokes grow in (Fisher-Yates), so filling looks natural, not like a clock.
  const order = out.map((_, i) => i);
  for (let i = order.length - 1; i > 0; i--) {
    const j = Math.floor(rnd() * (i + 1));
    [order[i], order[j]] = [order[j]!, order[i]!];
  }
  order.forEach((spokeIndex, rank) => {
    out[spokeIndex]!.threshold = (rank + 1) / count;
  });
  return out;
}

/** How grown a spoke is (0..1) when `fraction` of the bank is recorded. */
export function growth(threshold: number, fraction: number, softness = 0.02): number {
  if (fraction <= 0) return 0;
  if (fraction >= threshold) return 1;
  if (fraction <= threshold - softness) return 0;
  return (fraction - (threshold - softness)) / softness;
}

/**
 * How full the picture is. A gentle curve makes early sessions visible: the first hundred
 * sentences matter a lot and should look like it.
 */
export function shapeFraction(kept: number, complete: number): number {
  if (complete <= 0) return 0;
  return Math.min(1, Math.pow(Math.max(0, kept) / complete, 0.75));
}

/** Start and end points of a spoke for an SVG line, centred on (c, c). */
export function spokeLine(
  s: Spoke,
  c: number,
  inner: number,
  outer: number,
  grown: number,
): { x1: number; y1: number; x2: number; y2: number } {
  const length = inner + (outer - inner) * s.length * grown;
  const sin = Math.sin(s.angle);
  const cos = Math.cos(s.angle);
  return {
    x1: c + sin * inner,
    y1: c - cos * inner,
    x2: c + sin * length,
    y2: c - cos * length,
  };
}
