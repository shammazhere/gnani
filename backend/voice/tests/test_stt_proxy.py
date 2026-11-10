"""Tests for P5 STT proxy using a local fake Gnani WebSocket server (zero network)."""

from __future__ import annotations

import asyncio
import json
import wave
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
import websockets
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.voice.config import VadPreset, VoiceSettings, load_voice_settings
from backend.voice.errors import ErrorCode
from backend.voice.gnani_stt import GnaniSttClient, build_stt_headers
from backend.voice.models import AudioKind, SavedAudio
from backend.voice.router import get_voice_settings, router
from backend.voice.storage_stub import LocalAudioStore, get_audio_store


def _make_settings(
    tmp_path: Path,
    *,
    wss_url: str = "ws://127.0.0.1:0",
    voice_impl: str = "gnani",
    header_style: str = "legacy",
    keyterms_enabled: bool = False,
) -> VoiceSettings:
    return replace(
        load_voice_settings(load_env_files=False),
        voice_impl=voice_impl,
        gnani_api_key="test-key-never-logged",
        gnani_header_style=header_style,  # type: ignore[arg-type]
        gnani_stt_wss_url=wss_url,
        tts_cache_dir=tmp_path / "tts_cache",
        audio_stub_dir=tmp_path / "audio",
        keyterms_enabled=keyterms_enabled,
        llm_enabled=False,
        llm_provider="none",
        stt_timeout_s=5.0,
        vad_narration=VadPreset(min_silence_ms=700, vad_threshold=0.6),
        vad_confirm=VadPreset(min_silence_ms=300, min_speech_ms=100, min_segment_ms=100),
    )


def test_build_stt_headers_legacy_new_and_keyterms(tmp_path: Path) -> None:
    legacy_cfg = _make_settings(tmp_path, header_style="legacy", keyterms_enabled=True)
    h_legacy = build_stt_headers(
        legacy_cfg, "hi-IN", "narration", keyterms=["सुरेश", "Basavanagudi"]
    )
    assert h_legacy["x-model"] == "prisma-v3.0"
    assert h_legacy["lang_code"] == "hi-IN"
    assert h_legacy["x-format"] == "transcribe"
    assert h_legacy["x-sample-rate"] == "16000"
    assert h_legacy["x-min-silence-ms"] == "700"
    assert h_legacy["x-vad-threshold"] == "0.6"
    assert "\\u" in h_legacy["x-keyterms"]

    h_confirm = build_stt_headers(legacy_cfg, "kn-IN", "confirm")
    assert h_confirm["x-min-silence-ms"] == "300"
    assert h_confirm["x-min-speech-ms"] == "100"
    assert h_confirm["x-min-segment-ms"] == "100"

    new_cfg = _make_settings(tmp_path, header_style="new", keyterms_enabled=True)
    h_new = build_stt_headers(new_cfg, "bn-IN", "narration", keyterms=["অমিত"])
    assert h_new["model"] == "prisma-v3.0"
    assert h_new["language_code"] == "bn-IN"
    assert h_new["format"] == "transcribe"
    assert "\\u" in h_new["keyterms"]
    assert "x-model" not in h_new


