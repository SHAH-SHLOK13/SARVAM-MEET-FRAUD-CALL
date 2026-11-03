import pytest

from callshield.contracts import Evidence
from callshield.fusion import RiskEngine, load_risk_config
from callshield.policy import PolicyEngine

T0 = 1_000_000


@pytest.fixture
def cfg():
    return load_risk_config()


def ev(i, category, text="x", t=T0, quality=0.9, modality="speech"):
    return Evidence(evidence_id=f"ev{i}", category=category, source_modality=modality,
                    t_start_ms=t, t_end_ms=t, source_event_ids=[f"e{i}"],
                    quoted_text_or_observation=text, quality=quality)


def test_empty_is_normal(cfg):
    r = RiskEngine(cfg).assess(T0)
    assert r.risk_index == 0 and r.risk_level == "normal" and r.evidence_strength == "none"


def test_digital_arrest_pattern_is_critical(cfg):
    eng = RiskEngine(cfg)
    eng.add(ev(1, "authority_claim", "Main Mumbai Police se baat kar raha hoon"), "remote")
    eng.add(ev(2, "digital_arrest_claim", "Aap digital arrest mein hain"), "remote")
    eng.add(ev(3, "video_custody", "call disconnect mat karna"), "remote")
    eng.add(ev(4, "payment_demand", "verification ke liye paise transfer karne padenge"), "remote")
    r = eng.assess(T0)
    assert r.risk_level == "critical"
    assert "digital_arrest" in r.patterns
    assert r.evidence_strength == "strong"
    assert any("R13" in reason for reason in r.reasons)


def test_victim_speech_does_not_count(cfg):
    eng = RiskEngine(cfg)
    eng.add(ev(1, "digital_arrest_claim", "maine digital arrest scam ke baare mein suna"), "local")
    eng.add(ev(2, "credential_request", "mujhe OTP aaya hai"), "local")
    assert eng.assess(T0).risk_index == 0


def test_repeats_do_not_stack(cfg):
    eng = RiskEngine(cfg)
    eng.add(ev(1, "payment_demand", "paise transfer karo"), "remote")
    one = eng.assess(T0).risk_index
    assert eng.add(ev(2, "payment_demand", "paise transfer karo", t=T0 + 1000), "remote") is False
    eng.add(ev(3, "payment_demand", "abhi paise bhejo", t=T0 + 2000), "remote")
    assert eng.assess(T0 + 2000).risk_index == one


def test_weak_only_is_capped(cfg):
    eng = RiskEngine(cfg)
    for i, c in enumerate(["hook_story", "link_request", "unsolicited_pressure", "authority_claim"]):
        eng.add(ev(i, c, f"t{i}", quality=1.0), "remote")
    r = eng.assess(T0)
    assert r.risk_index <= int(cfg.weak_only_cap * 100)


def test_video_and_tone_alone_cannot_raise_risk(cfg):
    eng = RiskEngine(cfg)
    eng.add(ev(1, "visual_uniform", "uniform", modality="video", quality=1.0), "unknown")
    eng.add(ev(2, "tone_intimidation", "angry", modality="tone", quality=1.0), "unknown")
    r = eng.assess(T0)
    assert r.risk_index == 0
    assert any("not counted" in x for x in r.reasons)


def _critical_result(cfg):
    eng = RiskEngine(cfg)
    for i, c in enumerate(["authority_claim", "digital_arrest_claim", "video_custody", "payment_demand"]):
        eng.add(ev(i, c, f"t{i}"), "remote")
    return eng.assess(T0)


def _run_policy(cfg, r, settings, state="ok", mode="live", duration_ms=10_000):
    p = PolicyEngine(cfg)
    fired = []
    for t in range(T0, T0 + duration_ms + 1, 2000):
        _, acts = p.decide(r, settings=settings, monitoring_state=state, inference_mode=mode, now_ms=t)
        fired += [a.action_type for a in acts]
    return fired


