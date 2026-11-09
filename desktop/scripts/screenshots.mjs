// Renders the README screenshots from the app's built-in demo voice bank (no real recordings).
//
//   npm run dev &           # serves the interface with the demo backend on :1420
//   npm run screenshots     # writes ../docs/screenshots/*.png
//
// Needs Playwright (`npm i -g playwright && npx playwright install chromium`); it is resolved
// through NODE_PATH as well, so a global install works: NODE_PATH=$(npm root -g).

import { mkdir } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const { chromium } = createRequire(import.meta.url)('playwright');

const BASE = process.env.VOCALKEEP_DEV_URL ?? 'http://localhost:1420/';
const OUT = fileURLToPath(new URL('../../docs/screenshots/', import.meta.url));
const SCALE = Number(process.env.SCALE ?? 2);

const shots = [
  { name: 'today', query: 'view=today' },
  { name: 'progress', query: 'view=progress' },
  { name: 'progress-dark', query: 'view=progress&theme=dark' },
  { name: 'messages', query: 'view=messages' },
  { name: 'my-voice', query: 'view=voice' },
  { name: 'settings', query: 'view=settings' },
  { name: 'welcome', query: 'onboarding=1' },
  { name: 'studio-recording', query: 'view=today', studio: 'recording' },
  { name: 'studio-review', query: 'view=today', studio: 'review' },
  { name: 'studio-note', query: 'view=today&verdict=okay&theme=dark', studio: 'review' },
  { name: 'studio-contrast', query: 'view=today&theme=contrast', studio: 'recording' },
];

const only = process.argv.slice(2);
await mkdir(OUT, { recursive: true });
const browser = await chromium.launch();
try {
  for (const shot of shots) {
    if (only.length && !only.includes(shot.name)) continue;
    const page = await browser.newPage({
      viewport: { width: 1280, height: 820 },
      deviceScaleFactor: SCALE,
      colorScheme: 'light',
      reducedMotion: 'no-preference',
    });
    await page.goto(`${BASE}?${shot.query}`);
    await page.waitForSelector('main, .welcome', { timeout: 15000 });
    if (shot.studio) {
      await page.getByRole('button', { name: /^Okay/ }).click();
      await page.waitForSelector('.prompt');
      await page.keyboard.press('Space');
      await page.waitForTimeout(1600);
      if (shot.studio === 'review') {
        await page.keyboard.press('Space');
        await page.waitForSelector('.verdict');
        await page.waitForTimeout(400);
      }
    } else {
      await page.waitForTimeout(700);
    }
    await page.screenshot({ path: `${OUT}${shot.name}.png` });
    console.log(`docs/screenshots/${shot.name}.png`);
    await page.close();
  }
} finally {
  await browser.close();
}
