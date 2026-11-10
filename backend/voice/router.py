"""FastAPI router for Developer A's voice endpoints (mounted by backend/app/main.py)."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator
from typing import Literal

from fastapi import (
    APIRouter,
    Depends,
    Query,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .config import VoiceSettings, load_voice_settings
from .confirmation import classify_confirmation
from .errors import ErrorCode, VoiceError, build_error_payload
from .fixtures.fake_voice import FakeVoice
from .gnani_stt import FRAME_BYTES, GnaniSttClient
from .gnani_tts import GnaniTtsClient, TtsAudience
from .models import (
    AudioKind,
    AudioStore,
    ConfirmationResult,
    EntryDraft,
    ExtractContext,
    SupportedLanguage,
    VadMode,
    VoiceService,
    normalize_language,
)
from .normalise import normalise_for_tts
from .service import GnaniVoice
from .storage_stub import ensure_pcm16_16k_wav, get_audio_store

router = APIRouter(tags=["voice"])

_VALID_MODES: set[str] = {"narration", "confirm"}
_VALID_KINDS: set[str] = {"narration", "confirm", "consent", "dispute"}


class TtsRequest(BaseModel):
    text: str = Field(min_length=1)
    lang: str
    voice: str | None = None
    audience: TtsAudience = "worker"


class ExtractRequest(BaseModel):
    transcript: str
    lang: str
    context: ExtractContext = Field(default_factory=ExtractContext)


class ConfirmClassifyRequest(BaseModel):
    transcript: str
    lang: str


class ConfirmClassifyResponse(BaseModel):
    result: ConfirmationResult


def get_voice_settings() -> VoiceSettings:
    """FastAPI dependency returning VoiceSettings (overrideable in tests)."""
    return load_voice_settings()


def get_tts_client(
    settings: VoiceSettings = Depends(get_voice_settings),
) -> GnaniTtsClient:
    """FastAPI dependency returning GnaniTtsClient (overrideable in tests)."""
    return GnaniTtsClient(settings=settings)


def get_voice_service(
    settings: VoiceSettings = Depends(get_voice_settings),
    tts_client: GnaniTtsClient = Depends(get_tts_client),
) -> VoiceService:
    """FastAPI dependency returning FakeVoice or GnaniVoice per VOICE_IMPL."""
    if settings.voice_impl == "fake":
        return FakeVoice()
    return GnaniVoice(settings=settings, tts_client=tts_client)


async def _send_error_and_close(
    websocket: WebSocket, code: ErrorCode, message: str, *, close_code: int = 1008
) -> None:
    try:
        await websocket.send_json(build_error_payload(code, message))
    except Exception:
        pass
    try:
        await websocket.close(code=close_code)
    except Exception:
        pass


def _parse_keyterms_param(raw: str | None) -> list[str] | None:
    if not raw or not raw.strip():
        return None
    text = raw.strip()
    if text.startswith("["):
        try:
            loaded = json.loads(text)
            if isinstance(loaded, list):
                return [str(x) for x in loaded if str(x).strip()]
        except json.JSONDecodeError:
            pass
    return [part.strip() for part in text.split(",") if part.strip()]


def _validate_stt_params(
    lang: str, mode: str, kind: str
) -> tuple[SupportedLanguage, VadMode, AudioKind]:
    norm_lang = normalize_language(lang)
    if mode not in _VALID_MODES:
        raise VoiceError(
            ErrorCode.UNSUPPORTED_LANGUAGE,
            f"Invalid STT mode: {mode}",
            status_code=400,
        )
    if kind not in _VALID_KINDS:
        raise VoiceError(
            ErrorCode.EXTRACTION_FAILED,
            f"Invalid audio kind: {kind}",
            status_code=400,
        )
    return norm_lang, mode, kind  # type: ignore[return-value]


def _fake_stt_transcript(norm_lang: SupportedLanguage, vad_mode: VadMode) -> str:
    if vad_mode == "confirm":
        return "हाँ ठीक है" if norm_lang == "hi-IN" else "yes"
    fake = FakeVoice()
    match = next(
        (f for f in fake.list_fixtures() if f["lang"] == norm_lang),
        fake.list_fixtures()[0],
    )
    return match["transcript"]


@router.websocket("/ws/stt")
async def stt_websocket_proxy(
    websocket: WebSocket,
    lang: str = Query(default="hi-IN"),
    mode: str = Query(default="narration"),
    kind: str = Query(default="narration"),
    keyterms: str | None = Query(default=None),
    audio_store: AudioStore = Depends(get_audio_store),
    settings: VoiceSettings = Depends(get_voice_settings),
) -> None:
    """Proxy browser PCM16 audio frames to Gnani STT (or FakeVoice) and save WAV on end."""
    await websocket.accept()

    try:
        norm_lang, vad_mode, audio_kind = _validate_stt_params(lang, mode, kind)
    except VoiceError as err:
        await _send_error_and_close(websocket, err.code, err.message)
        return

    parsed_keyterms = _parse_keyterms_param(keyterms)

    recorded_pcm = bytearray()
    pcm_queue: asyncio.Queue[bytes | None] = asyncio.Queue()
    client_ended = False
    upstream_done = False

    async def _read_browser_frames() -> None:
        nonlocal client_ended
        try:
            while True:
                msg = await websocket.receive()
                msg_type = msg.get("type")
                if msg_type == "websocket.disconnect":
                    break
                if msg.get("bytes") is not None:
                    chunk = msg["bytes"]
                    if chunk:
                        recorded_pcm.extend(chunk)
                        if not upstream_done:
                            await pcm_queue.put(chunk)
                elif msg.get("text") is not None:
                    try:
                        ctrl = json.loads(msg["text"])
                    except json.JSONDecodeError:
                        ctrl = {}
                    if isinstance(ctrl, dict) and ctrl.get("type") == "end":
                        client_ended = True
                        break
        except WebSocketDisconnect:
            pass
        finally:
            await pcm_queue.put(None)

    async def _pcm_iter() -> AsyncIterator[bytes]:
        while True:
            chunk = await pcm_queue.get()
            if chunk is None:
                break
            yield chunk

    reader_task: asyncio.Task[None] | None = None
    try:
        await websocket.send_json({"type": "processing"})
        reader_task = asyncio.create_task(_read_browser_frames())

        if settings.voice_impl == "fake":
            # Drain audio frames from browser and return fixture transcript without network.
            async for _ in _pcm_iter():
                pass
            fake_text = _fake_stt_transcript(norm_lang, vad_mode)
            await websocket.send_json(
                {
                    "type": "transcript",
                    "text": fake_text,
                    "detected_language_code": norm_lang,
                    "segment_index": 1,
                    "latency_ms": 15,
                }
            )
        else:
            client = GnaniSttClient(settings=settings)
            transcript_count = 0
            try:
                async for evt in client.transcribe_pcm_stream(
                    _pcm_iter(),
                    norm_lang,
                    vad_mode,
                    keyterms=parsed_keyterms,
                ):
                    await websocket.send_json(
                        {
                            "type": "transcript",
                            "text": evt.text,
                            "detected_language_code": evt.detected_language_code,
                            "segment_index": evt.segment_index,
                            "latency_ms": evt.latency_ms,
                        }
                    )
                    transcript_count += 1
            except VoiceError as err:
                # Upstream STT can close or time out after delivering usable transcript(s);
                # finish draining browser audio so saved WAV + audio_saved still complete cleanly.
                if transcript_count == 0 or err.code not in (
                    ErrorCode.STT_CONNECTION_LOST,
                    ErrorCode.STT_TIMEOUT,
                ):
                    raise
            finally:
                upstream_done = True

        await reader_task
        if client_ended or recorded_pcm:
            wav_bytes, _ = ensure_pcm16_16k_wav(bytes(recorded_pcm))
            saved = await audio_store.save_audio(wav_bytes, audio_kind)
            await websocket.send_json(
                {
                    "type": "audio_saved",
                    "audio_ref": saved.audio_ref,
                    "sha256": saved.sha256,
                    "duration_ms": saved.duration_ms,
                }
            )
        await websocket.close(code=1000)
    except VoiceError as err:
        await _send_error_and_close(websocket, err.code, err.message)
    except Exception:
        await _send_error_and_close(
            websocket, ErrorCode.STT_CONNECTION_LOST, "STT proxy session failed."
        )
    finally:
        if reader_task is not None and not reader_task.done():
            reader_task.cancel()


@router.post("/api/voice/stt")
async def transcribe_pcm_upload(
    request: Request,
    lang: str = Query(default="hi-IN"),
    mode: str = Query(default="narration"),
    kind: str = Query(default="narration"),
    keyterms: str | None = Query(default=None),
    audio_store: AudioStore = Depends(get_audio_store),
    settings: VoiceSettings = Depends(get_voice_settings),
) -> JSONResponse:
    """HTTP fallback STT upload for serverless hosts without inbound WebSockets."""
    try:
        norm_lang, vad_mode, audio_kind = _validate_stt_params(lang, mode, kind)
        parsed_keyterms = _parse_keyterms_param(keyterms)
        pcm_bytes = await request.body()

        segments: list[dict[str, object]] = []
        if settings.voice_impl == "fake":
            segments.append(
                {
                    "type": "transcript",
                    "text": _fake_stt_transcript(norm_lang, vad_mode),
                    "detected_language_code": norm_lang,
                    "segment_index": 1,
                    "latency_ms": 15,
                }
            )
        else:

            async def _pcm_frames() -> AsyncIterator[bytes]:
                for offset in range(0, len(pcm_bytes), FRAME_BYTES):
                    yield pcm_bytes[offset : offset + FRAME_BYTES]

            client = GnaniSttClient(settings=settings)
            try:
                async for evt in client.transcribe_pcm_stream(
                    _pcm_frames(),
                    norm_lang,
                    vad_mode,
                    keyterms=parsed_keyterms,
                ):
                    segments.append(
                        {
                            "type": "transcript",
                            "text": evt.text,
                            "detected_language_code": evt.detected_language_code,
                            "segment_index": evt.segment_index,
                            "latency_ms": evt.latency_ms,
                        }
                    )
            except VoiceError as err:
                if not segments or err.code not in (
                    ErrorCode.STT_CONNECTION_LOST,
                    ErrorCode.STT_TIMEOUT,
                ):
                    raise

        wav_bytes, _ = ensure_pcm16_16k_wav(pcm_bytes)
        saved = await audio_store.save_audio(wav_bytes, audio_kind)
        detected_lang = (
            str(segments[-1]["detected_language_code"]) if segments else norm_lang
        )
        return JSONResponse(
            content={
                "segments": segments,
                "detected_language_code": detected_lang,
                "audio_ref": saved.audio_ref,
                "sha256": saved.sha256,
                "duration_ms": saved.duration_ms,
            }
        )
    except VoiceError as err:
        return JSONResponse(status_code=err.status_code, content=err.to_payload())
    except Exception:
        return JSONResponse(
            status_code=500,
            content=build_error_payload(
                ErrorCode.STT_CONNECTION_LOST, "STT upload failed unexpectedly."
            ),
        )


@router.post("/api/voice/tts")
async def synthesize_speech(
    body: TtsRequest,
    settings: VoiceSettings = Depends(get_voice_settings),
    tts_client: GnaniTtsClient = Depends(get_tts_client),
) -> Response:
    """Synthesize spoken read-back or prompt audio with disk caching headers."""
    try:
        if settings.voice_impl == "fake":
            norm_lang = normalize_language(body.lang)
            norm_text = normalise_for_tts(body.text, norm_lang)
            audio_bytes = await FakeVoice().synthesize(norm_text, norm_lang, body.voice)
            digest = hashlib.sha256(audio_bytes).hexdigest()
            return Response(
                content=audio_bytes,
                media_type="audio/wav",
                headers={
                    "Cache-Control": "public, max-age=86400",
                    "ETag": f'"{digest}"',
                    "X-TTS-Cache": "FAKE",
                },
            )

        res = await tts_client.synthesize_with_meta(
            body.text,
            body.lang,
            voice=body.voice,
            audience=body.audience,
        )
        return Response(
            content=res.audio_bytes,
            media_type=res.content_type,
            headers={
                "Cache-Control": "public, max-age=86400",
                "ETag": f'"{res.cache_key}"',
                "X-TTS-Cache": "HIT" if res.cache_hit else "MISS",
            },
        )
    except VoiceError as err:
        return JSONResponse(status_code=err.status_code, content=err.to_payload())
    except Exception:
        return JSONResponse(
            status_code=500,
            content=build_error_payload(
                ErrorCode.TTS_FAILED, "TTS synthesis failed unexpectedly."
            ),
        )


@router.post("/api/voice/extract", response_model=EntryDraft)
async def extract_entry_endpoint(
    body: ExtractRequest,
    voice_service: VoiceService = Depends(get_voice_service),
) -> EntryDraft | JSONResponse:
    """Extract structured EntryDraft from transcript using FakeVoice or GnaniVoice."""
    try:
        return await voice_service.extract_entry(
            body.transcript, body.lang, body.context
        )
    except VoiceError as err:
        return JSONResponse(status_code=err.status_code, content=err.to_payload())
    except Exception:
        return JSONResponse(
            status_code=500,
            content=build_error_payload(
                ErrorCode.EXTRACTION_FAILED, "Entry extraction failed unexpectedly."
            ),
        )


@router.post("/api/voice/classify-confirmation", response_model=ConfirmClassifyResponse)
async def classify_confirmation_endpoint(
    body: ConfirmClassifyRequest,
) -> ConfirmClassifyResponse | JSONResponse:
    """Classify a yes/no/unclear confirmation utterance."""
    try:
        return ConfirmClassifyResponse(
            result=classify_confirmation(body.transcript, body.lang)
        )
    except VoiceError as err:
        return JSONResponse(status_code=err.status_code, content=err.to_payload())
    except Exception:
        return JSONResponse(
            status_code=500,
            content=build_error_payload(
                ErrorCode.EXTRACTION_FAILED, "Confirmation classification failed."
            ),
        )
