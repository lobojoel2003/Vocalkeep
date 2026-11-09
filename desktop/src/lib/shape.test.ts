import { describe, expect, it } from 'vitest';
import { growth, random, shapeFraction, spokeLine, spokes } from './shape';

describe('voice shape', () => {
  it('is deterministic', () => {
    expect(spokes(60, 3)).toEqual(spokes(60, 3));
    expect(random(1)()).toBe(random(1)());
  });

  it('gives every spoke a unique growth threshold', () => {
    const s = spokes(120);
    const thresholds = new Set(s.map((x) => x.threshold));
    expect(thresholds.size).toBe(120);
    expect(Math.max(...thresholds)).toBe(1);
    for (const x of s) {
      expect(x.length).toBeGreaterThanOrEqual(0.3);
      expect(x.length).toBeLessThanOrEqual(1);
    }
  });

  it('fills as the bank grows', () => {
    const s = spokes(100);
    const grown = (f: number) => s.filter((x) => growth(x.threshold, f) === 1).length;
    expect(grown(0)).toBe(0);
    expect(s.every((x) => growth(x.threshold, 0) === 0)).toBe(true);
    expect(grown(0.5)).toBeGreaterThanOrEqual(49);
    expect(grown(1)).toBe(100);
  });

  it('shows early progress clearly', () => {
    expect(shapeFraction(0, 1500)).toBe(0);
    expect(shapeFraction(150, 1500)).toBeGreaterThan(0.15);
    expect(shapeFraction(3000, 1500)).toBe(1);
    expect(shapeFraction(10, 0)).toBe(0);
  });

  it('draws spokes outward from the centre', () => {
    const top = spokeLine({ angle: 0, length: 1, threshold: 0 }, 100, 40, 90, 1);
    expect(top.x1).toBeCloseTo(100);
    expect(top.y1).toBeCloseTo(60);
    expect(top.y2).toBeCloseTo(10);
  });
});
