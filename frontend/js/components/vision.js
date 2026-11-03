// CallShield Video Analysis Component
// Latest frame examined by the Sarvam vision model (documents, uniforms, emblems), plus the
// screenshots the backend kept at key moments (risk rose, chat flagged, document shown).

import { esc, fmtTime } from '../formatters.js';
import { summaryHtml } from './report.js';

export class VisionComponent {
  constructor(containerId, api) {
    this.container = document.getElementById(containerId);
    this.api = api;
    this.sessionId = null;
    this.lastVisionEvent = null;
    this.pollTimer = null;
    this.frameCount = -1;
    this.render();
  }

  render() {
    if (!this.container) return;
    this.container.innerHTML = `
      <div class="panel-header">
        <div class="panel-title-wrap">
          <h3 class="panel-title">Video Analysis</h3>
          <span class="muted small text-muted text-xs">(reports what is shown, never whether it is genuine)</span>
        </div>
      </div>
      <div class="vision">
        <img id="visionImg" alt="Last analysed video frame" class="hidden" />
        <div id="visionInfo" class="muted text-muted">No frame analysed yet.</div>
      </div>
      <div class="mt-4">
        <div class="panel-title-wrap mb-2"><b>Call summary</b>
          <span class="muted small text-muted text-xs">(what happened between the user and the other party; updates at each key moment)</span>
          <button class="btn btn-xs btn-ghost" id="summaryRefreshBtn">↻ Refresh summary</button></div>
        <div id="callSummary" class="summary-card"><div class="muted">No session selected.</div></div>
      </div>
      <div id="keyFrames" class="mt-4"></div>
    `;
  }

  setSession(sessionId) {
    if (this.sessionId === sessionId) return;
    this.sessionId = sessionId;
    this.lastVisionEvent = null;
    this.frameCount = -1;
    this.summarySeq = (this.summarySeq || 0) + 1;
    const kf = document.getElementById('keyFrames');
    if (kf) kf.innerHTML = '';
    const cs = document.getElementById('callSummary');
    if (cs) cs.innerHTML = '<div class="muted">Waiting for the call…</div>';
    const btn = document.getElementById('summaryRefreshBtn');
    if (btn) btn.onclick = () => this.refreshSummary();
    const img = document.getElementById('visionImg');
    const info = document.getElementById('visionInfo');
    if (img) {
      img.classList.add('hidden');
      img.src = '';
    }
    if (info) {
      info.textContent = 'No frame analysed yet.';
    }

    this.stopPolling();
    if (this.sessionId) {
      this.refresh();
      this.startPolling();
    }
  }

  startPolling() {
    this.stopPolling();
    this.pollTimer = setInterval(() => {
      this.refresh();
    }, 3000);
  }

  stopPolling() {
    if (this.pollTimer) {
      clearInterval(this.pollTimer);
      this.pollTimer = null;
    }
  }

  async refreshKeyFrames() {
    const el = document.getElementById('keyFrames');
    if (!el || !this.sessionId) return;
    let frames;
    try {
      frames = await this.api.getFrames(this.sessionId);
    } catch {
      return;
    }
    if (frames.length === this.frameCount) return;
    this.frameCount = frames.length;
    this.refreshSummary(); // a new key moment (or first load): bring the summary up to date
    el.innerHTML = `
      <div class="panel-title-wrap mb-2"><b>Key moments</b>
        <span class="muted small text-muted text-xs">(screenshots taken when risk rose to HIGH/CRITICAL, a chat was flagged, or a document was shown)</span></div>
      ${frames.length ? `<div class="keyframe-grid">${frames.slice().reverse().map(f => `
        <a class="keyframe" href="${this.api.frameUrl(this.sessionId, f.frame_id)}" target="_blank" rel="noopener">
          <img src="${this.api.frameUrl(this.sessionId, f.frame_id)}" alt="${esc(f.reason)}" loading="lazy" />
          <div class="keyframe-cap"><code>${fmtTime(f.t_ms)}</code> · risk ${esc(f.risk_index ?? '–')}<br>${esc(f.reason)}</div>
        </a>`).join('')}</div>` : '<div class="muted text-muted small">None yet.</div>'}`;
  }

  async refreshSummary() {
    const el = document.getElementById('callSummary');
    if (!el || !this.sessionId) return;
    const seq = (this.summarySeq = (this.summarySeq || 0) + 1);
    const sid = this.sessionId;
    el.innerHTML = summaryHtml(null);
    let s;
    try {
      s = await this.api.getSummary(sid);
    } catch (err) {
      // 404 = nothing said yet in this session
      s = { error: String(err.message || err).startsWith('404') ? 'nothing to summarise yet' : err.message };
    }
    if (seq === this.summarySeq && sid === this.sessionId) el.innerHTML = summaryHtml(s);
  }

  async refresh() {
    if (!this.sessionId) return;
    this.refreshKeyFrames();
    const img = document.getElementById('visionImg');
    const info = document.getElementById('visionInfo');
    if (!img || !info) return;

    let v;
    try {
      v = await this.api.getVisionLatest(this.sessionId);
    } catch {
      return;
    }

    if (!v || !v.available) {
      img.classList.add('hidden');
      info.textContent = 'No frame analysed yet (needs SARVAM_API_KEY; frames are checked when the picture changes, and once a minute).';
      this.lastVisionEvent = null;
      return;
    }

    if (v.event_id === this.lastVisionEvent) return;
    this.lastVisionEvent = v.event_id;

    const token = this.api.getToken();
    img.src = `/api/sessions/${encodeURIComponent(this.sessionId)}/vision/latest.jpg?token=${encodeURIComponent(token)}&e=${encodeURIComponent(v.event_id)}`;
    img.classList.remove('hidden');

    const docs = (v.documents || []).map((d) => {
      const kindStr = esc((d.kind || '').replace(/_/g, ' '));
      const agencyStr = d.agency ? ` <span class="muted text-muted">(${esc(d.agency)})</span>` : '';
      const textStr = d.text ? `<pre>${esc(d.text)}</pre>` : '';
      return `<div class="doc"><b>${kindStr}</b>${agencyStr}${textStr}</div>`;
    }).join('');

    const cues = (v.cues && v.cues.length)
      ? `<div>Cues: ${v.cues.map((c) => `<span class="tag tag-video">${esc((c || '').replace(/_/g, ' '))}</span>`).join(' ')}</div>`
      : '';

    info.innerHTML = `
      <div class="muted small text-muted text-xs mb-2">${fmtTime(v.t_ms)} · ${v.latency_ms ?? 0} ms · confidence ${esc(v.confidence ?? '–')}</div>
      ${docs || cues ? docs + cues : '<div>Nothing relevant visible.</div>'}
    `;
  }
}

