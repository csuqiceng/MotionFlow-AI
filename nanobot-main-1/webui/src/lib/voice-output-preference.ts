/** Per-operator preference for whether assistant replies are spoken aloud. */
export const VOICE_OUTPUT_PREFERENCE_EVENT = "robot-voice-output-preference";

const STORAGE_KEY = "robot.voice-output-enabled";

export function readVoiceOutputEnabled(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem(STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

export function writeVoiceOutputEnabled(enabled: boolean): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, enabled ? "1" : "0");
  } catch {
    // Playback remains off/on for the active page only if storage is blocked.
  }
  window.dispatchEvent(new Event(VOICE_OUTPUT_PREFERENCE_EVENT));
}
