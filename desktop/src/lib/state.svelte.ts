// App-wide state: settings, the voice bank overview, the current view and messages.

import { api, errorMessage } from './api';
import type { AppInfo, Overview, SessionStart, Settings, View } from './types';

export type ToastKind = 'info' | 'success' | 'error';

class AppStore {
  info = $state<AppInfo | null>(null);
  settings = $state<Settings | null>(null);
  overview = $state<Overview | null>(null);
  view = $state<View>('today');
  /** A recording session in progress: the studio takes over the window. */
  session = $state<SessionStart | null>(null);
  toast = $state<{ message: string; kind: ToastKind; id: number } | null>(null);
  ready = $state(false);
  loadError = $state<string | null>(null);

  async init(): Promise<void> {
    try {
      const [info, settings, overview] = await Promise.all([
        api.appInfo(),
        api.getSettings(),
        api.overview(),
      ]);
      this.info = info;
      this.settings = settings;
      this.overview = overview;
      const requested = new URLSearchParams(location.search).get('view') as View | null;
      if (requested) this.view = requested;
    } catch (e) {
      this.loadError = errorMessage(e);
    } finally {
      this.ready = true;
    }
  }

  async refresh(): Promise<void> {
    try {
      this.overview = await api.overview();
    } catch (e) {
      this.notify(errorMessage(e), 'error');
    }
  }

  async updateSettings(patch: Partial<Settings>): Promise<void> {
    if (!this.settings) return;
    const previous = this.settings;
    this.settings = { ...this.settings, ...patch };
    try {
      this.settings = await api.saveSettings(this.settings);
      if ('bankDir' in patch) await this.refresh();
    } catch (e) {
      this.settings = previous;
      this.notify(errorMessage(e), 'error');
    }
  }

  go(view: View): void {
    this.view = view;
    window.scrollTo?.({ top: 0 });
  }

  notify(message: string, kind: ToastKind = 'info'): void {
    const id = Date.now();
    this.toast = { message, kind, id };
    setTimeout(
      () => {
        if (this.toast?.id === id) this.toast = null;
      },
      kind === 'error' ? 8000 : 4500,
    );
  }

  get hasBank(): boolean {
    return !!this.overview?.bank;
  }
}

export const app = new AppStore();
