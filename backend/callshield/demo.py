"""One-click demo for evaluators: replays a recorded call through the real pipeline.

The server plays the extension's role: it streams the recording's PCM in real time (200 ms
chunks, exactly what the extension sends), sends Meet-like video frames (a warrant is held up
part-way) and a chat message. Everything downstream is the live system: Sarvam ASR, the
detector, vision, fusion, policy, key-frame screenshots and the call summary. The dashboard
plays the same audio aloud so the viewer hears what is being analysed.
"""

from __future__ import annotations

import asyncio
import io
import logging
import time
import uuid
import wave
from pathlib import Path

from . import framing
from .contracts import make_event, now_ms

log = logging.getLogger("callshield.demo")

EVAL = Path(__file__).resolve().parents[2] / "eval"
CHUNK_SAMPLES = 3200  # 200 ms at 16 kHz
FRAME_EVERY_S = 2.0
LINGER_S = 12.0       # keep the session open so the last lines are analysed

SCENARIOS = {
    "scam": {
        "label": "Digital-arrest scam call",
        "audio": ["s01_mumbai_police_parcel.wav", "s02_cbi_devanagari.wav"],
        # (from second, image): the warrant is held up to the camera part-way through
        "frames": [(0, "college_id_frame.jpg"), (14, "demo_warrant_frame.jpg")],
        "chat": [(22, "Arrest warrant copy: https://cbi-gov-in.case-verify.in/warrant.pdf  "
                      "Case band karne ke liye 2,00,000 RBI safe account mein abhi transfer karo")],
    },
    "awareness": {
        "label": "Awareness talk (should stay safe)",
        "audio": ["b01_awareness_discussion.wav"],
        "frames": [(0, "benign_slide_frame.jpg")],
        "chat": [],
    },
}

_running: dict[str, float] = {}  # session_id -> start time
MAX_RUNNING = 2


def scenario_pcm(name: str) -> bytes:
    """16 kHz mono s16le PCM of a scenario (recordings joined with 1 s of silence)."""
    out = b""
    for f in SCENARIOS[name]["audio"]:
        with wave.open(str(EVAL / "audio" / f)) as w:
            assert w.getframerate() == 16000 and w.getnchannels() == 1 and w.getsampwidth() == 2
            out += w.readframes(w.getnframes()) + b"\x00\x00" * 16000
    return out


def scenario_wav(name: str) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(scenario_pcm(name))
    return buf.getvalue()


class _DemoSocket:
    """Stands in for the extension's WebSocket (assessments/actions are just dropped)."""
    async def send_text(self, text: str) -> None:
        pass

    async def close(self, code: int = 1000) -> None:
        pass


def can_start() -> bool:
    now = time.monotonic()
    for sid, t in list(_running.items()):
        if now - t > 300:  # stale guard
            _running.pop(sid, None)
    return len(_running) < MAX_RUNNING


def new_session_id() -> str:
    return f"demo-{time.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4]}"


async def run(manager, scenario: str, sid: str) -> None:
    sc = SCENARIOS[scenario]
    pcm = scenario_pcm(scenario)
    images = {f: (EVAL / "images" / f).read_bytes() for _, f in sc["frames"]}
    ws = _DemoSocket()
    _running[sid] = time.monotonic()
    s = await manager.attach(sid, ws)
    try:
        await s.handle_text(make_event(sid, "control", "extension", {"command": "session_start", "details": {
            "auto_disconnect": False, "extension_version": f"demo:{scenario}"}}).model_dump_json())
        base = now_ms()
        t0 = time.monotonic()
        chats = list(sc["chat"])
        next_frame, frame_seq, last_img = 0.0, 0, None
        for seq, i in enumerate(range(0, len(pcm), CHUNK_SAMPLES * 2)):
            chunk = pcm[i:i + CHUNK_SAMPLES * 2]
            if len(chunk) % 2:
                chunk = chunk[:-1]
            n0 = i // 2
            env = make_event(sid, "audio_chunk", "meet_tab", {
                "seq": seq, "t_start_ms": base + n0 * 1000 // 16000,
                "t_end_ms": base + (n0 + len(chunk) // 2) * 1000 // 16000,
                "sample_rate_hz": 16000, "channels": 1, "encoding": "pcm_s16le", "speaker_role": "remote"})
            await s.handle_binary(framing.encode(env.model_dump(), chunk))
            elapsed = time.monotonic() - t0
            if elapsed >= next_frame:
                img = [f for start, f in sc["frames"] if start <= elapsed][-1]
                fenv = make_event(sid, "video_frame", "meet_tab", {
                    "seq": frame_seq, "t_ms": now_ms(), "width": 1280, "height": 720, "encoding": "jpeg",
                    "change_score": 0.3 if img != last_img else 0.0})
                await s.handle_binary(framing.encode(fenv.model_dump(), images[img]))
                frame_seq, last_img, next_frame = frame_seq + 1, img, next_frame + FRAME_EVERY_S
            while chats and chats[0][0] <= elapsed:
                _, text = chats.pop(0)
                await s.handle_text(make_event(sid, "chat_message", "meet_chat", {
                    "message_id": f"demo-chat-{seq}", "t_ms": now_ms(), "text": text,
                    "sender_role": "unknown", "sender_label": "chat_panel"}).model_dump_json())
            # real-time pacing, like a live call
            await asyncio.sleep(max(0.0, (seq + 1) * 0.2 - (time.monotonic() - t0)))
        await asyncio.sleep(LINGER_S)
        await s.handle_text(make_event(sid, "control", "extension", {
            "command": "session_stop", "details": {"reason": "demo_done"}}).model_dump_json())
    except Exception:  # noqa: BLE001
        log.exception("demo %s failed", sid)
    finally:
        _running.pop(sid, None)
        await manager.detach(s, ws)