def test_auto_disconnect_requires_opt_in(cfg):
    r = _critical_result(cfg)
    assert "auto_disconnect" not in _run_policy(cfg, r, {"auto_disconnect": False})
    assert _run_policy(cfg, r, {"auto_disconnect": True}).count("auto_disconnect") == 1


def test_auto_disconnect_requires_sustained_critical(cfg):
    r = _critical_result(cfg)
    assert "auto_disconnect" not in _run_policy(cfg, r, {"auto_disconnect": True}, duration_ms=2000)


def test_auto_disconnect_blocked_when_degraded_or_mock(cfg):
    cfg.auto_disconnect.allow_on_mock = False
    r = _critical_result(cfg)
    assert "auto_disconnect" not in _run_policy(cfg, r, {"auto_disconnect": True}, state="degraded")
    assert "auto_disconnect" not in _run_policy(cfg, r, {"auto_disconnect": True}, mode="mock")


# ---------- mitigating context (awareness / joke / test call) ----------

def _scam(eng, t=T0):
    eng.add(ev(1, "authority_claim", "Delhi Police se bol rahe hain", t=t), "remote")
    eng.add(ev(2, "digital_arrest_claim", "aap digital arrest mein hain", t=t + 1000), "remote")
    eng.add(ev(3, "payment_demand", "do lakh transfer kariye", t=t + 2000), "remote")
    eng.add(ev(4, "credential_request", "OTP bhejiye", t=t + 3000), "remote")


def test_awareness_cue_lowers_earlier_risk(cfg):
    eng = RiskEngine(cfg)
    _scam(eng)
    before = eng.assess(T0 + 4000)
    assert before.risk_level == "critical"
    eng.add(ev(9, "mitigation_awareness", "ye sab koi bole to wo fraud hai", t=T0 + 5000, quality=1.0), "remote")
    after = eng.assess(T0 + 5000)
    assert after.risk_index < before.risk_index - 30 and after.risk_level != "critical"
    assert after.raw_risk_index == before.risk_index
    assert after.last_mitigation_ms == T0 + 5000
    assert "Mitigating context" in after.reasons[0]


def test_demands_after_a_disclaimer_count_in_full(cfg):
    eng = RiskEngine(cfg)
    eng.add(ev(9, "mitigation_disclaimer", "mazaak kar raha hoon", t=T0, quality=1.0), "remote")
    _scam(eng, t=T0 + 20_000)  # beyond grace_s: a disclaimer cannot excuse what comes next
    r = eng.assess(T0 + 24_000)
    assert r.risk_level == "critical" and r.risk_index == r.raw_risk_index


def test_discount_is_capped_and_local_cues_do_nothing(cfg):
    eng = RiskEngine(cfg)
    _scam(eng)
    eng.add(ev(8, "mitigation_disclaimer", "mazaak tha", t=T0 + 5000, quality=1.0), "local")
    assert eng.assess(T0 + 5000).risk_level == "critical"  # the protected user can't excuse the caller
    for i in range(10, 16):
        eng.add(ev(i, "mitigation_awareness", f"to wo fraud hai {i}", t=T0 + 5000 + i, quality=1.0), "remote")
    assert eng.assess(T0 + 6000).risk_index > 0  # max_discount: evidence never vanishes entirely


def test_mitigation_blocks_and_cancels_auto_disconnect(cfg):
    eng = RiskEngine(cfg)
    _scam(eng)
    eng.add(ev(5, "video_custody", "call cut mat karna", t=T0 + 3500), "remote")
    pol = PolicyEngine(cfg)
    settings = {"auto_disconnect": True}
    t = T0 + 4000
    pol.decide(eng.assess(t), settings=settings, monitoring_state="ok", inference_mode="live", now_ms=t)
    t += cfg.auto_disconnect.sustain_ms
    _, acts = pol.decide(eng.assess(t), settings=settings, monitoring_state="ok", inference_mode="live", now_ms=t)
    assert [a.status for a in acts if a.action_type == "auto_disconnect"] == ["pending"]
    eng.add(ev(9, "mitigation_disclaimer", "ye ek test call tha", t=t + 1000, quality=1.0), "remote")
    gate, acts = pol.decide(eng.assess(t + 1000), settings=settings, monitoring_state="ok",
                            inference_mode="live", now_ms=t + 1000)
    assert not gate["no_recent_mitigation"]
    assert [(a.status, a.details["reason"]) for a in acts if a.action_type == "auto_disconnect"] == [
        ("cancelled", "mitigating_context")]


