// Plays WAV bytes from the Rust side. One sound at a time.

let current: HTMLAudioElement | null = null;
let currentUrl: string | null = null;

export function stopPlayback(): void {
  if (current) {
    current.pause();
    current.src = '';
    current = null;
  }
  if (currentUrl) {
    URL.revokeObjectURL(currentUrl);
    currentUrl = null;
  }
}

/** Plays the audio and resolves when it ends (or is stopped). */
export function playWav(bytes: ArrayBuffer): Promise<void> {
  stopPlayback();
  const url = URL.createObjectURL(new Blob([bytes], { type: 'audio/wav' }));
  const audio = new Audio(url);
  current = audio;
  currentUrl = url;
  return new Promise((resolve) => {
    const done = () => {
      if (current === audio) stopPlayback();
      resolve();
    };
    audio.addEventListener('ended', done, { once: true });
    audio.addEventListener('error', done, { once: true });
    audio.addEventListener('pause', () => resolve(), { once: true });
    audio.play().catch(done);
  });
}

export function isPlaying(): boolean {
  return current !== null && !current.paused;
}
