"""Action policy, kept separate from scoring.

The policy only *requests* actions. The extension executes an auto-disconnect only if the
user opted in locally as well, and only after a visible cancel window.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .fusion import RiskConfig, RiskResult


@dataclass
class ActionRequest:
    action_type: str
    status: str
    details: dict[str, Any] = field(default_factory=dict)


MAX_MITIGATION_CANCELS = 1


class PolicyEngine:
    def __init__(self, cfg: RiskConfig):
        self.cfg = cfg
        self.critical_since_ms: int | None = None
        self.auto_disconnect_issued = False
        self.auto_disconnect_issued_ms = 0
        # A cue may cancel one countdown per call: otherwise a scammer could keep saying
        # "savdhan rahiye" to stay below the auto-disconnect for the whole call.
        self.mitigation_cancels = 0

    def gate(self, r: RiskResult, *, settings: dict, monitoring_state: str,
             inference_mode: str, now_ms: int) -> dict[str, bool]:
        ad = self.cfg.auto_disconnect
        sustained = (self.critical_since_ms is not None
                     and now_ms - self.critical_since_ms >= ad.sustain_ms)
        hold_ms = self.cfg.mitigation.hold_s * 1000
        held = (r.last_mitigation_ms is not None
                and now_ms - r.last_mitigation_ms <= hold_ms
                # a new demand/threat after the cue ends the hold at once
                and (r.last_flag_ms is None or r.last_flag_ms <= r.last_mitigation_ms)
                and self.mitigation_cancels < MAX_MITIGATION_CANCELS)
        return {
            # Someone just framed the call as awareness / a joke / a test: don't hang up on that.
            "no_recent_mitigation": not held,
            "user_opted_in": bool(settings.get("auto_disconnect")),
            "level_critical": r.risk_level == "critical",
            "sustained": sustained,
            "corroborated": len(r.text_categories) >= ad.min_text_categories,
            "strong_category": r.has_strong_category or not ad.require_strong_category,
            "monitoring_ok": monitoring_state == "ok",
            "live_inference": inference_mode == "live" or (inference_mode == "mock" and ad.allow_on_mock),
        }

    def decide(self, r: RiskResult, *, settings: dict, monitoring_state: str,
               inference_mode: str, now_ms: int) -> tuple[dict[str, bool], list[ActionRequest]]:
        if r.risk_level == "critical":
            if self.critical_since_ms is None:
                self.critical_since_ms = now_ms
        else:
            self.critical_since_ms = None

        actions: list[ActionRequest] = []

        checks = self.gate(r, settings=settings, monitoring_state=monitoring_state,
                           inference_mode=inference_mode, now_ms=now_ms)
        window = self.cfg.auto_disconnect.cancel_window_ms
        if all(checks.values()) and not self.auto_disconnect_issued:
            self.auto_disconnect_issued = True
            self.auto_disconnect_issued_ms = now_ms
            actions.append(ActionRequest("auto_disconnect", "pending",
                                         {"cancel_window_ms": window, "gate": checks}))
        elif (self.auto_disconnect_issued
              and (r.risk_level != "critical" or not checks["no_recent_mitigation"])
              and now_ms - self.auto_disconnect_issued_ms < window):
            # Later context lowered the risk (evidence retracted, or awareness / joke / test-call
            # context) inside the cancel window.
            self.auto_disconnect_issued = False
            reason = "risk_revised" if checks["no_recent_mitigation"] else "mitigating_context"
            if reason == "mitigating_context":
                self.mitigation_cancels += 1
            actions.append(ActionRequest("auto_disconnect", "cancelled",
                                         {"reason": reason, "risk_level": r.risk_level}))
        return checks, actions
