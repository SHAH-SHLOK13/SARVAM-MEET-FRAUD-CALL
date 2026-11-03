# CallShield: real-time scam and digital-arrest protection for Google Meet

CallShield listens to a Google Meet call as it happens (speech, chat and video) and warns the user
within seconds when the other party behaves like a scammer: claiming to be police or CBI, threatening
arrest, declaring a "digital arrest", demanding money or an OTP, ordering the user to stay on camera or
keep it secret. It can end the call automatically (opt-in), produces an incident report with an AI
summary and screenshots, and tells harmless calls apart: a friend explaining the same scam as a warning,
or joking, is **not** flagged.

HackSplot 2026, Problem Statement 1. All AI runs on **Sarvam AI** (speech-to-text, language model, vision).

| | |
|---|---|
| **Live demo (no install)** | https://callshield-3lph.onrender.com/dashboard/ |
| **Source code** | https://github.com/SHAH-SHLOK13/SARVAM-MEET-FRAUD-CALL |

---

## 1. See it in 2 minutes (no install, no keys)

1. Open **https://callshield-3lph.onrender.com/dashboard/**.
   The free hosting sleeps when idle, so the first load can take about a minute.
2. Click **▶ Play demo: scam call** (top right). Turn your sound on.
   - A recorded digital-arrest scam call (Hinglish, about 1 minute) plays aloud.
   - At the same time the server streams that audio through the **live pipeline, exactly as the Chrome
     extension does on a real call**: Sarvam speech-to-text, the scam-behaviour detector, Sarvam vision
     on video frames (part-way through, a fake warrant is held up to the camera) and a scam chat message.
3. Watch the dashboard fill in live:
   - **Risk card:** NORMAL → CAUTION → HIGH → CRITICAL, with the reasons and the matched pattern
     ("Digital-arrest pattern").
   - **Live Transcript & Meet Chat:** each line as it is recognised; flagged lines get red ⚠ tags.
   - **Evidence:** each flagged behaviour with its exact quote.
   - **Video Analysis:** what the vision model saw, an **AI call summary** (verdict, what happened,
     timeline, advice) and **Key moments**, screenshots taken when the risk rose and when the scam chat
     arrived.
   - **Incident Report** (button on the risk card): the full report, downloadable as Markdown.