@pytest.mark.asyncio
async def test_stt_client_429_backoff_and_language_fallback(tmp_path: Path) -> None:
    attempts = 0
    seen_headers: list[dict[str, str]] = []
    seen_frame_sizes: list[int] = []

    async def process_request(connection: Any, request: Any) -> Any:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return connection.respond(429, json.dumps({"detail": {"error_code": "RATE_LIMITED"}}))
        return None

    async def handler(ws: Any) -> None:
        seen_headers.append({k.lower(): v for k, v in ws.request.headers.items()})
        async for msg in ws:
            if isinstance(msg, bytes):
                seen_frame_sizes.append(len(msg))
                if len(seen_frame_sizes) == 2:
                    # Interim is_final=False should be skipped; final segment forwarded.
                    await ws.send(
                        json.dumps(
                            {
                                "text": "700",
                                "is_final": False,
                                "detected_language_code": "hi-IN",
                                "segment_index": 1,
                            }
                        )
                    )
                    # Short Marathi tag fallback when profile is hi-IN
                    await ws.send(
                        json.dumps(
                            {
                                "transcript": "700 रुपये",
                                "is_final": True,
                                "detected_language_code": "mr-IN",
                                "segment_index": 1,
                            }
                        )
                    )
                    await ws.close()
                    break

    server = await websockets.serve(handler, "127.0.0.1", 0, process_request=process_request)
    port = server.sockets[0].getsockname()[1]
    try:
        cfg = _make_settings(tmp_path, wss_url=f"ws://127.0.0.1:{port}")
        client = GnaniSttClient(
            settings=cfg,
            max_retries=3,
            backoff_base_s=0.01,
            frame_interval_s=0.001,
            trailing_silence_frames=2,
        )

        async def chunks() -> Any:
            yield b"\x01\x00" * 800  # 1,600 bytes -> 1,024 + padded 1,024

        events = [e async for e in client.transcribe_pcm_stream(chunks(), "hi-IN", "narration")]
        assert attempts == 3
        assert len(events) == 1
        assert events[0].text == "700 रुपये"
        assert events[0].detected_language_code == "hi-IN"
        assert all(sz == 1024 for sz in seen_frame_sizes)
        assert seen_headers[0]["x-model"] == "prisma-v3.0"
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_ws_stt_proxy_saves_wav_and_forwards_transcript(tmp_path: Path) -> None:
    received_frames: list[int] = []

    async def fake_gnani_handler(ws: Any) -> None:
        async for msg in ws:
            if isinstance(msg, bytes):
                received_frames.append(len(msg))
                if len(received_frames) == 2:
                    await ws.send(
                        json.dumps(
                            {
                                "transcript": "Suresh ne 700 bola",
                                "detected_language_code": "hi-IN",
                                "segment_index": 1,
                            }
                        )
                    )
                    await ws.close()
                    break

    server = await websockets.serve(fake_gnani_handler, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        app = FastAPI()
        app.include_router(router)
        settings = _make_settings(tmp_path, wss_url=f"ws://127.0.0.1:{port}")
        store = LocalAudioStore(base_dir=tmp_path / "audio")
        app.dependency_overrides[get_voice_settings] = lambda: settings
        app.dependency_overrides[get_audio_store] = lambda: store

        import backend.voice.router as voice_router_mod

        orig_cls = voice_router_mod.GnaniSttClient
        voice_router_mod.GnaniSttClient = lambda settings: orig_cls(  # type: ignore[misc, assignment]
            settings=settings, frame_interval_s=0.001, trailing_silence_frames=1
        )
        try:
            def _run_client() -> list[dict[str, Any]]:
                with TestClient(app) as tc:
                    with tc.websocket_connect("/ws/stt?lang=hi-IN&mode=narration&kind=consent") as ws:
                        msg0 = ws.receive_json()
                        assert msg0 == {"type": "processing"}

                        frame = b"\x02\x00" * 512  # 1,024 bytes = 32 ms
                        ws.send_bytes(frame)
                        ws.send_bytes(frame)
                        ws.send_text(json.dumps({"type": "end"}))

                        collected: list[dict[str, Any]] = []
                        while True:
                            try:
                                collected.append(ws.receive_json())
                            except Exception:
                                break
                        return collected

            events = await asyncio.to_thread(_run_client)
            transcripts = [e for e in events if e.get("type") == "transcript"]
            saved = [e for e in events if e.get("type") == "audio_saved"]
            assert len(transcripts) == 1
            assert transcripts[0]["text"] == "Suresh ne 700 bola"
            assert transcripts[0]["detected_language_code"] == "hi-IN"
            assert len(saved) == 1
            assert saved[0]["audio_ref"].startswith("local://consent/")
            assert saved[0]["duration_ms"] == 64

            saved_file = tmp_path / "audio" / "consent" / saved[0]["audio_ref"].split("/")[-1]
            with wave.open(str(saved_file), "rb") as wf:
                assert wf.getframerate() == 16_000
                assert wf.getnchannels() == 1
                assert wf.getsampwidth() == 2
        finally:
            voice_router_mod.GnaniSttClient = orig_cls
    finally:
        server.close()
        await server.wait_closed()


def test_ws_stt_unsupported_language_returns_error_code(tmp_path: Path) -> None:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_voice_settings] = lambda: _make_settings(
        tmp_path, voice_impl="fake"
    )
    app.dependency_overrides[get_audio_store] = lambda: LocalAudioStore(tmp_path / "audio")

    with TestClient(app) as tc:
        with tc.websocket_connect("/ws/stt?lang=or-IN&mode=narration&kind=narration") as ws:
            err = ws.receive_json()
            assert err["type"] == "error"
            assert err["code"] == ErrorCode.UNSUPPORTED_LANGUAGE.value


