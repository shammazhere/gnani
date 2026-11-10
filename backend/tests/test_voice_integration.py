from __future__ import annotations

import io
import os
import sys
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
os.environ.setdefault("SECRET_KEY", "tests-only-random-secret-key-0123456789abcd")

import main
from app.models import Base
from app.routers import auth, contractor, entries, evidence


@pytest.fixture
def integrated_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("VOICE_IMPL", "fake")
    auth.login_rate_limiter.reset()
    db_path = tmp_path / "integration.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    api = main.create_application()
    for mod in (auth, entries, contractor, evidence):
        api.dependency_overrides[mod.get_db] = override_get_db

    monkeypatch.setattr(main, "engine", engine)
    monkeypatch.chdir(tmp_path)
    with TestClient(api) as tc:
        try:
            yield tc, tmp_path
        finally:
            engine.dispose()
            auth.login_rate_limiter.reset()


def test_voice_router_mounted_and_full_stt_extract_draft_confirm_evidence_flow(
    integrated_client: tuple[TestClient, Path],
):
    tc, tmp_path = integrated_client

    reg = tc.post(
        "/api/auth/register",
        json={"alias": "voice-worker", "pin": "1234", "language": "hi-IN"},
    )
    assert reg.status_code == 201
    token = reg.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 1) Stream PCM frames over /ws/stt -> real AppAudioStore saves WAV & returns audio_saved
    pcm_chunk = b"\x00\x01" * 512  # 1,024 bytes (32ms @ 16kHz PCM16)
    transcript = ""
    saved_audio: dict | None = None
    with tc.websocket_connect("/ws/stt?lang=hi-IN&mode=narration&kind=narration") as ws:
        ws.send_bytes(pcm_chunk)
        ws.send_bytes(pcm_chunk)
        ws.send_text('{"type":"end"}')
        while True:
            msg = ws.receive_json()
            if msg["type"] == "transcript":
                transcript = msg["text"]
            elif msg["type"] == "audio_saved":
                saved_audio = msg
                break

    assert transcript
    assert saved_audio is not None
    assert Path(saved_audio["audio_ref"]).is_file()
    assert len(saved_audio["sha256"]) == 64

    # 2) Extract structured wage entry via /api/voice/extract
    ext = tc.post(
        "/api/voice/extract",
        json={"transcript": transcript, "lang": "hi-IN", "context": {}},
    )
    assert ext.status_code == 200
    draft = ext.json()

    # 3) Save draft + confirm into hash chain -> verify -> export pack containing recorded WAV
    created = tc.post(
        "/api/entries/draft",
        headers=headers,
        json={
            "audio_ref": saved_audio["audio_ref"],
            "audio_sha256": saved_audio["sha256"],
            "transcript": transcript,
            "lang": "hi-IN",
            "work_date": draft["work_date"],
            "site_name": draft["site_name"],
            "counterparty_name": draft["counterparty_name"],
            "hours": draft["hours"],
            "agreed_inr": draft["agreed_amount_inr"],
            "paid_inr": draft["paid_amount_inr"],
        },
    )
    assert created.status_code == 201
    entry = created.json()
    assert entry["due_inr"] == max(0.0, float(draft["agreed_amount_inr"] or 0) - float(draft["paid_amount_inr"] or 0))

    confirmed = tc.post(f"/api/entries/{entry['id']}/confirm", headers=headers)
    assert confirmed.status_code == 200

    verified = tc.get("/api/verify", headers=headers)
    assert verified.status_code == 200 and verified.json()["valid"] is True

    pack_res = tc.post(
        "/api/evidence",
        headers=headers,
        json={"period_from": "2000-01-01", "period_to": "2099-12-31"},
    )
    assert pack_res.status_code == 200
    pack = pack_res.json()

    zip_res = tc.get(pack["zip_download_url"], headers=headers)
    assert zip_res.status_code == 200
    with zipfile.ZipFile(io.BytesIO(zip_res.content)) as zf:
        assert any(Path(saved_audio["audio_ref"]).name in name for name in zf.namelist())

    # 4) TTS & confirmation classification endpoints work through main app
    cls_res = tc.post("/api/voice/classify-confirmation", json={"transcript": "haan thik hai", "lang": "hi-IN"})
    assert cls_res.status_code == 200 and cls_res.json()["result"] == "yes"

    tts_res = tc.post("/api/voice/tts", json={"text": "Suresh ke paas 400 baaki", "lang": "hi-IN"})
    assert tts_res.status_code == 200 and len(tts_res.content) > 0


def test_vercel_entrypoint_and_quoted_database_url() -> None:
    import vercel_app
    from app import main as app_main
    from app.db import normalize_database_url

    assert vercel_app.app is app_main.app
    route_paths = {getattr(r, "path", None) for r in vercel_app.app.routes}
    assert "/api/health" in route_paths
    assert "/api/voice/stt" in route_paths
    assert normalize_database_url(
        '  "postgres://u:p@ep.neon.tech/neondb?sslmode=require" '
    ) == ("postgresql+psycopg://u:p@ep.neon.tech/neondb?sslmode=require")