4. Click **▶ Play demo: awareness talk**. Two friends discuss the *same* scam ("CBI officer bolte
   hain… video call cut mat karna… paise transfer karwate hain") as a warning. The risk stays
   **NORMAL (0/100)** and the summary says *awareness*. Avoiding false alarms like this is the hard
   part of the problem.

> The demos use the real AI on the server: the score, flags and summary are computed live on each run,
> not replayed.

## 2. Try it on a real Google Meet call (optional)

The extension is already configured for the hosted backend, so there is nothing to set up.

1. Download this repository as a ZIP (**Code → Download ZIP**) and unzip it.
2. In Chrome open `chrome://extensions`, turn on **Developer mode**, click **Load unpacked** and
   select the `extension/` folder.
3. Join a Google Meet call. Click the CallShield icon, then **Start monitoring this Meet tab**.
4. Join the same Meet from a second device (a phone) and, **from that device**, say for example:
   *"Main Mumbai Police cyber cell se Inspector Sharma bol raha hoon. Aapke naam ka parcel pakda gaya
   hai, usme drugs mile hain. Aap abhi se digital arrest mein hain. Video call cut mat karna. Abhi
   turant do lakh rupaye transfer kariye."*
5. A warning appears on the Meet page within a few seconds. The dashboard link above shows the session
   live.

Notes: CallShield judges the **other** participants. The protected user's own voice is never counted
against them. Use headphones on the monitored laptop. Automatic call ending is **off** unless ticked in
the popup.

---

## 3. What it detects (PS1 mapping)

| PS1 requirement | How CallShield does it | Status |
|---|---|---|
| Red flags from **spoken** words | Sarvam `saaras:v4` streaming speech-to-text (Hindi/English code-mix) → contextual detector (`sarvam-105b`) labels 15 scam behaviours with exact quotes | Working on real Meet calls and in the hosted demo |
| Red flags from **messages** during the call | Meet chat read from the chat panel (opened automatically) and judged with the conversation | Working on real Meet |
| **Video**: documents, IDs, uniforms | Sarvam vision (`gemma4`) on changed/settled frames: reads warrants, ID cards, payment details; spots police-style uniforms and badges. Never claims a document is genuine or fake | Working (hosted demo + replay) |
| Disconnect the call | Opt-in automatic "Leave call" after a strict policy gate and an 8 s visible cancel window; manual **End call** from the dashboard | Working on real Meet |
| Report to a central server | Every event, flag and decision is logged on the server; incident report with AI summary + screenshots; 1930 / cybercrime.gov.in guidance | Working (not auto-filed with authorities) |
| Switch off mobile / freeze transactions | Not possible from desktop Chrome; out of scope for this build | Not included |
| Accuracy, false positives/negatives, latency | See [Results](#6-results) | Measured |

Behaviours detected (`backend/risk_config.yaml`): authority claim, legal/arrest threat, explicit
"digital arrest", OTP/PIN/CVV request, card/KYC request, payment demand, remote-access/app install,
"stay on video" custody, secrecy/isolation, documents shown as "proof", move to WhatsApp/Skype, urgency,
parcel/drugs hook story, link to pay/verify, unsolicited data requests; plus visual cues (uniform,
insignia, official document, payment details on screen).

---

## 4. Architecture

```text
 Google Meet tab (desktop Chrome)
 ┌──────────────────────────────────────┐
 │ CallShield extension (Manifest V3)    │   tab audio 16 kHz PCM (200 ms chunks)
 │  • captures tab audio + video frames  │   video frames (JPEG, ~1 / 2 s, change score)
 │  • reads Meet chat                    │   chat messages
 │  • warning overlay, Leave call        │ ─────────── WebSocket (wss) ───────────┐
 └──────────────────▲───────────────────┘                                         │
                    │ risk assessments, "end call" requests                        ▼
 ┌──────────────────┴─────────────────────────────────────────────────────────────────────┐
 │ CallShield backend (FastAPI, hosted on Render)                                          │
 │                                                                                          │
 │  per-call session ─► AI pipeline (Sarvam)                                                │
 │                      ├─ saaras:v4 streaming ASR ──► Hinglish transcript                  │
 │                      ├─ sarvam-105b detector (gemma4 fallback): behaviours + exact quotes │
 │                      │    + speech act (direct / reported / educational / joke)          │
 │                      ├─ gemma4 vision on settled new frames: documents, uniforms          │
 │                      └─ rule-based mitigation cues: awareness / joke / test call          │
 │                  ─► evidence ledger ─► deterministic risk engine ─► policy               │
 │                  ─► SQLite: events, key-moment screenshots, AI call summary               │
 │                  ─► dashboard (live over WebSocket) + incident report                     │
 └──────────────────────────────────────────────────────────────────────────────────────────┘
```

| Folder | What |
|---|---|
| `extension/` | Chrome MV3 extension: tab audio/video capture (offscreen document), Meet chat reader, warning overlay, leave-call, popup |
| `backend/callshield/` | FastAPI app: ingest WebSocket, sessions, AI pipeline (`ai/`), risk engine (`fusion.py`), policy (`policy.py`), reports, one-click demo (`demo.py`) |
| `backend/risk_config.yaml` | All weights, thresholds, patterns and mitigation settings (one file, no hidden numbers) |
| `frontend/` | Dashboard (plain JS, served by the backend at `/dashboard/`) |
| `eval/` | Test conversations, recorded audio, images and the evaluation script |
| `integration_tests/` | Simulate a call or replay audio without Chrome |
| `docs/` | Event contract between extension, backend and AI pipeline; deliverable status |

**Design principle:** the AI *observes* and the maths *decides*. The language model only labels
behaviours with verbatim quotes. It never produces the risk score and cannot end a call. The score is
deterministic and reproducible from the evidence ledger, and every action passes an explicit policy
gate.

---

## 5. How a decision is made

### 5.1 Understanding the conversation (AI)
- **Speech → text:** Sarvam `saaras:v4` in code-mix mode streams Hinglish (Devanagari + Roman)
  transcripts about 0.1 s after each phrase ends.
- **Behaviour detection:** `sarvam-105b` reads a rolling window of the last 16 lines grouped by
  speaker turn, and for each new line decides its **speech act**:
  - *direct*: the speaker is doing it to the listener now ("aap digital arrest mein hain"). Only
    this counts.
  - *reported*: retelling a past call. *educational*: a warning or lesson. *joke*: playing around.
    None of these count.
  Every flag must quote the line verbatim. The model can later **retract** its own flags when context
  shows they were part of a story or lesson. If `sarvam-105b` fails or is rate-limited, `gemma4` takes
  over automatically.
- **Video:** frames are analysed only when the picture changes and then settles (at most one per
  10 s, plus once a minute). Document text joins the transcript and is judged in context like speech.
  Visual cues can only add a little risk, and never on their own.
- **Mitigating context (rules, instant):** phrases such as "…to wo fraud hai", "1930 pe report karo",
  "bank kabhi OTP nahi maangta", "mazaak kar raha hoon", "ye test call tha", "savdhan rahein" are
  detected without waiting for the AI. Negations a scammer would use ("ye fraud nahi hai",
  "mazaak nahi hai") are excluded.

### 5.2 The risk score (deterministic, `backend/callshield/fusion.py`)
1. Each flagged behaviour contributes `c = weight × quality × speaker_factor × decay(age)`
   (half-life 15 min; speaker factor: other party 1.0, unknown 0.7, **protected user 0**). Only the
   strongest mention per behaviour counts, so repetition cannot inflate the score.
2. **Mitigation discount:** a cue at time `t_m` with strength `μ` discounts every flag from the 3
   minutes before it: `D = min(0.85, 1 − Π(1 − μ_i))`, `c ← c × (1 − D)`. Flags raised **after** the cue
   count in full, so a "disclaimer" cannot excuse later demands.
3. Text risk = noisy-OR `1 − Π(1 − c)`. Pattern bonuses (e.g. *authority + threat + custody/secrecy +
   payment* = digital-arrest pattern) are added in proportion to the evidence still standing.
4. Caps: a single behaviour stays below HIGH; weak-only evidence stays below 30; video/tone add at
   most 0.10 / 0.05 and only once speech or chat evidence exists.
5. Levels: CAUTION ≥ 25, HIGH ≥ 50, CRITICAL ≥ 75.

### 5.3 Policy (`backend/callshield/policy.py`)
Automatic call ending is requested only when **all** of these hold: the user opted in; risk is
CRITICAL and has stayed CRITICAL for 6 s; at least 3 different behaviours including a strongest-class
one; monitoring is healthy; real (not mock) AI; and no unanswered mitigation cue in the last 30 s (only
the first cue of a call can hold it, and any new demand ends the hold). The extension then shows an 8 s
countdown the user can cancel. If later context lowers the risk inside that window, the backend
cancels it.

### 5.4 Report
Screenshots of the Meet tab are taken at key moments: when risk first reaches HIGH or CRITICAL, when a
chat message is flagged, and when a document is shown. `sarvam-105b` writes a short call summary
(verdict, what happened, timeline, advice) from the event ledger. The incident report bundles these
with every flag, retraction and action, plus reporting guidance (1930, cybercrime.gov.in). It is
**never** filed automatically.

---

## 6. Results

| Test | Result |
|---|---|
| **Text test set**: 24 scripted Hinglish conversations (12 scams of different kinds, 12 hard negatives: awareness talks, a teacher's class, a victim retelling a story, a lawyer, a friend joking, genuine bank and police calls) | **12/12 scams flagged, 0/12 false alarms** (sarvam-105b). Caveat: this set was used during development, so these numbers are optimistic; a held-out set is future work. |
| **Keyword-only baseline** on the same set (no AI) | 66.7% accuracy, 5 false alarms: why contextual understanding is needed |
| **3 real Meet test calls** (a team member played scammer, then revealed "it was a test / a joke / be careful") | Before the mitigation logic: all 3 ended in auto-disconnect. Now: risk falls to 44, 19 and 2 after the awareness/joke lines; no call is ended. Scam lines before the reveal still reach HIGH/CRITICAL |
| **Hosted one-click demo** (real Sarvam pipeline on Render) | Scam call: 21 transcribed lines, peak **CRITICAL 100/100**, 3 key-moment screenshots, summary verdict *likely scam*. Awareness talk: **NORMAL 0/100**, verdict *awareness* |
| **Latency** | Transcript ≈ 0.1 s after a phrase ends; detector ≈ 1.5 s typical (p95 ≈ 2.5 s); end of a scam sentence → warning on screen ≈ 1–3 s; vision ≈ 1.6 s per analysed frame; call summary ≈ 3.5 s |
| **Automated tests** | 58 unit/integration tests (`cd backend && python -m pytest`) |

Reproduce: `backend\.venv\Scripts\python eval\run_text_eval.py` (AI) or `--mode rules` (baseline).
Results are saved in `eval/results/`.

---

## 7. Security and privacy

- **No AI keys in the code or the extension.** The Sarvam key lives only in the server's environment
  (Render) and in a git-ignored `.env` locally. The repository history was checked: it was never
  committed.
- **Backend access** uses a bearer token. For this public demo, the extension and the hosted
  dashboard ship with a *demo* token so evaluators need no setup. To bound what anyone holding it can
  do, the server enforces **usage caps**: at most 6 live calls, 30 minutes per call, 150 new calls
  per day, 2 demos at a time. The token will be rotated after judging. Planned next: per-call JWTs
  (short-lived, scoped to one call) instead of a shared token.
- **No audio is stored.** Audio is streamed to Sarvam for transcription and discarded. The server keeps
  the transcript, flags and decisions, plus a small number of screenshots at key moments (max 20 per
  call). Only the latest analysed frame is kept in memory for the live view.
- **Prompt-injection resistant by design:** transcript, chat and on-screen text are passed to the
  model as untrusted data, never as instructions; model output is validated (known categories only,
  quotes must match the line, the protected user's lines are ignored); the model cannot score or act.
- **Safe auto-disconnect:** opt-in, multi-condition gate, visible 8 s cancel, never on mock AI, and
  cannot be held off indefinitely by a scammer repeating "be careful" (covered by tests).
- **Dashboard:** all displayed text is HTML-escaped. Screenshots and reports require the token.
- Transport is HTTPS/WSS to the hosted backend.

---

## 8. Limitations (honest)

- **Desktop Chrome + Google Meet only.** Phone calls, WhatsApp and Zoom are not covered. The
  extension is loaded unpacked (not yet on the Chrome Web Store).
- **Meet mixes all remote participants into one audio stream**, so in a group call we cannot tell
  which remote person said what. The protected user's own microphone is optional and kept separate.
- **Transcription errors** on noisy audio can cause missed or extra flags; the multi-condition gate and
  cancel window are the safeguards for actions.
- **Thresholds are not yet calibrated** on real scam recordings; the test set is small and was used in
  development.
- **Chat** is read only while Meet's chat panel is open (the extension opens it automatically).
- **Free hosting** sleeps when idle (about 1 minute to wake), and its disk resets on restart, so old
  sessions and screenshots disappear.
- **Switching off the phone / freezing bank transactions** is not possible from a browser extension.

---

## 9. Tech stack

| Layer | Technology |
|---|---|
| Speech-to-text | Sarvam AI `saaras:v4`, streaming WebSocket, code-mix (Hinglish) |
| Language model | Sarvam AI `sarvam-105b` (detector + call summary), `gemma4` on Sarvam as automatic fallback |
| Vision | `gemma4` via Sarvam chat completions v2 (image input) |
| Backend | Python 3.11+, FastAPI, Uvicorn, Pydantic, SQLite, httpx, websockets |
| Extension | Chrome Manifest V3: tabCapture, offscreen document, AudioWorklet (PCM), content script |
| Dashboard | Plain HTML/CSS/JavaScript (no framework), live WebSocket |
| Hosting | Render (free web service, `render.yaml` blueprint) |

---

## 10. Run it yourself (developers)

Needs CPython 3.11+ and a Sarvam API key (https://dashboard.sarvam.ai).

```powershell
cd backend
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
"SARVAM_API_KEY=your_key" | Out-File -Encoding ascii .env      # never commit this file
.venv\Scripts\python -m pytest -q
.venv\Scripts\python -m uvicorn callshield.main:create_app --factory --port 8000
```

Open http://localhost:8000/dashboard/ (local token `dev-token`). To use the extension against a local
backend, set **Backend → URL** to `http://localhost:8000` and **Token** to `dev-token` in its popup.
Without `SARVAM_API_KEY` the backend runs a keyword-only mock (no speech-to-text).

| Variable | Default | Meaning |
|---|---|---|
| `SARVAM_API_KEY` | – | The only key needed: ASR, detector, vision, summary |
| `CALLSHIELD_TOKEN` | `dev-token` | Bearer token for extension, dashboard and API |
| `CALLSHIELD_LLM_BACKENDS` | `sarvam:sarvam-105b,sarvam:gemma4` | Detector models in failover order |
| `CALLSHIELD_VISION` / `CALLSHIELD_VISION_MODEL` | `on` / `gemma4` | Video analysis on/off and model |
| `CALLSHIELD_PIPELINE` | `auto` | `live`, `mock`, or `module:Class` for another pipeline |
| `CALLSHIELD_RISK_CONFIG` | `backend/risk_config.yaml` | Scoring configuration |
| `CALLSHIELD_DB` | `callshield.db` | SQLite file |
| `CALLSHIELD_MAX_ACTIVE` / `_MAX_SESSION_S` / `_MAX_SESSIONS_PER_DAY` | `6` / `1800` / `150` | Usage caps |

Without Chrome:

```powershell
backend\.venv\Scripts\python integration_tests\simulate_call.py --script digital_arrest
backend\.venv\Scripts\python integration_tests\replay_audio.py eval\audio\s01_mumbai_police_parcel.wav
```

Deploy your own copy: Render → **New → Blueprint** → this repository (`render.yaml`); enter
`SARVAM_API_KEY` when asked.

More detail: [docs/CONTRACT.md](docs/CONTRACT.md) (event contract), [docs/STATUS.md](docs/STATUS.md)
(deliverable status), [eval/README.md](eval/README.md) (evaluation method).