def test_ws_stt_unhandled_storage_exception_emits_error_code(tmp_path: Path) -> None:
    class BrokenStore:
        async def save_audio(self, data: bytes, kind: AudioKind) -> SavedAudio:
            raise RuntimeError("disk full")

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_voice_settings] = lambda: _make_settings(
        tmp_path, voice_impl="fake"
    )
    app.dependency_overrides[get_audio_store] = lambda: BrokenStore()

    with TestClient(app) as tc:
        with tc.websocket_connect("/ws/stt?lang=hi-IN&mode=narration&kind=narration") as ws:
            assert ws.receive_json() == {"type": "processing"}
            ws.send_bytes(b"\x01\x00" * 512)
            ws.send_text(json.dumps({"type": "end"}))
            msgs = []
            while True:
                try:
                    msgs.append(ws.receive_json())
                except Exception:
                    break
            errors = [m for m in msgs if m.get("type") == "error"]
            assert len(errors) == 1
            assert errors[0]["code"] == ErrorCode.STT_CONNECTION_LOST.value


@pytest.mark.asyncio
async def test_stt_client_send_timeout_maps_to_stt_timeout(tmp_path: Path) -> None:
    async def slow_handler(ws: Any) -> None:
        await asyncio.sleep(0.5)

    server = await websockets.serve(slow_handler, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        cfg = replace(
            _make_settings(tmp_path, wss_url=f"ws://127.0.0.1:{port}"),
            stt_timeout_s=0.05,
        )
        client = GnaniSttClient(
            settings=cfg, frame_interval_s=0.001, trailing_silence_frames=1
        )
        # Monkeypatch ws.send after connect by testing timeout inside _receiver wait_for
        async def chunks() -> Any:
            yield b"\x01\x00" * 512

        with pytest.raises(Exception) as exc:
            async for _ in client.transcribe_pcm_stream(chunks(), "hi-IN", "narration"):
                pass
        assert getattr(exc.value, "code", None) == ErrorCode.STT_TIMEOUT
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_ws_stt_proxy_settles_when_gnani_stays_open_after_transcript(tmp_path: Path) -> None:
    """Persistent STT WS stays open after final transcript; proxy must still emit audio_saved."""
    received_frames = 0

    async def persistent_gnani_handler(ws: Any) -> None:
        nonlocal received_frames
        async for msg in ws:
            if isinstance(msg, bytes):
                received_frames += 1
                if received_frames == 2:
                    await ws.send(
                        json.dumps(
                            {
                                "transcript": "Shamaz agreed 10000 rupees",
                                "detected_language_code": "en-IN",
                                "segment_index": 1,
                            }
                        )
                    )
                    # Intentionally keep the WS open while trailing silence arrives,
                    # mirroring Gnani's persistent streaming STT server.

    server = await websockets.serve(persistent_gnani_handler, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        app = FastAPI()
        app.include_router(router)
        settings = _make_settings(tmp_path, wss_url=f"ws://127.0.0.1:{port}")
        store = LocalAudioStore(base_dir=tmp_path / "audio")
        app.dependency_overrides[get_voice_settings] = lambda: settings
        app.dependency_overrides[get_audio_store] = lambda: store

        import backend.voice.router as voice_router_mod

        orig_cls = voice_router_mod.GnaniSttClient
        voice_router_mod.GnaniSttClient = lambda settings: orig_cls(  # type: ignore[misc, assignment]
            settings=settings,
            frame_interval_s=0.001,
            trailing_silence_frames=1,
            post_end_flush_s=0.05,
        )
        try:
            def _run_client() -> list[dict[str, Any]]:
                with TestClient(app) as tc:
                    with tc.websocket_connect("/ws/stt?lang=en-IN&mode=narration&kind=narration") as ws:
                        assert ws.receive_json() == {"type": "processing"}
                        frame = b"\x02\x00" * 512
                        ws.send_bytes(frame)
                        ws.send_bytes(frame)
                        ws.send_text(json.dumps({"type": "end"}))
                        collected: list[dict[str, Any]] = []
                        while True:
                            try:
                                collected.append(ws.receive_json())
                            except Exception:
                                break
                        return collected

            events = await asyncio.wait_for(asyncio.to_thread(_run_client), timeout=3.0)
            assert [e["text"] for e in events if e.get("type") == "transcript"] == [
                "Shamaz agreed 10000 rupees"
            ]
            assert [e for e in events if e.get("type") == "error"] == []
            saved = [e for e in events if e.get("type") == "audio_saved"]
            assert len(saved) == 1
            assert saved[0]["audio_ref"].startswith("local://narration/")
        finally:
            voice_router_mod.GnaniSttClient = orig_cls
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_ws_stt_proxy_saves_audio_when_upstream_closes_uncleanly_after_transcript(
    tmp_path: Path,
) -> None:
    """If upstream STT drops unexpectedly after delivering a transcript, audio_saved still emits."""
    received_frames = 0

    async def abrupt_gnani_handler(ws: Any) -> None:
        nonlocal received_frames
        async for msg in ws:
            if isinstance(msg, bytes):
                received_frames += 1
                if received_frames == 2:
                    await ws.send(
                        json.dumps(
                            {
                                "transcript": "Paid 10 rupees",
                                "detected_language_code": "en-IN",
                                "segment_index": 1,
                            }
                        )
                    )
                    await ws.close(code=1011, reason="upstream idle drop")
                    break

    server = await websockets.serve(abrupt_gnani_handler, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        app = FastAPI()
        app.include_router(router)
        settings = _make_settings(tmp_path, wss_url=f"ws://127.0.0.1:{port}")
        store = LocalAudioStore(base_dir=tmp_path / "audio")
        app.dependency_overrides[get_voice_settings] = lambda: settings
        app.dependency_overrides[get_audio_store] = lambda: store

        import backend.voice.router as voice_router_mod

        orig_cls = voice_router_mod.GnaniSttClient
        voice_router_mod.GnaniSttClient = lambda settings: orig_cls(  # type: ignore[misc, assignment]
            settings=settings,
            frame_interval_s=0.001,
            trailing_silence_frames=1,
            post_end_flush_s=0.05,
        )
        try:
            def _run_client() -> list[dict[str, Any]]:
                with TestClient(app) as tc:
                    with tc.websocket_connect("/ws/stt?lang=en-IN&mode=narration&kind=narration") as ws:
                        assert ws.receive_json() == {"type": "processing"}
                        frame = b"\x02\x00" * 512
                        ws.send_bytes(frame)
                        ws.send_bytes(frame)
                        ws.send_text(json.dumps({"type": "end"}))
                        collected: list[dict[str, Any]] = []
                        while True:
                            try:
                                collected.append(ws.receive_json())
                            except Exception:
                                break
                        return collected

            events = await asyncio.wait_for(asyncio.to_thread(_run_client), timeout=3.0)
            assert [e["text"] for e in events if e.get("type") == "transcript"] == [
                "Paid 10 rupees"
            ]
            assert [e for e in events if e.get("type") == "error"] == []
            saved = [e for e in events if e.get("type") == "audio_saved"]
            assert len(saved) == 1
        finally:
            voice_router_mod.GnaniSttClient = orig_cls
    finally:
        server.close()
        await server.wait_closed()


def test_http_stt_upload_fake_and_invalid_params(tmp_path: Path) -> None:
    app = FastAPI()
    app.include_router(router)
    settings = _make_settings(tmp_path, voice_impl="fake")
    store = LocalAudioStore(base_dir=tmp_path / "audio")
    app.dependency_overrides[get_voice_settings] = lambda: settings
    app.dependency_overrides[get_audio_store] = lambda: store

    with TestClient(app) as tc:
        res = tc.post(
            "/api/voice/stt?lang=hi-IN&mode=narration&kind=narration",
            content=b"\x01\x00" * 512,
        )
        assert res.status_code == 200
        body = res.json()
        assert len(body["segments"]) == 1
        assert body["segments"][0]["text"]
        assert body["detected_language_code"] == "hi-IN"
        assert body["audio_ref"]
        assert len(body["sha256"]) == 64

        bad = tc.post(
            "/api/voice/stt?lang=hi-IN&mode=bogus&kind=narration", content=b""
        )
        assert bad.status_code == 400
        assert bad.json()["code"] == ErrorCode.UNSUPPORTED_LANGUAGE.value


@pytest.mark.asyncio
async def test_http_stt_upload_streams_to_upstream_gnani(tmp_path: Path) -> None:
    async def handler(websocket: Any) -> None:
        while True:
            msg = await websocket.recv()
            if isinstance(msg, bytes):
                if msg == b"\x00" * 1024:
                    break
        await websocket.send(
            json.dumps(
                {
                    "type": "transcript",
                    "transcript": "700 rupees today",
                    "language": "en-IN",
                }
            )
        )
        await asyncio.sleep(0.02)

    server = await websockets.serve(handler, "127.0.0.1", 0)
    try:
        port = server.sockets[0].getsockname()[1]
        app = FastAPI()
        app.include_router(router)
        settings = _make_settings(tmp_path, wss_url=f"ws://127.0.0.1:{port}")
        store = LocalAudioStore(base_dir=tmp_path / "audio")
        app.dependency_overrides[get_voice_settings] = lambda: settings
        app.dependency_overrides[get_audio_store] = lambda: store

        import backend.voice.router as voice_router_mod

        orig_cls = voice_router_mod.GnaniSttClient
        voice_router_mod.GnaniSttClient = lambda settings: orig_cls(  # type: ignore[misc, assignment]
            settings=settings,
            frame_interval_s=0.001,
            trailing_silence_frames=1,
            post_end_flush_s=0.05,
        )
        try:

            def _post_audio() -> dict[str, Any]:
                with TestClient(app) as tc:
                    resp = tc.post(
                        "/api/voice/stt?lang=en-IN&mode=narration&kind=narration",
                        content=b"\x02\x00" * 1024,
                    )
                    assert resp.status_code == 200
                    return resp.json()

            data = await asyncio.wait_for(asyncio.to_thread(_post_audio), timeout=3.0)
            assert [s["text"] for s in data["segments"]] == ["700 rupees today"]
            assert data["detected_language_code"] == "en-IN"
            assert data["audio_ref"]
        finally:
            voice_router_mod.GnaniSttClient = orig_cls
    finally:
        server.close()
        await server.wait_closed()
