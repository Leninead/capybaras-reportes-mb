"""
PDF generator — professional multi-page report following SOP v4.
Structure: Cover → Executive Summary → Account Summary →
           Advertising → P&L → Inventory & BSR → Account Health.
Narrative (What Went Well / Areas to Optimize) in Spanish.
No timezone. KPI labels in English.
"""
import io
from typing import Optional
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether, Image as RLImage,
)
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus.flowables import PageBreak

from app.engine.kpis import (
    AccountSummary, AdPerformance, KPI_LABELS, KPI_TYPE,
    ACCOUNT_FIELDS, ADS_FIELDS,
)
from app.engine.deltas import build_deltas, LOWER_IS_BETTER

# ── Colours ───────────────────────────────────────────────────────────────
ORANGE = colors.HexColor("#E84000")
DARK = colors.HexColor("#1A1A1A")
LIGHT_BG = colors.HexColor("#FAFAF8")
GREEN = colors.HexColor("#16803C")
RED = colors.HexColor("#DC2626")
BORDER = colors.HexColor("#E8E5E0")
WHITE = colors.white
MUTED = colors.HexColor("#6B6560")

W, H = A4


def _styles():
    base = getSampleStyleSheet()
    s = {}
    s["title"] = ParagraphStyle("title", fontName="Helvetica-Bold",
                                 fontSize=22, textColor=WHITE,
                                 leading=26, alignment=TA_CENTER)
    s["subtitle"] = ParagraphStyle("subtitle", fontName="Helvetica",
                                    fontSize=11, textColor=WHITE,
                                    leading=14, alignment=TA_CENTER)
    s["section"] = ParagraphStyle("section", fontName="Helvetica-Bold",
                                   fontSize=12, textColor=WHITE,
                                   leading=16, spaceBefore=6)
    s["body"] = ParagraphStyle("body", fontName="Helvetica",
                                fontSize=9, textColor=DARK,
                                leading=13, spaceBefore=2)
    s["kpi_label"] = ParagraphStyle("kpi_label", fontName="Helvetica",
                                     fontSize=8.5, textColor=DARK, leading=11)
    s["note"] = ParagraphStyle("note", fontName="Helvetica-Oblique",
                                fontSize=8, textColor=MUTED, leading=11)
    return s


def _fmt(val, kpi_type: str, currency: str = "USD") -> str:
    if val is None:
        return "N/A"
    sym = "$" if currency == "USD" else "MX$"
    if kpi_type == "currency":
        return f"{sym}{val:,.2f}"
    if kpi_type == "percent":
        return f"{val:.2f}%"
    if kpi_type == "ratio":
        return f"{val:.2f}x"
    if isinstance(val, int) or (isinstance(val, float) and val == int(val)):
        return f"{int(val):,}"
    return f"{val:,.2f}"


def _delta_cell(delta: dict) -> tuple[str, colors.Color]:
    """Return (display_string, color)."""
    display = delta.get("display", "N/A")
    is_good = delta.get("is_good")
    if is_good is True:
        return display, GREEN
    if is_good is False:
        return display, RED
    return display, MUTED


def _kpi_table(fields, current_obj, prior_obj, deltas, currency="USD"):
    data = [["KPI", "Current", "Prior Year", "YoY Change"]]
    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), DARK),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LIGHT_BG]),
        ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
    ]
    for i, field in enumerate(fields):
        r = i + 1
        label = KPI_LABELS.get(field, field)
        ktype = KPI_TYPE.get(field, "number")
        curr_val = getattr(current_obj, field) if current_obj else None
        prior_val = getattr(prior_obj, field) if prior_obj else None
        delta = deltas.get(field, {})
        delta_str, delta_color = _delta_cell(delta)

        data.append([
            label,
            _fmt(curr_val, ktype, currency),
            _fmt(prior_val, ktype, currency),
            delta_str,
        ])
        if delta.get("is_good") is True:
            style_cmds.append(("TEXTCOLOR", (3, r), (3, r), GREEN))
            style_cmds.append(("FONTNAME", (3, r), (3, r), "Helvetica-Bold"))
        elif delta.get("is_good") is False:
            style_cmds.append(("TEXTCOLOR", (3, r), (3, r), RED))
            style_cmds.append(("FONTNAME", (3, r), (3, r), "Helvetica-Bold"))

    col_widths = [5 * cm, 3.8 * cm, 3.8 * cm, 3.2 * cm]
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle(style_cmds))
    return t


def _section_bar(text: str, styles):
    data = [[Paragraph(f"<b>{text}</b>", styles["section"])]]
    t = Table(data, colWidths=[15.8 * cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), ORANGE),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return t


