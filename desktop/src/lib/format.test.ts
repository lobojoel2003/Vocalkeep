import { describe, expect, it } from 'vitest';
import { bytesText, clock, greeting, minutesText, percent, plural, relativeDay } from './format';

describe('format', () => {
  it('counts', () => {
    expect(plural(1, 'sentence')).toBe('1 sentence');
    expect(plural(1200, 'sentence')).toBe('1,200 sentences');
    expect(plural(2, 'day')).toBe('2 days');
  });

  it('clocks', () => {
    expect(clock(0)).toBe('0:00');
    expect(clock(7_400)).toBe('0:07');
    expect(clock(83_000)).toBe('1:23');
    expect(clock(3_723_000)).toBe('1:02:03');
  });

  it('minutes', () => {
    expect(minutesText(0.4)).toBe('less than a minute');
    expect(minutesText(12.2)).toBe('12 minutes');
    expect(minutesText(60)).toBe('1 hour');
    expect(minutesText(125)).toBe('2 hours 5 minutes');
  });

  it('sizes', () => {
    expect(bytesText(512)).toBe('512 B');
    expect(bytesText(2048)).toBe('2.0 KB');
    expect(bytesText(63_201_442)).toBe('60 MB');
  });

  it('relative days', () => {
    const now = new Date('2026-11-09T15:00:00');
    expect(relativeDay('2026-11-09T08:00:00', now)).toBe('today');
    expect(relativeDay('2026-11-08T22:00:00', now)).toBe('yesterday');
    expect(relativeDay('2026-11-05T10:00:00', now)).toBe('4 days ago');
    expect(relativeDay('2026-10-01T10:00:00', now)).toContain('2026');
    expect(relativeDay(null, now)).toBe('');
  });

  it('greets by first name and time of day', () => {
    expect(greeting('Maya Patel', new Date('2026-11-09T09:00:00'))).toBe('Good morning, Maya');
    expect(greeting('', new Date('2026-11-09T19:00:00'))).toBe('Good evening');
  });

  it('percent', () => {
    expect(percent(0.426)).toBe('43%');
    expect(percent(2)).toBe('100%');
  });
});
