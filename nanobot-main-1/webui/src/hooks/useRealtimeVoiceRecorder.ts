import { useCallback, useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";

import type { VoiceRecorderErrorKey } from "@/hooks/useVoiceRecorder";

const MAX_RECORDING_MS = 60_000;
const MIN_RECORDING_MS = 300;
const HOLD_START_MS = 140;
const PCM_SAMPLE_RATE = 16_000;
const IDLE_LEVELS = Array.from({ length: 64 }, () => 3);
// Keep enough early audio to cover the provider handshake after interrupting
// speech. At a normal 48 kHz input this is roughly eight seconds.
const MAX_PENDING_AUDIO_CHUNKS = 192;

interface Options {
  disabled?: boolean;
  onClearError: () => void;
  onError: (key: VoiceRecorderErrorKey) => void;
  onTranscript: (text: string) => void;
  onStart?: () => Promise<string>;
  onAudio?: (sessionId: string, pcmBase64: string) => void;
  onStop?: (sessionId: string) => Promise<string>;
  onCancel?: (sessionId: string) => void;
  /** Stop assistant speech before the microphone begins collecting a new turn. */
  onInterruptSpeech?: () => void;
}

/** Browser microphone -> 16kHz PCM stream for Bailian realtime ASR. */
export function useRealtimeVoiceRecorder(options: Options) {
  // The composer re-renders for every waveform update. Keep callbacks in a
  // ref so that a harmless paint cannot recreate `finish` and accidentally
  // run the unmount cleanup while the operator is still holding the mic.
  const optionsRef = useRef(options);
  useEffect(() => { optionsRef.current = options; }, [options]);
  const streamRef = useRef<MediaStream | null>(null);
  const contextRef = useRef<AudioContext | null>(null);
  const sourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const silentGainRef = useRef<GainNode | null>(null);
  const sessionIdRef = useRef<string | null>(null);
  const startPromiseRef = useRef<Promise<string> | null>(null);
  const pendingAudioRef = useRef<string[]>([]);
  const pendingFinishRef = useRef<{ cancelled: boolean; duration: number } | null>(null);
  const endingRef = useRef(false);
  const preparingRef = useRef(false);
  const startAbortedRef = useRef(false);
  const captureGenerationRef = useRef(0);
  const startedAtRef = useRef(0);
  const holdTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const holdActiveRef = useRef(false);
  const suppressClickRef = useRef(false);
  const maxTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [state, setState] = useState<"idle" | "preparing" | "recording" | "transcribing">("idle");
  const [elapsedMs, setElapsedMs] = useState(0);
  const [levels, setLevels] = useState<number[]>(IDLE_LEVELS);

  const enabled = Boolean(options.onStart && options.onAudio && options.onStop && options.onCancel);

  const cleanup = useCallback((releaseMicrophone = false) => {
    // Invalidate the callback before AudioContext.close() completes. Without
    // this guard an old processor can briefly emit into the next ASR turn,
    // duplicating audio and making recognition look delayed.
    captureGenerationRef.current += 1;
    clearTimeout(holdTimerRef.current ?? undefined);
    clearTimeout(maxTimerRef.current ?? undefined);
    holdTimerRef.current = null;
    maxTimerRef.current = null;
    if (processorRef.current) {
      processorRef.current.onaudioprocess = null;
      processorRef.current.disconnect();
    }
    sourceRef.current?.disconnect();
    silentGainRef.current?.disconnect();
    processorRef.current = null;
    sourceRef.current = null;
    silentGainRef.current = null;
    // Retain the already-authorized microphone between push-to-talk turns.
    // This avoids losing the first syllable while the browser reopens the
    // device. The stream never reaches the provider until a new recording
    // turn has started, so idle time does not create ASR audio usage.
    if (releaseMicrophone) {
      streamRef.current?.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    }
    const context = contextRef.current;
    contextRef.current = null;
    if (context) void context.close().catch(() => undefined);
  }, []);

  const completeTurn = useCallback(async (sessionId: string, cancelled: boolean, duration: number) => {
    pendingFinishRef.current = null;
    pendingAudioRef.current = [];
    startPromiseRef.current = null;
    if (!sessionId) {
      endingRef.current = false;
      setState("idle");
      return;
    }
    if (cancelled) {
      optionsRef.current.onCancel?.(sessionId);
      sessionIdRef.current = null;
      endingRef.current = false;
      setState("idle");
      return;
    }
    if (duration < MIN_RECORDING_MS) {
      optionsRef.current.onCancel?.(sessionId);
      optionsRef.current.onError("tooShort");
      sessionIdRef.current = null;
      endingRef.current = false;
      setState("idle");
      return;
    }
    setState("transcribing");
    try {
      const transcript = await optionsRef.current.onStop!(sessionId);
      if (!transcript.trim()) optionsRef.current.onError("noInput");
      else optionsRef.current.onTranscript(transcript);
    } catch (error) {
      const detail = error instanceof Error ? error.message : "";
      optionsRef.current.onError(detail === "voice_not_configured" ? "notConfigured" : "failed");
    } finally {
      sessionIdRef.current = null;
      endingRef.current = false;
      setState("idle");
    }
  }, []);

  const finish = useCallback(async (cancelled = false) => {
    if (endingRef.current) return;
    // The user can release a press while getUserMedia is still resolving.
    // Abort that preparation rather than opening an ASR turn with no audio.
    if (preparingRef.current && !sessionIdRef.current && !startPromiseRef.current) {
      startAbortedRef.current = true;
      preparingRef.current = false;
      pendingAudioRef.current = [];
      cleanup();
      setState("idle");
      return;
    }
    endingRef.current = true;
    const duration = Math.max(0, Date.now() - startedAtRef.current);
    const sessionId = sessionIdRef.current;
    cleanup();
    if (sessionId) {
      await completeTurn(sessionId, cancelled, duration);
      return;
    }

    // The first spoken syllables can arrive before the ASR WebSocket reports
    // `voice_started`, particularly when it follows a TTS interruption. Keep
    // the capture buffer and finish as soon as that handshake completes.
    if (startPromiseRef.current) {
      pendingFinishRef.current = { cancelled, duration };
      setState(cancelled ? "idle" : "transcribing");
      return;
    }
    endingRef.current = false;
    setState("idle");
  }, [cleanup, completeTurn]);

  const start = useCallback(async () => {
    if (!enabled || optionsRef.current.disabled || state !== "idle" || preparingRef.current) return;
    if (!navigator.mediaDevices?.getUserMedia || !audioContextConstructor()) {
      optionsRef.current.onError("unsupported");
      return;
    }
    try {
      preparingRef.current = true;
      startAbortedRef.current = false;
      setState("preparing");
      optionsRef.current.onInterruptSpeech?.();
      let stream = streamRef.current;
      if (!stream?.active || !stream.getAudioTracks().some((track) => track.readyState === "live")) {
        stream = await navigator.mediaDevices.getUserMedia({
          audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
        });
        streamRef.current = stream;
      }
      if (startAbortedRef.current) {
        preparingRef.current = false;
        setState("idle");
        return;
      }
      // Enter the recording state as soon as the microphone is open.  The
      // provider handshake is network-bound and may take a moment after TTS
      // is interrupted; waiting for it here made a successful click look like
      // it had done nothing.
      startedAtRef.current = Date.now();
      setElapsedMs(0);
      setLevels(IDLE_LEVELS);
      const Ctor = audioContextConstructor()!;
      const captureGeneration = ++captureGenerationRef.current;
      const context = new Ctor();
      const source = context.createMediaStreamSource(stream);
      const processor = context.createScriptProcessor(2048, 1, 1);
      const silentGain = context.createGain();
      silentGain.gain.value = 0;
      processor.onaudioprocess = (event) => {
        if (captureGeneration !== captureGenerationRef.current) return;
        const input = event.inputBuffer.getChannelData(0);
        const pcm = downsampleToPcm16(input, context.sampleRate);
        if (pcm.byteLength) {
          const encoded = pcmToBase64(pcm);
          const sessionId = sessionIdRef.current;
          if (sessionId) {
            optionsRef.current.onAudio?.(sessionId, encoded);
          } else if (pendingAudioRef.current.length < MAX_PENDING_AUDIO_CHUNKS) {
            pendingAudioRef.current.push(encoded);
          }
        }
        const level = rms(input);
        setLevels((current) => [...current.slice(1), waveformHeight(level)]);
      };
      source.connect(processor);
      processor.connect(silentGain);
      silentGain.connect(context.destination);
      contextRef.current = context;
      sourceRef.current = source;
      processorRef.current = processor;
      silentGainRef.current = silentGain;
      await context.resume();
      if (startAbortedRef.current) {
        preparingRef.current = false;
        pendingAudioRef.current = [];
        cleanup();
        setState("idle");
        return;
      }
      preparingRef.current = false;
      setState("recording");
      optionsRef.current.onClearError();
      maxTimerRef.current = setTimeout(() => { void finish(); }, MAX_RECORDING_MS);

      const startPromise = optionsRef.current.onStart!();
      startPromiseRef.current = startPromise;
      void startPromise.then(async (sessionId) => {
        // A newer recording may have superseded this delayed provider session.
        if (startPromiseRef.current !== startPromise) {
          optionsRef.current.onCancel?.(sessionId);
          return;
        }
        sessionIdRef.current = sessionId;
        const buffered = pendingAudioRef.current;
        pendingAudioRef.current = [];
        for (const audio of buffered) optionsRef.current.onAudio?.(sessionId, audio);

        const pendingFinish = pendingFinishRef.current;
        if (pendingFinish) {
          await completeTurn(sessionId, pendingFinish.cancelled, pendingFinish.duration);
        }
      }).catch((error: unknown) => {
        if (startPromiseRef.current !== startPromise) return;
        startPromiseRef.current = null;
        pendingAudioRef.current = [];
        pendingFinishRef.current = null;
        sessionIdRef.current = null;
        preparingRef.current = false;
        cleanup();
        endingRef.current = false;
        setState("idle");
        const detail = error instanceof Error ? error.message : "";
        optionsRef.current.onError(detail.startsWith("voice_") ? "failed" : "permission");
      });
    } catch (error) {
      cleanup();
      startPromiseRef.current = null;
      pendingAudioRef.current = [];
      pendingFinishRef.current = null;
      preparingRef.current = false;
      endingRef.current = false;
      setState("idle");
      const detail = error instanceof Error ? error.message : "";
      optionsRef.current.onError(detail.startsWith("voice_") ? "failed" : "permission");
    }
  }, [cleanup, enabled, finish, state]);

  const beginPress = useCallback((event: ReactPointerEvent<HTMLButtonElement>) => {
    if (event.pointerType === "mouse" && event.button !== 0) return;
    if (!enabled || optionsRef.current.disabled || state !== "idle") return;
    try { event.currentTarget.setPointerCapture(event.pointerId); } catch { /* host bridge may not expose capture */ }
    clearTimeout(holdTimerRef.current ?? undefined);
    holdTimerRef.current = setTimeout(() => {
      holdActiveRef.current = true;
      suppressClickRef.current = true;
      void start();
    }, HOLD_START_MS);
  }, [enabled, start, state]);

  const endPress = useCallback(() => {
    clearTimeout(holdTimerRef.current ?? undefined);
    holdTimerRef.current = null;
    if (!holdActiveRef.current) return;
    holdActiveRef.current = false;
    suppressClickRef.current = true;
    void finish();
  }, [finish]);

  const handleClick = useCallback(() => {
    if (suppressClickRef.current) {
      suppressClickRef.current = false;
      return;
    }
    if (state === "recording") void finish();
    else if (state === "idle") void start();
  }, [finish, start, state]);

  const beginShortcutHold = useCallback(() => { if (state === "idle") void start(); }, [start, state]);
  const endShortcutHold = useCallback(() => { if (state === "recording") void finish(); }, [finish, state]);

  useEffect(() => {
    if (state !== "recording") { setElapsedMs(0); return; }
    const timer = window.setInterval(() => setElapsedMs(Math.max(0, Date.now() - startedAtRef.current)), 250);
    return () => window.clearInterval(timer);
  }, [state]);
  useEffect(() => () => {
    void finish(true);
    // Leaving the chat/settings page or closing the app is the explicit
    // lifecycle boundary for the retained microphone stream.
    cleanup(true);
  }, [cleanup, finish]);

  return {
    beginShortcutHold, beginPress, endShortcutHold, endPress, handleClick,
    buttonDisabled: options.disabled || state === "preparing" || state === "transcribing" || !enabled,
    elapsedLabel: formatElapsed(elapsedMs), isRecording: state === "recording", levels, state,
  };
}

function audioContextConstructor(): typeof AudioContext | undefined {
  if (typeof window === "undefined") return undefined;
  return window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
}

function downsampleToPcm16(input: Float32Array, inputRate: number): Int16Array {
  if (inputRate === PCM_SAMPLE_RATE) return toPcm16(input);
  const ratio = inputRate / PCM_SAMPLE_RATE;
  const output = new Int16Array(Math.floor(input.length / ratio));
  for (let index = 0; index < output.length; index += 1) {
    const start = Math.floor(index * ratio);
    const end = Math.min(input.length, Math.floor((index + 1) * ratio));
    let sum = 0;
    for (let sample = start; sample < end; sample += 1) sum += input[sample];
    output[index] = floatToPcm16(sum / Math.max(1, end - start));
  }
  return output;
}

function toPcm16(input: Float32Array): Int16Array {
  const output = new Int16Array(input.length);
  for (let index = 0; index < input.length; index += 1) output[index] = floatToPcm16(input[index]);
  return output;
}

function floatToPcm16(value: number): number {
  const sample = Math.max(-1, Math.min(1, value));
  return sample < 0 ? sample * 0x8000 : sample * 0x7fff;
}

function pcmToBase64(pcm: Int16Array): string {
  const bytes = new Uint8Array(pcm.buffer, pcm.byteOffset, pcm.byteLength);
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000));
  }
  return btoa(binary);
}

function rms(samples: Float32Array): number {
  let sum = 0;
  for (const value of samples) sum += value * value;
  return Math.sqrt(sum / Math.max(samples.length, 1));
}

function waveformHeight(level: number): number {
  if (level < 0.012) return 3;
  return Math.round(7 + Math.min(1, level * 8) * 27);
}

function formatElapsed(ms: number): string {
  const seconds = Math.max(0, Math.floor(ms / 1000));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}
