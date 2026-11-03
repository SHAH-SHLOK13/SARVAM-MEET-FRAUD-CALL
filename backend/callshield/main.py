"""CallShield backend. Run:  uvicorn callshield.main:create_app --factory --port 8000"""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import logging
import os
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .adapter import AIPipeline, MockPipeline, load_pipeline
from .contracts import SCHEMA_VERSION, now_ms
from .fusion import load_risk_config
from .hub import Hub
from . import demo
from .ai.summary import summarize
from .report import build_report, report_markdown
from .session import Deps, SessionManager
from .store import Store

log = logging.getLogger("callshield")
FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
SESSION_ID_RE = r"^[A-Za-z0-9_.-]{1,64}$"
TICK_S = 2.0
# Usage caps: the shared demo token is public, so bound what anyone holding it can spend.
MAX_ACTIVE_SESSIONS = int(os.environ.get("CALLSHIELD_MAX_ACTIVE", "6"))
MAX_SESSION_S = int(os.environ.get("CALLSHIELD_MAX_SESSION_S", "1800"))
MAX_SESSIONS_PER_DAY = int(os.environ.get("CALLSHIELD_MAX_SESSIONS_PER_DAY", "150"))


class InjectText(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    speaker_role: str = Field(default="remote", pattern="^(remote|local|unknown)$")


def create_app(*, config_path: str | None = None, pipeline: AIPipeline | None = None,
               db_path: str | None = None, token: str | None = None,
               tick_s: float = TICK_S) -> FastAPI:
    logging.basicConfig(level=logging.INFO)
    load_dotenv(ENV_FILE)
    cfg = load_risk_config(config_path or os.environ.get("CALLSHIELD_RISK_CONFIG"))
    api_token = token or os.environ.get("CALLSHIELD_TOKEN", "dev-token")
    if pipeline is None:
        pipeline = load_pipeline(os.environ.get("CALLSHIELD_PIPELINE"))
    if hasattr(pipeline, "configure"):
        pipeline.configure(cfg)
    if isinstance(pipeline, MockPipeline) and not pipeline.rule_refs:
        pipeline.rule_refs = {k: v.rules for k, v in cfg.categories.items()}
    log.info("AI pipeline: %s (mock=%s)", pipeline.name, pipeline.is_mock)
    store = Store(db_path or os.environ.get("CALLSHIELD_DB", "callshield.db"))
    hub = Hub()
    manager = SessionManager(Deps(cfg=cfg, store=store, hub=hub, pipeline=pipeline))

    async def ticker():
        while True:
            await asyncio.sleep(tick_s)
            try:
                await manager.tick()
            except Exception:  # noqa: BLE001
                log.exception("tick failed")
            # Duration cap, enforced even if the tick above failed.
            cutoff = now_ms() - MAX_SESSION_S * 1000
            for s in list(manager.sessions.values()):
                if s.active and s.created_ms < cutoff:
                    log.warning("session %s hit the %ss cap; stopping", s.id, MAX_SESSION_S)
                    try:
                        await s.stop()
                    except Exception:  # noqa: BLE001
                        log.exception("stopping %s failed", s.id)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task = asyncio.create_task(ticker())
        yield
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        await manager.shutdown()
        store.close()

    app = FastAPI(title="CallShield", lifespan=lifespan)
    app.state.manager = manager
    app.state.store = store
    app.state.cfg = cfg

    def token_ok(t: str | None) -> bool:
        return bool(t) and hmac.compare_digest(t, api_token)

    def require_token(token: str | None = Query(default=None),
                      authorization: str | None = Header(default=None)) -> None:
        t = token
        if authorization and authorization.lower().startswith("bearer "):
            t = authorization[7:]
        if not token_ok(t):
            raise HTTPException(401, "invalid token")

    auth = [Depends(require_token)]
    day_count = {"day": "", "n": 0}

    def admit_new_session() -> bool:
        if sum(1 for s in manager.sessions.values() if s.active) >= MAX_ACTIVE_SESSIONS:
            return False
        today = time.strftime("%Y-%m-%d")
        if day_count["day"] != today:
            day_count.update(day=today, n=0)
        if day_count["n"] >= MAX_SESSIONS_PER_DAY:
            return False
        day_count["n"] += 1
        return True

    demo_tasks: set[asyncio.Task] = set()

    @app.post("/api/demo/start", dependencies=auth)
    async def demo_start(scenario: str = "scam") -> dict[str, Any]:
        """One-click demo: replays a recorded call through the live pipeline (see demo.py)."""
        if scenario not in demo.SCENARIOS:
            raise HTTPException(404, "unknown scenario")
        if not demo.can_start() or not admit_new_session():
            raise HTTPException(429, "a demo is already running or the usage cap is reached; try again in a minute")
        sid = demo.new_session_id()
        demo.reserve(sid)  # before any await: concurrent requests see the slot as taken
        task = asyncio.create_task(demo.run(manager, scenario, sid))
        demo_tasks.add(task)
        task.add_done_callback(demo_tasks.discard)
        pcm_s = demo.duration_s(scenario)
        return {"session_id": sid, "label": demo.SCENARIOS[scenario]["label"], "duration_s": round(pcm_s, 1),
                "audio_url": f"/api/demo/audio/{scenario}.wav"}

    @app.get("/api/demo/audio/{scenario}.wav", dependencies=auth)
    def demo_audio(scenario: str):
        if scenario not in demo.SCENARIOS:
            raise HTTPException(404, "unknown scenario")
        return Response(content=demo.scenario_wav(scenario), media_type="audio/wav",
                        headers={"Cache-Control": "no-store"})

    # ---------- WebSockets ----------

    @app.websocket("/ws/ingest")
    async def ws_ingest(ws: WebSocket, token: str = "", session_id: str = ""):
        if not token_ok(token) or not re.match(SESSION_ID_RE, session_id):
            await ws.close(code=4401)
            return
        existing = manager.sessions.get(session_id)
        # attach() creates a new Session for an unknown OR ended id: both count against the caps.
        if (existing is None or not existing.active) and not admit_new_session():
            await ws.close(code=4429)  # usage cap reached
            return
        await ws.accept()
        session = await manager.attach(session_id, ws)
        try:
            while True:
                msg = await ws.receive()
                if msg["type"] == "websocket.disconnect":
                    break
                if msg.get("bytes") is not None:
                    await session.handle_binary(msg["bytes"])
                elif msg.get("text") is not None:
                    await session.handle_text(msg["text"])
        except WebSocketDisconnect:
            pass
        finally:
            await manager.detach(session, ws)

    @app.websocket("/ws/dashboard")
    async def ws_dashboard(ws: WebSocket, token: str = ""):
        if not token_ok(token):
            await ws.close(code=4401)
            return
        await ws.accept()
        q = hub.subscribe()
        try:
            await ws.send_json({"kind": "hello", "schema_version": SCHEMA_VERSION,
                                "sessions": [s.health() for s in manager.sessions.values()]})
            while True:
                await ws.send_json(await q.get())
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            hub.unsubscribe(q)

    # ---------- REST ----------

    @app.get("/health")
    def health() -> dict[str, Any]:
        try:
            p = pipeline.health()
        except Exception as e:  # noqa: BLE001
            p = {"ok": False, "detail": repr(e)}
        return {"ok": True, "schema_version": SCHEMA_VERSION, "pipeline": {"name": pipeline.name,
                "is_mock": pipeline.is_mock, **p}, "risk_config_version": cfg.version}

    @app.get("/", include_in_schema=False)
    def root():
        return RedirectResponse("/dashboard/")

    @app.get("/api/sessions", dependencies=auth)
    def list_sessions() -> list[dict[str, Any]]:
        live = {sid: s.health() for sid, s in manager.sessions.items()}
        out = []
        for row in store.sessions():
            out.append(row | {"live": live.get(row["session_id"])})
        return out

    @app.get("/api/sessions/{session_id}", dependencies=auth)
    def session_detail(session_id: str) -> dict[str, Any]:
        s = manager.sessions.get(session_id)
        events = store.events(session_id, ["chat_message", "utterance", "evidence", "retraction", "assessment",
                                           "action", "control"], limit=2000)
        if not events and s is None:
            raise HTTPException(404, "unknown session")
        return {"session_id": session_id, "health": s.health() if s else None, "events": events}

    @app.get("/api/sessions/{session_id}/report", dependencies=auth)
    def session_report(session_id: str, format: str = "json"):
        events = store.events(session_id, limit=5000)
        if not events:
            raise HTTPException(404, "unknown session")
        s = manager.sessions.get(session_id)
        cached = store.summary(session_id)
        rep = build_report(session_id, events, s.health() if s else None, store.frames(session_id),
                           cached[1] if cached else None)
        if format == "md":
            return PlainTextResponse(report_markdown(rep), media_type="text/markdown")
        return rep

    @app.post("/api/sessions/{session_id}/end_call", dependencies=auth)
    async def end_call(session_id: str) -> dict[str, Any]:
        s = manager.sessions.get(session_id)
        if s is None or not s.active:
            raise HTTPException(404, "no active session")
        if s.ext_ws is None:
            raise HTTPException(409, "extension not connected")
        env = await s.issue_action("manual_end_call", "requested", {"origin": "dashboard"},
                                   s.latest.assessment_id if s.latest else None)
        return env.model_dump()

    @app.post("/api/sessions/{session_id}/inject_text", dependencies=auth)
    async def inject_text(session_id: str, body: InjectText) -> dict[str, Any]:
        """Debug / replay: feeds text as a final utterance (marked is_mock). Not live ASR."""
        s = manager.sessions.get(session_id)
        if s is None or not s.active:
            raise HTTPException(404, "no active session")
        return s.inject_text(body.text, body.speaker_role).model_dump()

    @app.post("/api/sessions/{session_id}/summary", dependencies=auth)
    async def session_summary(session_id: str) -> dict[str, Any]:
        """AI-written brief summary of the call (Sarvam LLM), cached until new events arrive."""
        events = store.events(session_id, ["utterance", "chat_message", "evidence", "retraction",
                                           "assessment", "action"], limit=3000)
        if not events:
            raise HTTPException(404, "unknown session")
        cached = store.summary(session_id)
        if cached and cached[0] == len(events):
            return cached[1]
        try:
            body = await summarize(events, store.frames(session_id))
        except Exception as e:  # noqa: BLE001 - surfaced to the dashboard
            raise HTTPException(503, f"summary unavailable: {e}")
        store.save_summary(session_id, len(events), body)
        return body

    @app.get("/api/sessions/{session_id}/frames", dependencies=auth)
    def session_frames(session_id: str) -> list[dict[str, Any]]:
        """Screenshots taken when risk rose to high/critical, a chat message was flagged, or a
        document / uniform was seen on video."""
        return store.frames(session_id)

    @app.get("/api/sessions/{session_id}/frames/{frame_id}.jpg", dependencies=auth)
    def session_frame_jpg(session_id: str, frame_id: str):
        jpeg = store.frame_jpeg(session_id, frame_id)
        if jpeg is None:
            raise HTTPException(404, "unknown frame")
        return Response(content=jpeg, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})

    def _latest_frame(session_id: str) -> dict | None:
        getter = getattr(pipeline, "latest_frame", None)
        return getter(session_id) if getter else None

    @app.get("/api/sessions/{session_id}/vision/latest", dependencies=auth)
    def vision_latest(session_id: str) -> dict[str, Any]:
        """Last frame the vision model analysed (kept in memory only, never stored)."""
        f = _latest_frame(session_id)
        if not f:
            return {"available": False}
        return {"available": True, **{k: v for k, v in f.items() if k != "jpeg"}}

    @app.get("/api/sessions/{session_id}/vision/latest.jpg", dependencies=auth)
    def vision_latest_jpg(session_id: str):
        f = _latest_frame(session_id)
        if not f:
            raise HTTPException(404, "no analysed frame")
        return Response(content=f["jpeg"], media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    if FRONTEND_DIR.is_dir():
        app.mount("/dashboard", StaticFiles(directory=FRONTEND_DIR, html=True), name="dashboard")

    return app
