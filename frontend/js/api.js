// CallShield REST API Client

class ApiClient {
  constructor() {
    const params = new URLSearchParams(window.location.search);
    // Hosted demo: preconfigured shared demo token, so evaluators can open the dashboard link as is.
    const defaultToken = window.location.hostname.endsWith('onrender.com') ? 'RxGiUbLIoP5S8GsZf6AiVpDMVye3m9OjN8EJsE2VjMo=' : 'dev-token';
    this.token = params.get('token') || localStorage.getItem('cs_token') || defaultToken;
    try {
      localStorage.setItem('cs_token', this.token);
    } catch {}
  }

  setToken(newToken) {
    this.token = newToken.trim();
    try {
      localStorage.setItem('cs_token', this.token);
    } catch {}
  }

  getToken() {
    return this.token;
  }

  async request(path, opts = {}) {
    const url = path;
    const headers = {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${this.token}`,
      ...(opts.headers || {}),
    };

    try {
      const res = await fetch(url, { ...opts, headers });
      if (!res.ok) {
        let errText = '';
        try {
          const jsonErr = await res.json();
          errText = jsonErr.detail || JSON.stringify(jsonErr);
        } catch {
          errText = await res.text();
        }
        throw new Error(`${res.status} ${errText || res.statusText}`);
      }
      const ct = res.headers.get('content-type') || '';
      if (ct.includes('application/json')) {
        return await res.json();
      }
      return await res.text();
    } catch (err) {
      console.warn(`[API] Error on ${opts.method || 'GET'} ${path}:`, err.message);
      throw err;
    }
  }

  // System
  async getHealth() {
    // Health is public and does not strictly require auth
    const res = await fetch('/health');
    if (!res.ok) throw new Error(`Health error: ${res.status}`);
    return await res.json();
  }

  // Sessions
  async listSessions() {
    return await this.request('/api/sessions');
  }

  async getSession(sessionId) {
    return await this.request(`/api/sessions/${encodeURIComponent(sessionId)}`);
  }

  async getReport(sessionId, format = 'json') {
    return await this.request(`/api/sessions/${encodeURIComponent(sessionId)}/report?format=${format}`);
  }

  async endCall(sessionId) {
    return await this.request(`/api/sessions/${encodeURIComponent(sessionId)}/end_call`, {
      method: 'POST',
    });
  }

  async injectText(sessionId, text, speakerRole = 'remote') {
    return await this.request(`/api/sessions/${encodeURIComponent(sessionId)}/inject_text`, {
      method: 'POST',
      body: JSON.stringify({ text, speaker_role: speakerRole }),
    });
  }

  // Vision
  async getVisionLatest(sessionId) {
    return await this.request(`/api/sessions/${encodeURIComponent(sessionId)}/vision/latest`);
  }

  // Call summary (Sarvam LLM, cached server-side) and key-moment screenshots
  async getSummary(sessionId) {
    return await this.request(`/api/sessions/${encodeURIComponent(sessionId)}/summary`, { method: 'POST' });
  }

  async getFrames(sessionId) {
    return await this.request(`/api/sessions/${encodeURIComponent(sessionId)}/frames`);
  }

  frameUrl(sessionId, frameId) {
    return `/api/sessions/${encodeURIComponent(sessionId)}/frames/${encodeURIComponent(frameId)}.jpg?token=${encodeURIComponent(this.token)}`;
  }
}

export const api = new ApiClient();