# ── Narrative generation ─────────────────────────────────────────────────────

_WENT_WELL_TEMPLATES = {
    "revenue": "Las ventas alcanzaron {curr} ({delta} YoY), liderando el crecimiento de la cuenta.",
    "sessions": "El tráfico creció {delta} interanual, con {curr} sesiones vs {prior} el año anterior.",
    "conv_pct": "La tasa de conversión mejoró {delta} ppt YoY, llegando a {curr}.",
    "ad_sales": "Las ventas de ads aumentaron {delta} YoY hasta {curr}.",
    "roas": "El ROAS mejoró a {curr} ({delta} vs año anterior), reflejando mayor eficiencia publicitaria.",
    "acos_pct": "El ACoS bajó {delta} ppt YoY a {curr}, indicando mejor eficiencia de inversión.",
    "impressions": "Las impresiones crecieron {delta} YoY, con mayor visibilidad en los resultados de búsqueda.",
    "ordered_units": "Las unidades ordenadas aumentaron {delta} YoY, alcanzando {curr} unidades.",
    "orders": "Los pedidos de ads crecieron {delta} YoY hasta {curr} órdenes.",
    "ntb_units": "Las unidades NTB (nuevos clientes) aumentaron {delta} YoY, sumando {curr} unidades.",
}

_OPTIMIZE_TEMPLATES = {
    "acos_pct": "El ACoS se deterioró {delta} ppt YoY a {curr}; hay oportunidad de optimizar la eficiencia de inversión.",
    "tacos_pct": "El TACoS subió {delta} ppt YoY a {curr}; revisar la eficiencia del gasto total de ads.",
    "revenue": "Las ventas cayeron {delta} YoY a {curr}; analizar tráfico y conversión para recuperar volumen.",
    "sessions": "El tráfico bajó {delta} YoY a {curr} sesiones; evaluar estrategia orgánica y de ads.",
    "conv_pct": "La conversión bajó {delta} ppt YoY a {curr}; revisar listings y precio.",
    "cpc": "El CPC aumentó {delta} YoY a {curr}; evaluar pujas y targeting.",
    "roas": "El ROAS bajó {delta} YoY a {curr}; revisar eficiencia de campañas.",
    "ad_spend": "El gasto en ads subió {delta} YoY a {curr} sin incremento proporcional en ventas.",
}

EXCLUDE_FROM_NARRATIVE = {"avg_retail", "buybox_win_pct"}


def _generate_narratives(
    current_account: AccountSummary,
    prior_account: AccountSummary,
    current_ads: AdPerformance,
    prior_ads: AdPerformance,
    deltas: dict,
    currency: str = "USD",
) -> tuple[list[str], list[str]]:
    """Return (went_well_list, optimize_list) — all in Spanish."""

    from app.engine.kpis import ACCOUNT_FIELDS, ADS_FIELDS
    all_fields = ACCOUNT_FIELDS + ADS_FIELDS

    improvements = []
    declines = []

    for field in all_fields:
        if field in EXCLUDE_FROM_NARRATIVE:
            continue
        delta = deltas.get(field, {})
        if delta.get("base_baja"):
            continue
        if delta.get("value") is None:
            continue
        ktype = KPI_TYPE.get(field, "number")
        is_good = delta.get("is_good")

        if field in (ACCOUNT_FIELDS):
            curr_obj, prior_obj = current_account, prior_account
        else:
            curr_obj, prior_obj = current_ads, prior_ads

        curr_val = getattr(curr_obj, field) if curr_obj else None
        prior_val = getattr(prior_obj, field) if prior_obj else None
        curr_str = _fmt(curr_val, ktype, currency)
        prior_str = _fmt(prior_val, ktype, currency)
        delta_str = delta.get("display", "")

        ctx = {"curr": curr_str, "prior": prior_str, "delta": delta_str}

        if is_good is True and field in _WENT_WELL_TEMPLATES:
            improvements.append((abs(delta.get("value") or 0), field, ctx))
        elif is_good is False and field in _OPTIMIZE_TEMPLATES:
            declines.append((abs(delta.get("value") or 0), field, ctx))

    # Top 2-3 improvements, 1-2 declines
    improvements.sort(reverse=True)
    declines.sort(reverse=True)

    went_well = []
    for _, field, ctx in improvements[:3]:
        tmpl = _WENT_WELL_TEMPLATES.get(field, "")
        if tmpl:
            went_well.append(tmpl.format(**ctx))

    optimize = []
    for _, field, ctx in declines[:2]:
        tmpl = _OPTIMIZE_TEMPLATES.get(field, "")
        if tmpl:
            optimize.append(tmpl.format(**ctx))

    return went_well, optimize


