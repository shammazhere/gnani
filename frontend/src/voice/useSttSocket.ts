import { useCallback, useEffect, useRef, useState } from "react";
import workletUrl from "./recorder.worklet.ts?worker&url";
import {
  ErrorCode,
  SavedAudio,
  SttServerMessage,
  SttStatus,
  SttTranscriptEvent,
  UseSttSocketOptions,
  UseSttSocketReturn,
  VoiceErrorInfo,
} from "./types";

const FRAME_PACING_MS = 32;
const FINALIZE_TIMEOUT_MS = 15_000;

function buildSttQueryParams(options: UseSttSocketOptions): URLSearchParams {
  const params = new URLSearchParams({
    lang: options.lang,
    mode: options.mode,
    kind: options.kind,
  });
  if (options.keyterms && options.keyterms.length > 0) {
    params.set("keyterms", JSON.stringify(options.keyterms));
  }
  return params;
}

function resolveWsUrl(options: UseSttSocketOptions): string {
  const params = buildSttQueryParams(options);
  const envWsBase = (import.meta.env.VITE_WS_URL || "")
    .trim()
    .replace(/\/+$/, "");
  const envApiBase = (import.meta.env.VITE_API_URL || "")
    .trim()
    .replace(/\/+$/, "");
  const explicitBase = options.wsBaseUrl
    ? options.wsBaseUrl.replace(/\/+$/, "")
    : envWsBase || (envApiBase ? envApiBase.replace(/^http/i, "ws") : "");

  if (explicitBase) {
    return `${explicitBase}/ws/stt?${params.toString()}`;
  }

  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}/ws/stt?${params.toString()}`;
}

function resolveSttHttpUrl(options: UseSttSocketOptions): string {
  const params = buildSttQueryParams(options);
  const envApiBase = (import.meta.env.VITE_API_URL || "")
    .trim()
    .replace(/\/+$/, "");
  const base = options.wsBaseUrl
    ? options.wsBaseUrl
        .replace(/\/+$/, "")
        .replace(/^wss:/i, "https:")
        .replace(/^ws:/i, "http:")
    : envApiBase;
  return `${base}/api/voice/stt?${params.toString()}`;
}

function mergePcmChunks(chunks: ArrayBuffer[]): Uint8Array {
  const totalBytes = chunks.reduce((sum, buf) => sum + buf.byteLength, 0);
  const merged = new Uint8Array(totalBytes);
  let offset = 0;
  for (const chunk of chunks) {
    merged.set(new Uint8Array(chunk), offset);
    offset += chunk.byteLength;
  }
  return merged;
}

function isPermissionDeniedError(err: unknown): boolean {
  if (err instanceof DOMException) {
    return (
      err.name === "NotAllowedError" ||
      err.name === "PermissionDeniedError" ||
      err.name === "SecurityError"
    );
  }
  return false;
}

export function useSttSocket(options: UseSttSocketOptions): UseSttSocketReturn {
  const [status, setStatus] = useState<SttStatus>("idle");
  const [segments, setSegments] = useState<SttTranscriptEvent[]>([]);
  const [detectedLanguage, setDetectedLanguage] = useState<string | null>(null);
  const [savedAudio, setSavedAudio] = useState<SavedAudio | null>(null);
  const [error, setError] = useState<VoiceErrorInfo | null>(null);

  const optionsRef = useRef(options);
  optionsRef.current = options;

  const wsRef = useRef<WebSocket | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const workletNodeRef = useRef<AudioWorkletNode | null>(null);
  const frameQueueRef = useRef<ArrayBuffer[]>([]);
  const pacerTimerRef = useRef<number | null>(null);
  const stoppingRef = useRef(false);
  const httpFallbackRef = useRef(false);
  const audioSavedRef = useRef(false);
  const serverErrorRef = useRef(false);
  const reconnectAttemptsRef = useRef(0);
  const endResolveRef = useRef<(() => void) | null>(null);

  const emitError = useCallback((code: ErrorCode, message: string) => {
    const info: VoiceErrorInfo = { code, message };
    setError(info);
    setStatus("error");
    optionsRef.current.onError?.(info);
  }, []);

  const stopPacer = useCallback(() => {
    if (pacerTimerRef.current !== null) {
      window.clearInterval(pacerTimerRef.current);
      pacerTimerRef.current = null;
    }
  }, []);

  const cleanupMedia = useCallback(() => {
    stopPacer();
    if (workletNodeRef.current) {
      workletNodeRef.current.port.onmessage = null;
      workletNodeRef.current.disconnect();
      workletNodeRef.current = null;
    }
    if (audioCtxRef.current) {
      void audioCtxRef.current.close().catch(() => undefined);
      audioCtxRef.current = null;
    }
    if (mediaStreamRef.current) {
      for (const track of mediaStreamRef.current.getTracks()) {
        track.stop();
      }
      mediaStreamRef.current = null;
    }
  }, [stopPacer]);

  const startPacer = useCallback(() => {
    stopPacer();
    // Strict 32 ms interval sends one 1,024-byte frame at a time (no buffer-and-burst).
    pacerTimerRef.current = window.setInterval(() => {
      const ws = wsRef.current;
      if (!ws || ws.readyState !== WebSocket.OPEN) {
        return;
      }
      const nextFrame = frameQueueRef.current.shift();
      if (nextFrame) {
        ws.send(nextFrame);
      }
    }, FRAME_PACING_MS);
  }, [stopPacer]);

  const openWebSocket = useCallback((): Promise<void> => {
    return new Promise((resolve, reject) => {
      serverErrorRef.current = false;
      const url = resolveWsUrl(optionsRef.current);
      const ws = new WebSocket(url);
      ws.binaryType = "arraybuffer";
      wsRef.current = ws;

      let opened = false;
      let settled = false;

      ws.onopen = () => {
        opened = true;
        settled = true;
        if (stoppingRef.current) {
          ws.close(1000);
          resolve();
          return;
        }
        reconnectAttemptsRef.current = 0;
        setStatus("recording");
        startPacer();
        resolve();
      };

      ws.onmessage = (event) => {
        if (typeof event.data !== "string") {
          return;
        }
        let msg: SttServerMessage;
        try {
          msg = JSON.parse(event.data) as SttServerMessage;
        } catch {
          return;
        }

        if (msg.type === "processing") {
          if (stoppingRef.current) {
            setStatus("processing");
          }
        } else if (msg.type === "transcript") {
          setSegments((prev) => [...prev, msg]);
          setDetectedLanguage(msg.detected_language_code);
          optionsRef.current.onTranscript?.(msg);
        } else if (msg.type === "audio_saved") {
          audioSavedRef.current = true;
          const saved: SavedAudio = {
            audio_ref: msg.audio_ref,
            sha256: msg.sha256,
            duration_ms: msg.duration_ms,
          };
          setSavedAudio(saved);
          optionsRef.current.onAudioSaved?.(saved);
          endResolveRef.current?.();
          endResolveRef.current = null;
        } else if (msg.type === "error") {
          serverErrorRef.current = true;
          emitError(msg.code, msg.message);
          endResolveRef.current?.();
          endResolveRef.current = null;
        }
      };

      ws.onerror = () => {
        if (!opened && !settled) {
          settled = true;
          reject(new Error("WebSocket handshake failed"));
        }
      };

      ws.onclose = (ev) => {
        stopPacer();
        if (!opened) {
          if (!settled) {
            settled = true;
            reject(new Error("WebSocket closed before open"));
          }
          return;
        }

        if (stoppingRef.current) {
          if (
            ev.code !== 1000 &&
            !audioSavedRef.current &&
            !serverErrorRef.current
          ) {
            emitError(
              "STT_CONNECTION_LOST",
              "Voice connection dropped before saving audio.",
            );
          } else {
            setStatus((prev) => (prev === "error" ? "error" : "idle"));
          }
          endResolveRef.current?.();
          endResolveRef.current = null;
          return;
        }

        if (ev.code === 1000) {
          setStatus((prev) => (prev === "error" ? "error" : "idle"));
          return;
        }

        const maxRetries = optionsRef.current.maxReconnectAttempts ?? 2;
        if (
          reconnectAttemptsRef.current < maxRetries &&
          mediaStreamRef.current
        ) {
          const attempt = reconnectAttemptsRef.current;
          reconnectAttemptsRef.current += 1;
          setStatus("connecting");
          window.setTimeout(
            () => {
              if (!stoppingRef.current && mediaStreamRef.current) {
                void openWebSocket().catch(() => {
                  emitError(
                    "STT_CONNECTION_LOST",
                    "Lost connection to voice server.",
                  );
                  cleanupMedia();
                });
              }
            },
            300 * 2 ** attempt,
          );
          return;
        }

        emitError(
          "STT_CONNECTION_LOST",
          "Voice connection closed unexpectedly.",
        );
        cleanupMedia();
      };
    });
  }, [cleanupMedia, emitError, startPacer, stopPacer]);

  const start = useCallback(async () => {
    if (status === "recording" || status === "connecting") {
      return;
    }

    stoppingRef.current = false;
    httpFallbackRef.current = false;
    audioSavedRef.current = false;
    frameQueueRef.current = [];
    setError(null);
    setSegments([]);
    setDetectedLanguage(null);
    setSavedAudio(null);
    setStatus("connecting");

    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
        },
      });
    } catch (err) {
      const code: ErrorCode = isPermissionDeniedError(err)
        ? "MIC_DENIED"
        : "STT_CONNECTION_LOST";
      emitError(
        code,
        code === "MIC_DENIED"
          ? "Microphone permission was denied."
          : "Unable to access microphone.",
      );
      return;
    }

    if (stoppingRef.current) {
      for (const track of stream.getTracks()) {
        track.stop();
      }
      setStatus("idle");
      return;
    }

    mediaStreamRef.current = stream;

    try {
      const audioCtx = new AudioContext();
      audioCtxRef.current = audioCtx;
      await audioCtx.audioWorklet.addModule(workletUrl);

      if (stoppingRef.current) {
        cleanupMedia();
        setStatus("idle");
        return;
      }

      const source = audioCtx.createMediaStreamSource(stream);
      const worklet = new AudioWorkletNode(audioCtx, "saakshi-pcm-recorder");
      workletNodeRef.current = worklet;

      worklet.port.onmessage = (
        event: MessageEvent<{ type?: string; buffer?: ArrayBuffer }>,
      ) => {
        if (event.data?.type === "frame" && event.data.buffer) {
          frameQueueRef.current.push(event.data.buffer);
        }
      };

      source.connect(worklet);
      try {
        await openWebSocket();
      } catch {
        // Serverless hosts (e.g. Vercel Functions) reject inbound WebSockets;
        // retain recorded PCM frames and upload over HTTPS POST /api/voice/stt on stop().
        if (!stoppingRef.current && mediaStreamRef.current) {
          httpFallbackRef.current = true;
          setStatus("recording");
        } else {
          cleanupMedia();
          emitError(
            "STT_CONNECTION_LOST",
            "Could not initialize voice recording stream.",
          );
        }
      }
    } catch {
      cleanupMedia();
      emitError(
        "STT_CONNECTION_LOST",
        "Could not initialize voice recording stream.",
      );
    }
  }, [cleanupMedia, emitError, openWebSocket, status]);

  const stop = useCallback(async () => {
    if (stoppingRef.current) {
      return;
    }
    stoppingRef.current = true;
    setStatus("processing");

    // Flush any remaining audio samples from the AudioWorklet.
    const worklet = workletNodeRef.current;
    if (worklet) {
      await new Promise<void>((resolve) => {
        const prevHandler = worklet.port.onmessage;
        const timer = window.setTimeout(resolve, 150);
        worklet.port.onmessage = (
          event: MessageEvent<{ type?: string; buffer?: ArrayBuffer }>,
        ) => {
          prevHandler?.call(worklet.port, event);
          if (event.data?.type === "flushed") {
            window.clearTimeout(timer);
            resolve();
          }
        };
        worklet.port.postMessage({ type: "flush" });
      });
    }

    const useHttpFallback = httpFallbackRef.current;
    const httpChunks = useHttpFallback ? frameQueueRef.current.splice(0) : [];

    if (!useHttpFallback) {
      // Wait for queued 1,024-byte frames to drain at 32 ms cadence (never burst).
      await new Promise<void>((resolve) => {
        const checkDrain = () => {
          const ws = wsRef.current;
          if (
            frameQueueRef.current.length === 0 ||
            !ws ||
            ws.readyState !== WebSocket.OPEN
          ) {
            resolve();
            return;
          }
          window.setTimeout(checkDrain, FRAME_PACING_MS);
        };
        checkDrain();
      });
    }

    cleanupMedia();

    if (useHttpFallback) {
      httpFallbackRef.current = false;
      try {
        const pcmBytes = mergePcmChunks(httpChunks);
        const body = pcmBytes.buffer.slice(
          pcmBytes.byteOffset,
          pcmBytes.byteOffset + pcmBytes.byteLength,
        ) as ArrayBuffer;
        const response = await fetch(resolveSttHttpUrl(optionsRef.current), {
          method: "POST",
          headers: { "Content-Type": "application/octet-stream" },
          body,
        });
        const payload = (await response.json().catch(() => ({}))) as {
          segments?: SttTranscriptEvent[];
          detected_language_code?: string;
          audio_ref?: string;
          sha256?: string;
          duration_ms?: number;
          code?: ErrorCode;
          message?: string;
        };
        if (!response.ok) {
          emitError(
            payload.code ?? "STT_CONNECTION_LOST",
            payload.message ?? "Voice transcription upload failed.",
          );
          return;
        }
        const uploadedSegments = Array.isArray(payload.segments)
          ? payload.segments
          : [];
        if (uploadedSegments.length > 0) {
          setSegments(uploadedSegments);
          for (const seg of uploadedSegments) {
            optionsRef.current.onTranscript?.(seg);
          }
        }
        if (payload.detected_language_code) {
          setDetectedLanguage(payload.detected_language_code);
        }
        if (payload.audio_ref && payload.sha256 !== undefined) {
          const saved: SavedAudio = {
            audio_ref: payload.audio_ref,
            sha256: payload.sha256,
            duration_ms: payload.duration_ms ?? 0,
          };
          audioSavedRef.current = true;
          setSavedAudio(saved);
          optionsRef.current.onAudioSaved?.(saved);
        }
      } catch {
        emitError(
          "STT_CONNECTION_LOST",
          "Lost connection while uploading voice recording.",
        );
        return;
      }
      setStatus("idle");
      return;
    }

    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      await new Promise<void>((resolve) => {
        const timeoutId = window.setTimeout(() => {
          endResolveRef.current = null;
          serverErrorRef.current = true;
          emitError(
            "STT_TIMEOUT",
            "Timed out waiting for speech transcription.",
          );
          try {
            ws.close();
          } catch {
            // ignore
          }
          resolve();
        }, FINALIZE_TIMEOUT_MS);

        endResolveRef.current = () => {
          window.clearTimeout(timeoutId);
          resolve();
        };
        ws.send(JSON.stringify({ type: "end" }));
      });
    }

    setStatus((prev) => (prev === "error" ? "error" : "idle"));
  }, [cleanupMedia, emitError]);

  const reset = useCallback(() => {
    stoppingRef.current = true;
    httpFallbackRef.current = false;
    audioSavedRef.current = false;
    serverErrorRef.current = false;
    cleanupMedia();
    if (wsRef.current) {
      try {
        wsRef.current.close(1000);
      } catch {
        // ignore
      }
      wsRef.current = null;
    }
    frameQueueRef.current = [];
    setSegments([]);
    setDetectedLanguage(null);
    setSavedAudio(null);
    setError(null);
    setStatus("idle");
  }, [cleanupMedia]);

  useEffect(() => {
    return () => {
      stoppingRef.current = true;
      cleanupMedia();
      if (wsRef.current) {
        try {
          wsRef.current.close(1000);
        } catch {
          // ignore
        }
      }
    };
  }, [cleanupMedia]);

  const transcript = segments
    .map((s) => s.text.trim())
    .filter(Boolean)
    .join(" ");

  return {
    status,
    transcript,
    segments,
    detectedLanguage,
    savedAudio,
    error,
    start,
    stop,
    reset,
  };
}
