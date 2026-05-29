from typing import Optional
from .kpis import (
    AccountSummary, AdPerformance, KPI_TYPE,
    ACCOUNT_FIELDS, ADS_FIELDS,
)

LOWER_IS_BETTER = {"acos_pct", "tacos_pct", "ad_spend", "cpc", "cpa"}

# If pct-change > this AND prior < RATIO * current → "base baja"
BASE_BAJA_PCT = 300.0
BASE_BAJA_RATIO = 0.15


def calc_delta(kpi_name: str, current: Optional[float], prior: Optional[float]) -> dict:
    """Return display delta dict for one KPI."""
    null = {"value": None, "display": "N/A", "direction": "neutral",
            "is_good": None, "base_baja": False}

    if current is None or prior is None:
        return null

    kpi_type = KPI_TYPE.get(kpi_name, "number")

    if kpi_type == "percent":
        value = current - prior
        display = f"{value:+.1f} ppt"

    elif kpi_type == "ratio":
        value = current - prior
        display = f"{value:+.2f}x"

    else:  # currency / number
        if prior == 0:
            if current == 0:
                return {"value": 0.0, "display": "0%", "direction": "neutral",
                        "is_good": None, "base_baja": False}
            return {"value": None, "display": "n/d", "direction": "neutral",
                    "is_good": None, "base_baja": False}

        value = (current - prior) / abs(prior) * 100

        # Seasonal / low-base detection
        if (abs(prior) < abs(current) * BASE_BAJA_RATIO and
                abs(value) > BASE_BAJA_PCT):
            direction = "up" if current > prior else "down"
            lower_better = kpi_name in LOWER_IS_BETTER
            is_good = (not lower_better) if direction == "up" else lower_better
            return {"value": value, "display": "base baja", "direction": direction,
                    "is_good": is_good, "base_baja": True}

        display = f"{value:+.1f}%"

    direction = "up" if value > 0 else ("down" if value < 0 else "neutral")
    lower_better = kpi_name in LOWER_IS_BETTER

    if value > 0:
        is_good = not lower_better
    elif value < 0:
        is_good = lower_better
    else:
        is_good = None

    return {"value": value, "display": display, "direction": direction,
            "is_good": is_good, "base_baja": False}


def build_deltas(
    current_account: AccountSummary,
    prior_account: AccountSummary,
    current_ads: AdPerformance,
    prior_ads: AdPerformance,
) -> dict:
    """Return flat dict of delta results keyed by KPI name."""
    deltas = {}

    for f in ACCOUNT_FIELDS:
        deltas[f] = calc_delta(f, getattr(current_account, f), getattr(prior_account, f))

    for f in ADS_FIELDS:
        c_val = getattr(current_ads, f) if current_ads else None
        p_val = getattr(prior_ads, f) if prior_ads else None
        deltas[f] = calc_delta(f, c_val, p_val)

    return deltas