# ── Cover page ────────────────────────────────────────────────────────────────

def _build_cover(
    canvas_obj, doc,
    account_name: str,
    period_current: str,
    period_prior: str,
    cover_image_bytes: Optional[bytes] = None,
):
    canvas_obj.saveState()
    # Full-bleed orange background
    canvas_obj.setFillColor(ORANGE)
    canvas_obj.rect(0, 0, W, H, fill=1, stroke=0)

    if cover_image_bytes:
        try:
            img_buf = io.BytesIO(cover_image_bytes)
            canvas_obj.drawImage(img_buf, 0, 0, W, H,
                                  preserveAspectRatio=False, mask="auto")
            # Semi-transparent orange overlay
            canvas_obj.setFillColorRGB(0.91, 0.25, 0, alpha=0.65)
            canvas_obj.rect(0, 0, W, H, fill=1, stroke=0)
        except Exception:
            pass  # Fall back to plain orange cover

    # Capybaras logo text
    canvas_obj.setFillColor(WHITE)
    canvas_obj.setFont("Helvetica-Bold", 11)
    canvas_obj.drawString(2 * cm, H - 2 * cm, "CAPYBARAS")
    canvas_obj.setFont("Helvetica", 9)
    canvas_obj.drawString(2 * cm, H - 2.7 * cm, "Amazon Agency")

    # Decorative lines
    canvas_obj.setStrokeColor(WHITE)
    canvas_obj.setLineWidth(0.5)
    canvas_obj.line(2 * cm, H * 0.48, W - 2 * cm, H * 0.48)
    canvas_obj.line(2 * cm, H * 0.47, W - 2 * cm, H * 0.47)

    # Account name
    canvas_obj.setFillColor(WHITE)
    canvas_obj.setFont("Helvetica-Bold", 28)
    canvas_obj.drawCentredString(W / 2, H * 0.52, account_name)

    # Report type
    canvas_obj.setFont("Helvetica", 14)
    canvas_obj.drawCentredString(W / 2, H * 0.44, "Weekly YoY Performance Report")

    # Periods
    canvas_obj.setFont("Helvetica", 11)
    canvas_obj.drawCentredString(W / 2, H * 0.39,
                                   f"{period_current}  vs  {period_prior}")

    # Footer
    canvas_obj.setFont("Helvetica", 8)
    canvas_obj.drawCentredString(W / 2, 1.5 * cm, "Prepared by Capybaras Agency")

    canvas_obj.restoreState()


# ── Main generate function ────────────────────────────────────────────────────

