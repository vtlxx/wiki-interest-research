"""Rule-based trust level with explicit reasons (spec 6.7). Reason texts live in the locale files."""
from __future__ import annotations

from dataclasses import dataclass, field

LEVELS = ("low", "medium", "high")
MAX_REASONS = 5


@dataclass(frozen=True)
class TrustInputs:
    median_monthly_views: float
    history_months: int
    spike_share: float
    flips_without_spikes: bool
    high_incidents: list[str]
    redirect_coverage: float | None
    dominant_redirect: bool
    young_article: bool
    renamed_in_window: bool
    project_yoy: float | None
    trend_conflict: bool
    is_proxy: bool
    verify_outcome: str | None = None


@dataclass(frozen=True)
class Reason:
    code: str
    severity: str  # critical | minor | cap


@dataclass(frozen=True)
class Trust:
    level: str
    reasons: list[Reason] = field(default_factory=list)


def assess(inp: TrustInputs) -> Trust:
    critical: list[str] = []
    minor: list[str] = []
    if inp.median_monthly_views < 30:
        critical.append("tiny_volume")
    elif inp.median_monthly_views < 300:
        minor.append("low_volume")
    if inp.history_months < 12:
        critical.append("short_history")
    elif inp.history_months < 24:
        minor.append("history_lt_24")
    if inp.spike_share > 0.5:
        critical.append("spike_driven")
    elif inp.spike_share >= 0.2:
        minor.append("spiky")
    if inp.flips_without_spikes:
        critical.append("flips_without_spikes")
    if inp.verify_outcome == "flips":
        critical.append("verify_flips")
    elif inp.verify_outcome == "weakens":
        minor.append("verify_weakens")
    if inp.high_incidents:
        minor.append("data_incident")
    if inp.redirect_coverage is not None and inp.redirect_coverage < 0.9:
        minor.append("redirect_coverage")
    if inp.dominant_redirect:
        minor.append("dominant_redirect")
    if inp.young_article:
        minor.append("young_article")
    if inp.renamed_in_window:
        minor.append("renamed")
    if inp.project_yoy is not None and abs(inp.project_yoy) > 0.25:
        minor.append("project_shift")
    if inp.trend_conflict:
        minor.append("trend_conflict")

    level = 0 if critical else max(0, 2 - len(minor))
    caps = []
    if inp.is_proxy:
        caps.append("proxy")
        level = min(level, 1)
    reasons = ([Reason(c, "critical") for c in critical] + [Reason(c, "minor") for c in minor]
               + [Reason(c, "cap") for c in caps])[:MAX_REASONS]
    return Trust(LEVELS[level], reasons)
