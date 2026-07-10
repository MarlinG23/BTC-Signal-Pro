/** Shared Web Audio — must be unlocked via user gesture before playback. */

let audioCtx: AudioContext | null = null;
let unlocked = false;

export function isAudioUnlocked(): boolean {
  return unlocked;
}

export async function unlockAudio(): Promise<boolean> {
  try {
    if (!audioCtx) {
      audioCtx = new AudioContext();
    }
    if (audioCtx.state === "suspended") {
      await audioCtx.resume();
    }
    unlocked = audioCtx.state === "running";
    return unlocked;
  } catch {
    return false;
  }
}

export function playSignalBeep(bullish: boolean): void {
  if (!audioCtx || !unlocked) return;

  try {
    const osc = audioCtx.createOscillator();
    const gain = audioCtx.createGain();
    osc.connect(gain);
    gain.connect(audioCtx.destination);
    osc.frequency.value = bullish ? 880 : 440;
    gain.gain.setValueAtTime(0.3, audioCtx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + 0.5);
    osc.start(audioCtx.currentTime);
    osc.stop(audioCtx.currentTime + 0.5);
  } catch {
    // Ignore playback errors after unlock
  }
}