def generate(
    account_name: str,
    period_current: str,
    period_prior: str,
    current_account: AccountSummary,
    prior_account: AccountSummary,
    current_ads: AdPerformance,
    prior_ads: AdPerformance,
    cover_image_bytes: Optional[bytes] = None,
    week_number: Optional[int] = None,
    currency: str = "USD",
) -> bytes:
    """Return the full PDF report as bytes."""

    styles = _styles()
    deltas = build_deltas(current_account, prior_account, current_ads, prior_ads)
    went_well, optimize = _generate_narratives(
        current_account, prior_account, current_ads, prior_ads, deltas, currency
    )

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )

    story = []

    # ── Cover (drawn via canvas callback, not flowables) ──────────────────
    def cover_page(canvas_obj, document):
        _build_cover(canvas_obj, document, account_name,
                     period_current, period_prior, cover_image_bytes)

    def later_pages(canvas_obj, document):
        pass

    # Blank first page placeholder for cover (just a tiny spacer + break)
    story.append(Spacer(1, 0.1))
    story.append(PageBreak())

    # ── Executive Summary ─────────────────────────────────────────────────
    story.append(_section_bar("EXECUTIVE SUMMARY", styles))
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph(
        f"<b>{account_name}</b>  ·  {period_current} vs {period_prior}", styles["body"]
    ))
    story.append(Spacer(1, 0.4 * cm))

    # What Went Well
    if went_well:
        story.append(Paragraph("<b>What Went Well</b>", styles["body"]))
        story.append(Spacer(1, 0.15 * cm))
        for item in went_well:
            story.append(Paragraph(f"• {item}", styles["body"]))
        story.append(Spacer(1, 0.3 * cm))

    # Areas to Optimize
    if optimize:
        story.append(Paragraph("<b>Areas to Optimize</b>", styles["body"]))
        story.append(Spacer(1, 0.15 * cm))
        for item in optimize:
            story.append(Paragraph(f"• {item}", styles["body"]))
        story.append(Spacer(1, 0.4 * cm))

    # Quick KPI snapshot (revenue, sessions, conv, ACOS, ROAS)
    highlight_fields = ["revenue", "sessions", "conv_pct", "acos_pct", "roas"]
    summary_data = [["KPI", "Current", "Prior Year", "YoY"]]
    for field in highlight_fields:
        ktype = KPI_TYPE.get(field, "number")
        if field in ACCOUNT_FIELDS:
            curr_obj, prior_obj = current_account, prior_account
        else:
            curr_obj, prior_obj = current_ads, prior_ads
        curr_val = getattr(curr_obj, field) if curr_obj else None
        prior_val = getattr(prior_obj, field) if prior_obj else None
        delta = deltas.get(field, {})
        summary_data.append([
            KPI_LABELS.get(field, field),
            _fmt(curr_val, ktype, currency),
            _fmt(prior_val, ktype, currency),
            delta.get("display", "N/A"),
        ])
    t = Table(summary_data, colWidths=[5 * cm, 3.5 * cm, 3.5 * cm, 3.3 * cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), DARK),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LIGHT_BG]),
        ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t)
    story.append(PageBreak())

    # ── Account Summary (Traffic & Sales) ────────────────────────────────
    story.append(_section_bar("ACCOUNT SUMMARY", styles))
    story.append(Spacer(1, 0.3 * cm))
    story.append(_kpi_table(ACCOUNT_FIELDS, current_account, prior_account, deltas, currency))
    story.append(PageBreak())

    # ── Advertising ───────────────────────────────────────────────────────
    story.append(_section_bar("ADVERTISING PERFORMANCE SUMMARY", styles))
    story.append(Spacer(1, 0.3 * cm))
    story.append(_kpi_table(ADS_FIELDS, current_ads, prior_ads, deltas, currency))
    story.append(PageBreak())

    # ── Profit & Loss ─────────────────────────────────────────────────────
    story.append(_section_bar("PROFIT & LOSS", styles))
    story.append(Spacer(1, 0.3 * cm))
    pl_data = [
        ["", period_current, period_prior],
        ["Gross Revenue (B2C)",
         _fmt(current_account.revenue, "currency", currency),
         _fmt(prior_account.revenue, "currency", currency)],
        ["Ad Spend",
         _fmt(current_ads.ad_spend if current_ads else None, "currency", currency),
         _fmt(prior_ads.ad_spend if prior_ads else None, "currency", currency)],
        ["Ad Spend % of Revenue",
         _fmt(current_ads.tacos_pct if current_ads else None, "percent"),
         _fmt(prior_ads.tacos_pct if prior_ads else None, "percent")],
        ["COGs", "— manual", "— manual"],
        ["FBA Fees", "— manual", "— manual"],
        ["Net Profit", "— manual", "— manual"],
    ]
    t_pl = Table(pl_data, colWidths=[6 * cm, 4 * cm, 4 * cm])
    t_pl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), DARK),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LIGHT_BG]),
        ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t_pl)
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph("Nota: No incluye Estimated Payout. "
                            "Completar COGs y fees manualmente.", styles["note"]))
    story.append(PageBreak())

    # ── Inventory & BSR ───────────────────────────────────────────────────
    story.append(_section_bar("INVENTORY & BSR", styles))
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph(
        "Los datos de Inventory, Days Cover, BSR y reseñas no están disponibles en los "
        "archivos fuente. Amazon no archiva estas métricas históricamente — "
        "para el año anterior se muestran como N/A.",
        styles["body"],
    ))
    story.append(PageBreak())

    # ── Account Health ────────────────────────────────────────────────────
    story.append(_section_bar("ACCOUNT HEALTH", styles))
    story.append(Spacer(1, 0.3 * cm))
    ah_data = [
        ["Metric", period_current, f"{period_prior} (N/A)"],
        ["Order Defect Rate", "—", "N/A"],
        ["Late Shipment Rate", "—", "N/A"],
        ["Cancellation Rate", "—", "N/A"],
        ["A-to-Z Claims", "—", "N/A"],
        ["Policy Violations", "—", "N/A"],
    ]
    t_ah = Table(ah_data, colWidths=[7 * cm, 4 * cm, 4 * cm])
    t_ah.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), DARK),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LIGHT_BG]),
        ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t_ah)
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph(
        "Completar Account Health manualmente desde Seller Central.", styles["note"]
    ))

    doc.build(story, onFirstPage=cover_page, onLaterPages=later_pages)
    return buf.getvalue()


def build_filename(account_name: str, week_number: Optional[int],
                   period_current: str, period_prior: str) -> str:
    wk = f"Week {week_number:02d}" if week_number else "Weekly"
    clean = account_name.replace("/", "-")
    return f"{clean} - {wk} - {period_current} vs {period_prior}.pdf"
