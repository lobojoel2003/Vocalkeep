import { mount } from 'svelte';
import '@fontsource/atkinson-hyperlegible-next/400.css';
import '@fontsource/atkinson-hyperlegible-next/700.css';
import './app.css';
import App from './App.svelte';

// In a plain browser (`npm run dev`), stand in for the Rust backend with a demo voice bank so the
// interface can be worked on and screenshotted. Never included in the app's production build.
if (import.meta.env.DEV && !('__TAURI_INTERNALS__' in window)) {
  const { installMockBackend } = await import('./lib/mock');
  installMockBackend();
}

const app = mount(App, { target: document.getElementById('app')! });

export default app;
