from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AccountSummary:
    """Traffic & Sales KPIs — B2C only (B2B excluded per SOP)."""
    revenue: Optional[float] = None
    ordered_units: Optional[int] = None
    page_views: Optional[int] = None
    conv_pct: Optional[float] = None        # units / sessions * 100
    sessions: Optional[int] = None
    s_conv_pct: Optional[float] = None      # orders / sessions * 100
    avg_retail: Optional[float] = None      # calculated: revenue / units
    buybox_win_pct: Optional[float] = None
    mobile_sessions_pct: Optional[float] = None


@dataclass
class AdPerformance:
    """Advertising performance KPIs."""
    ad_sales: Optional[float] = None
    ad_spend: Optional[float] = None
    acos_pct: Optional[float] = None        # spend / sales * 100
    roas: Optional[float] = None            # sales / spend
    tacos_pct: Optional[float] = None       # calculated: spend / total_revenue * 100
    troas: Optional[float] = None           # calculated: total_revenue / spend
    impressions: Optional[int] = None
    clicks: Optional[int] = None
    orders: Optional[int] = None
    units_ads: Optional[int] = None
    cpc: Optional[float] = None             # spend / clicks
    cpa: Optional[float] = None             # spend / orders
    conv_pct_ads: Optional[float] = None    # orders / clicks * 100
    ntb_units: Optional[int] = None


@dataclass
class ParsedData:
    account: AccountSummary
    ads: Optional[AdPerformance]
    column_mapping: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)


def compute_derived(account: AccountSummary, ads: AdPerformance) -> None:
    """Compute all derived/calculated fields in-place."""
    if account.revenue and account.ordered_units and account.ordered_units > 0:
        account.avg_retail = account.revenue / account.ordered_units

    if not ads:
        return

    if ads.ad_spend and ads.ad_sales and ads.ad_sales > 0:
        ads.acos_pct = ads.ad_spend / ads.ad_sales * 100
        ads.roas = ads.ad_sales / ads.ad_spend

    if ads.ad_spend and account.revenue and account.revenue > 0:
        ads.tacos_pct = ads.ad_spend / account.revenue * 100
        ads.troas = account.revenue / ads.ad_spend

    if ads.ad_spend and ads.clicks and ads.clicks > 0:
        ads.cpc = ads.ad_spend / ads.clicks

    if ads.ad_spend and ads.orders and ads.orders > 0:
        ads.cpa = ads.ad_spend / ads.orders

    if ads.orders and ads.clicks and ads.clicks > 0:
        ads.conv_pct_ads = ads.orders / ads.clicks * 100


KPI_LABELS = {
    # Account Summary
    "revenue": "Revenue ordered",
    "ordered_units": "Ordered units",
    "page_views": "Page views",
    "conv_pct": "Conv.",
    "sessions": "Sessions",
    "s_conv_pct": "S. Conv.",
    "avg_retail": "Avg Retail",
    "buybox_win_pct": "Buybox win",
    "mobile_sessions_pct": "Mobile S.",
    # Advertising
    "ad_sales": "Ad sales",
    "ad_spend": "Ad spend",
    "acos_pct": "ACOS",
    "roas": "ROAS",
    "tacos_pct": "TACOS",
    "troas": "TROAS",
    "impressions": "Impressions",
    "clicks": "Clicks",
    "orders": "Orders",
    "units_ads": "Units",
    "cpc": "CPC",
    "cpa": "CPA",
    "conv_pct_ads": "CONV",
    "ntb_units": "NTB units",
}

KPI_TYPE = {
    "revenue": "currency",
    "ordered_units": "number",
    "page_views": "number",
    "conv_pct": "percent",
    "sessions": "number",
    "s_conv_pct": "percent",
    "avg_retail": "currency",
    "buybox_win_pct": "percent",
    "mobile_sessions_pct": "percent",
    "ad_sales": "currency",
    "ad_spend": "currency",
    "acos_pct": "percent",
    "roas": "ratio",
    "tacos_pct": "percent",
    "troas": "ratio",
    "impressions": "number",
    "clicks": "number",
    "orders": "number",
    "units_ads": "number",
    "cpc": "currency",
    "cpa": "currency",
    "conv_pct_ads": "percent",
    "ntb_units": "number",
}

ACCOUNT_FIELDS = [
    "revenue", "ordered_units", "page_views", "conv_pct",
    "sessions", "s_conv_pct", "avg_retail", "buybox_win_pct", "mobile_sessions_pct",
]

ADS_FIELDS = [
    "ad_sales", "ad_spend", "acos_pct", "roas", "tacos_pct", "troas",
    "impressions", "clicks", "orders", "units_ads", "cpc", "cpa", "conv_pct_ads", "ntb_units",
]
