# CallShield

Real-time fraud and digital-arrest call warnings for Google Meet on desktop Chrome.
HackSplot 2026, PS1. Proof of concept.

## For evaluators (no setup, no keys)

- **One-click demo (no install):** open https://callshield-3lph.onrender.com/dashboard/ (free hosting may
  take ~1 minute to wake up the first time) and click **▶ Play demo: scam call**. A recorded
  digital-arrest call plays aloud while the server streams it through the *live* pipeline exactly like
  the extension does: Sarvam speech-to-text, the scam detector, vision on video frames (a warrant is held
  up), and a scam chat message. Watch the transcript, the risk rising to CRITICAL, the key-moment
  screenshots and the AI call summary appear. Then click **▶ Play demo: awareness talk**: same words,
  but a warning between friends, so the risk stays NORMAL.
- **Extension** (already pointed at the hosted backend, nothing to configure):
  1. Download this repo as ZIP and unzip it.
  2. Chrome → `chrome://extensions` → turn on **Developer mode** → **Load unpacked** → pick the `extension/` folder.
  3. Join a Google Meet call, click the CallShield icon → **Start monitoring this Meet tab**.
  4. From a second device in the same Meet, say a scam line, e.g. *"Main Mumbai Police se bol raha hoon,
     aap digital arrest mein hain, call cut mat karna, abhi do lakh transfer kariye"*. The warning
     appears on Meet; the dashboard shows the transcript, risk, call summary and key-moment screenshots.
- AI keys (Sarvam) live only on the server; nothing is needed on your side.

```text
Meet tab ──► MV3 extension (offscreen capture) ──WS──► FastAPI backend ──► AI pipeline (Shlok)
  ▲  overlay / leave call                                │ evidence ledger → fusion → policy
  └──────────── assessments + action requests ◄──────────┤
                                                         ├──► dashboard (/dashboard)
                                                         └──► incident report: AI call summary + key-moment screenshots
```

| Folder | What |
|---|---|
| `extension/` | Manifest V3 extension: tab audio/video capture, optional mic, Meet chat ingest, overlay, leave call |
| `backend/` | FastAPI: ingest, sessions, AI adapter, fusion + policy, SQLite, call summaries, key-frame screenshots, reports |
| `frontend/` | Dashboard (static, served by the backend at `/dashboard/`) |
| `integration_tests/` | `simulate_call.py`: plays the extension's role without Chrome |
| `docs/` | Contract, limitations, deliverable status |

## Run the backend

Needs a standard CPython 3.11+ (not the MSYS2/MinGW Python: it has no pydantic-core wheels).

```powershell
cd backend
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m pytest -q
.venv\Scripts\python -m uvicorn callshield.main:create_app --factory --port 8000
```

Put `SARVAM_API_KEY=...` in `backend/.env` (gitignored) to run the live pipeline; without it the backend uses the keyword mock.

Open http://localhost:8000/dashboard/ (default token `dev-token`).

Environment variables:

| Variable | Default | Meaning |
|---|---|---|
| `CALLSHIELD_TOKEN` | `dev-token` | Shared token for extension, dashboard and API |
| `CALLSHIELD_PIPELINE` | `mock` | `module:Class` of the AI pipeline (see `backend/callshield/adapter.py`) |
| `CALLSHIELD_RISK_CONFIG` | `backend/risk_config.yaml` | Weights / thresholds (Shlok owns the values) |
| `CALLSHIELD_DB` | `callshield.db` | SQLite file |
| `SARVAM_API_KEY` | – | **The only key needed.** Streaming Hinglish ASR (saaras:v4), the fraud detector LLM and video-frame analysis |
| `CALLSHIELD_LLM_BACKENDS` | `sarvam:sarvam-105b,sarvam:gemma4` | Failover order (`provider:model`). `groq:`/`gemini:` entries still work if `GROQ_API_KEY`/`GEMINI_API_KEY` are set |
| `CALLSHIELD_LLM_EFFORT` | `low` | `reasoning_effort` for the detector (reasoning tokens are billed as output) |
| `CALLSHIELD_VISION` / `CALLSHIELD_VISION_MODEL` | `on` / `gemma4` | Frame analysis on/off and Sarvam v2 image model (`gemma4`, `glm5.3-flash`) |

## Try it without Chrome

```powershell
backend\.venv\Scripts\python integration_tests\simulate_call.py --script digital_arrest
backend\.venv\Scripts\python integration_tests\simulate_call.py --script benign
```

## Load the extension

1. `chrome://extensions` → Developer mode → **Load unpacked** → `extension/`.
2. Join a Google Meet call in a tab (reload Meet tabs opened before installing).
3. Optional: in the popup click **grant access** for the microphone (one time, needs a visible page).
4. On the Meet tab, open the popup → **Start monitoring this Meet tab**.
5. Watch the overlay on Meet and the dashboard.

Auto-disconnect is **off by default**. It needs the popup checkbox *and* the backend policy gate
(critical, sustained, ≥3 corroborating behaviours incl. a strongest-class one, healthy monitoring,
non-mock inference), then an 8 s visible cancel window.

## How the risk score works

Deterministic, reproducible (`backend/callshield/fusion.py`, values in `backend/risk_config.yaml`):

1. Each flagged behaviour contributes `weight × quality × speaker_factor × decay(age)`; one per category.
2. **Mitigating context** (rule-based, instant): when the other party frames what they said as a warning
   ("…to wo fraud hai", "1930 pe report karo"), a joke ("mazaak kar raha hoon") or a test call, every
   flag from the preceding 3 minutes is discounted: `D = min(0.85, 1 − Π(1 − μ_cue))`. Flags raised
   *after* the cue count in full, and negations ("ye fraud nahi hai", "mazaak nahi hai") never count.
3. Text risk = noisy-OR of the contributions; pattern bonuses scale with the share of evidence left.
4. Auto-disconnect needs critical risk sustained 6 s, ≥3 behaviours incl. a strong one, live AI,
   healthy monitoring, user opt-in, and **no mitigating cue in the last 30 s with no new demand after it**
   (only the first cue of a call can hold it, and a demand in the same line or later ends the hold, so repeating "savdhan rahiye" cannot block it); a pending countdown is
   cancelled when one arrives.

Dev-set result (24 scripted conversations, Sarvam `sarvam-105b`): 12/12 scams caught, 0/12 false alarms.

## Status

See [docs/STATUS.md](docs/STATUS.md). Nothing below "verified" has been tested on a real Meet call yet.
