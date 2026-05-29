"""
Parser for Amazon Business Reports → Detail Page Sales and Traffic by Child Item (CSV).
Aggregates across all child ASINs and subtracts B2B to return B2C-only metrics.
"""
import csv
import io
import logging
from .utils import parse_number, find_col
from app.engine.kpis import AccountSummary, ParsedData

log = logging.getLogger(__name__)

COLUMN_ALIASES: dict[str, list[str]] = {
    "sessions": ["Sessions", "Sessions - Total", "Session - Total"],
    "page_views": ["Page Views", "Page Views - Total"],
    "buybox_pct": [
        "Featured Offer (Buy Box) Percentage",
        "Buy Box Percentage",
        "Featured Offer Percentage",
        "Buy Box %",
    ],
    "units_ordered": ["Units Ordered", "Units Ordered - B2C"],
    "units_b2b": ["Units Ordered - B2B"],
    "unit_session_pct": [
        "Unit Session Percentage",
        "Unit Session Percentage - B2C",
        "Unit Session %",
    ],
    "unit_session_pct_b2b": ["Unit Session Percentage - B2B"],
    "ordered_sales": ["Ordered Product Sales", "Ordered Product Sales - B2C"],
    "ordered_sales_b2b": ["Ordered Product Sales - B2B"],
    "order_items": ["Total Order Items", "Total Order Items - B2C"],
    "order_items_b2b": ["Total Order Items - B2B"],
}

REQUIRED = ["sessions", "page_views", "units_ordered", "ordered_sales"]


def parse(content: bytes) -> ParsedData:
    """
    Parse an Amazon Business Report CSV.
    Returns ParsedData with account populated; ads is None.
    Raises ValueError with a user-friendly Spanish message if required columns are missing.
    """
    text = content.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    headers = list(reader.fieldnames or [])

    col_map: dict[str, str] = {}
    for key, aliases in COLUMN_ALIASES.items():
        found = find_col(headers, aliases)
        if found:
            col_map[key] = found
            log.info("Business Report: '%s' → column '%s'", key, found)

    missing_required = [k for k in REQUIRED if k not in col_map]
    if missing_required:
        cols_missing = ", ".join(f"'{COLUMN_ALIASES[k][0]}'" for k in missing_required)
        sample = ", ".join(f"'{h}'" for h in headers[:12])
        raise ValueError(
            f"No encontré las columnas requeridas en el Business Report: {cols_missing}. "
            f"Columnas detectadas: {sample}{'...' if len(headers) > 12 else ''}. "
            "Asegurate de usar 'Detail Page Sales and Traffic by Child Item'."
        )

    rows = list(reader)
    if not rows:
        raise ValueError("El Business Report está vacío (sin filas de datos).")

    warnings: list[str] = []

    def sum_col(key: str) -> float:
        if key not in col_map:
            return 0.0
        return sum(parse_number(r.get(col_map[key])) or 0.0 for r in rows)

    sessions = sum_col("sessions")
    page_views = sum_col("page_views")
    units_total = sum_col("units_ordered")
    units_b2b = sum_col("units_b2b")
    revenue_total = sum_col("ordered_sales")
    revenue_b2b = sum_col("ordered_sales_b2b")
    items_total = sum_col("order_items")
    items_b2b = sum_col("order_items_b2b")

    if "units_b2b" not in col_map:
        warnings.append(
            "Columna 'Units Ordered - B2B' no encontrada; los totales incluyen B2B."
        )
    if "ordered_sales_b2b" not in col_map:
        warnings.append(
            "Columna 'Ordered Product Sales - B2B' no encontrada; los totales incluyen B2B."
        )

    units_b2c = units_total - units_b2b
    revenue_b2c = revenue_total - revenue_b2b
    items_b2c = items_total - items_b2b

    conv_pct = (units_b2c / sessions * 100) if sessions > 0 else None
    s_conv_pct = (items_b2c / sessions * 100) if sessions > 0 else None
    avg_retail = (revenue_b2c / units_b2c) if units_b2c > 0 else None

    # Buybox: page-view-weighted average across ASINs
    buybox_win_pct: float | None = None
    if "buybox_pct" in col_map and page_views > 0:
        weighted = sum(
            (parse_number(r.get(col_map["buybox_pct"])) or 0.0)
            * (parse_number(r.get(col_map["page_views"])) or 0.0)
            for r in rows
        )
        buybox_win_pct = weighted / page_views
    elif "buybox_pct" not in col_map:
        warnings.append(
            "Columna 'Featured Offer (Buy Box) Percentage' no encontrada en Business Report."
        )

    return ParsedData(
        account=AccountSummary(
            revenue=revenue_b2c,
            ordered_units=int(units_b2c),
            page_views=int(page_views),
            conv_pct=conv_pct,
            sessions=int(sessions),
            s_conv_pct=s_conv_pct,
            avg_retail=avg_retail,
            buybox_win_pct=buybox_win_pct,
            mobile_sessions_pct=None,
        ),
        ads=None,
        column_mapping={"business_report": col_map},
        warnings=warnings,
    )