@pytest.mark.parametrize("text,cats", [
    ("जी ये सब अगर कोई आपको बोले। तो वो fraud है।", ["mitigation_awareness"]),
    ("ye scam karne ki koshish hai", ["mitigation_awareness"]),
    ("OTP kisi ko mat batana", ["mitigation_awareness"]),
    ("बैंक कभी OTP नहीं मांगता", ["mitigation_awareness"]),
    ("मज़ाक कर रहा हूं भाई", ["mitigation_disclaimer"]),
    ("ये एक test call था", ["mitigation_disclaimer"]),
    ("आप सावधान रहें सुरक्षित रहें", ["mitigation_caution"]),
    # scammer talk: negated / reassuring, never a cue
    ("ओ fraud नहीं है बेटे", []),
    ("ye scam nahi hai, main asli police hoon", []),
    ("मैं मज़ाक नहीं कर रहा", []),
    ("isko mazaak mat samjho", []),
    ("aapke against warrant nikla hai", []),
])
def test_mitigation_cue_rules(text, cats):
    from callshield.adapter import mitigation_cues
    assert mitigation_cues(text) == cats


@pytest.mark.parametrize("text,ok", [
    ("आप।", False), ("ए", False), ("अरे!", False), ("ओ भाई ओ।", False), ("Drugs.", False),
    ("OTP भेजिए।", True), ("FIR हो चुकी है।", True), ("समझे आप?", True),
])
def test_fragment_lines(text, ok):
    from callshield.ai.detector import substantive
    assert substantive(text) is ok


def test_repeated_cues_cannot_suppress_auto_disconnect(cfg):
    """A scammer saying 'savdhan rahiye' between demands must not hold off the hang-up."""
    eng = RiskEngine(cfg)
    _scam(eng)
    eng.add(ev(5, "video_custody", "call cut mat karna", t=T0 + 3500), "remote")
    pol, settings = PolicyEngine(cfg), {"auto_disconnect": True}

    def step(t):
        return pol.decide(eng.assess(t), settings=settings, monitoring_state="ok",
                          inference_mode="live", now_ms=t)

    step(T0 + 4000)
    t = T0 + 4000 + cfg.auto_disconnect.sustain_ms
    assert [a.status for a in step(t)[1]] == ["pending"]
    # cue 1 cancels once
    eng.add(ev(9, "mitigation_caution", "savdhan rahiye", t=t + 1000, quality=1.0), "remote")
    assert [a.status for a in step(t + 1000)[1]] == ["cancelled"]
    # a new demand right after the cue ends the hold
    eng.add(ev(10, "payment_demand", "abhi paise bhejiye", t=t + 20_000), "remote")
    eng.add(ev(11, "credential_request", "OTP boliye", t=t + 21_000), "remote")
    gate, _ = step(t + 21_000)
    assert gate["no_recent_mitigation"]
    # a second cue cannot cancel again in the same call
    t2 = t + 40_000
    step(t2)
    eng.add(ev(12, "mitigation_caution", "savdhan rahiye", t=t2 + cfg.auto_disconnect.sustain_ms, quality=1.0), "remote")
    eng.add(ev(13, "payment_demand", "turant transfer karo", t=t2 + cfg.auto_disconnect.sustain_ms + 500), "remote")
    gate, _ = step(t2 + cfg.auto_disconnect.sustain_ms + 1000)
    assert gate["no_recent_mitigation"]
