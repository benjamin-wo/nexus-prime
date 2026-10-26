import { useCallback, useEffect, useRef, useState } from "react";

/** Voice notes are capped at two minutes; the recorder stops and sends at the cap. */
export const MAX_VOICE_SECONDS = 120;

export const NO_MIC_HINT = "Mic isn't available here — send a voice note in the Telegram chat instead.";

// In order of preference: Chrome and Firefox, then Firefox/Android, then Safari.
const FORMATS = [
  { mime: "audio/webm;codecs=opus", ext: "webm" },
  { mime: "audio/ogg;codecs=opus", ext: "ogg" },
  { mime: "audio/mp4", ext: "m4a" },
];

/** Whether this browser can record at all: needs a microphone API and MediaRecorder. */
export function canRecord(): boolean {
  return typeof MediaRecorder !== "undefined" && typeof navigator !== "undefined" && typeof navigator.mediaDevices?.getUserMedia === "function";
}

/** The first format MediaRecorder says it supports (none: let the browser choose). */
function pickFormat(): { mime: string; ext: string } | null {
  if (typeof MediaRecorder.isTypeSupported !== "function") return null;
  return FORMATS.find((f) => MediaRecorder.isTypeSupported(f.mime)) ?? null;
}

/** The file extension for what was recorded. */
function extensionFor(mime: string): string {
  if (mime.includes("ogg")) return "ogg";
  if (mime.includes("mp4") || mime.includes("m4a") || mime.includes("aac")) return "m4a";
  return "webm";
}

export type Recorded = { blob: Blob; filename: string };

/** Records a voice note with the microphone. `start` asks for the mic and begins; `stop` finishes
 * and hands the audio to `onDone`; `cancel` throws it away. Every track is stopped afterwards, so the
 * phone's mic indicator goes off. Unsupported or refused mic: `onUnavailable`, never an exception. */
export function useVoiceRecorder({
  onDone,
  onUnavailable,
  onEmpty,
}: {
  onDone: (recorded: Recorded) => void;
  onUnavailable: () => void;
  onEmpty: () => void;
}) {
  const [recording, setRecording] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const recorder = useRef<MediaRecorder | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const timer = useRef<number | null>(null);
  const discard = useRef(false);
  // A start that is waiting for the permission prompt.
  const starting = useRef(false);
  const callbacks = useRef({ onDone, onUnavailable, onEmpty });
  callbacks.current = { onDone, onUnavailable, onEmpty };

  const release = useCallback(() => {
    if (timer.current !== null) window.clearInterval(timer.current);
    timer.current = null;
    stream.current?.getTracks().forEach((track) => track.stop());
    stream.current = null;
    recorder.current = null;
    setRecording(false);
    setSeconds(0);
  }, []);

  const finish = useCallback((send: boolean) => {
    const active = recorder.current;
    if (!active) return;
    discard.current = !send;
    if (timer.current !== null) window.clearInterval(timer.current);
    timer.current = null;
    try {
      if (active.state !== "inactive") active.stop();
      else release();
    } catch {
      release();
    }
  }, [release]);

  const stop = useCallback(() => finish(true), [finish]);
  const cancel = useCallback(() => {
    if (starting.current) starting.current = false; // refused to wait: drop it when the prompt is answered
    finish(false);
  }, [finish]);

  const start = useCallback(async () => {
    if (recorder.current || starting.current) return;
    if (!canRecord()) {
      callbacks.current.onUnavailable();
      return;
    }
    starting.current = true;
    let media: MediaStream;
    try {
      media = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      if (starting.current) callbacks.current.onUnavailable();
      starting.current = false;
      return;
    }
    if (!starting.current) {
      // Cancelled (or closed) while the permission prompt was open.
      media.getTracks().forEach((track) => track.stop());
      return;
    }
    starting.current = false;
    let active: MediaRecorder;
    const format = pickFormat();
    try {
      active = format ? new MediaRecorder(media, { mimeType: format.mime }) : new MediaRecorder(media);
    } catch {
      media.getTracks().forEach((track) => track.stop());
      callbacks.current.onUnavailable();
      return;
    }
    const chunks: Blob[] = [];
    active.ondataavailable = (event) => {
      if (event.data && event.data.size > 0) chunks.push(event.data);
    };
    active.onerror = () => {
      discard.current = true;
      release();
      callbacks.current.onUnavailable();
    };
    active.onstop = () => {
      const send = !discard.current;
      const type = active.mimeType || format?.mime || "audio/webm";
      release();
      if (!send) return;
      const blob = new Blob(chunks, { type });
      if (blob.size === 0) callbacks.current.onEmpty();
      else callbacks.current.onDone({ blob, filename: `voice.${format?.ext ?? extensionFor(type)}` });
    };
    discard.current = false;
    recorder.current = active;
    stream.current = media;
    try {
      active.start();
    } catch {
      discard.current = true;
      release();
      callbacks.current.onUnavailable();
      return;
    }
    const began = Date.now();
    setSeconds(0);
    setRecording(true);
    timer.current = window.setInterval(() => {
      const elapsed = Math.min(MAX_VOICE_SECONDS, Math.floor((Date.now() - began) / 1000));
      setSeconds(elapsed);
      if (elapsed >= MAX_VOICE_SECONDS) stop();
    }, 250);
  }, [release, stop]);

  // Closing the chat mid-recording throws the note away and lets the mic go.
  useEffect(
    () => () => {
      starting.current = false;
      discard.current = true;
      if (recorder.current && recorder.current.state !== "inactive") {
        try {
          recorder.current.stop();
        } catch {
          /* already stopped */
        }
      }
      if (timer.current !== null) window.clearInterval(timer.current);
      stream.current?.getTracks().forEach((track) => track.stop());
    },
    [],
  );

  return { recording, seconds, start, stop, cancel };
}

/** 75 seconds as "1:15". */
export function clock(seconds: number): string {
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}
