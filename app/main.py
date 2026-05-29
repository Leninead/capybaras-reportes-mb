"""
Capybaras YoY Weekly Report Tool — FastAPI backend.
Stateless: files processed in memory, nothing persisted.
"""
import io
import json
import logging
import zipfile
from dataclasses import asdict
from datetime import date, timedelta
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.parsers import business_report, ads_report, merchantspring
from app.engine.kpis import (
    AccountSummary, AdPerformance, ParsedData,
    compute_derived, KPI_LABELS, KPI_TYPE, ACCOUNT_FIELDS, ADS_FIELDS,
)
from app.engine.deltas import build_deltas
from app.generators import excel_gen, pdf_gen

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Capybaras YoY Report Tool", version="1.0.0")


# ── Helpers ──────────────────────────────────────────────────────────────────

def _safe_read(field: str, val, ktype: str) -> Optional[float]:
    """Parse an overridden value from the verification form."""
    if val is None or str(val).strip() in ("", "null", "N/A", "n/a"):
        return None
    try:
        s = str(val).replace(",", "").replace("$", "").replace("%", "").strip()
        return float(s)
    except ValueError:
        raise HTTPException(400, f"Valor inválido para '{field}': '{val}'")


def _obj_to_dict(obj) -> dict:
    """Convert a dataclass to a JSON-safe dict (None → None, int → int)."""
    if obj is None:
        return {}
    d = asdict(obj)
    return {k: (int(v) if isinstance(v, float) and v == int(v) and k.endswith("_units") or k in
                ("ordered_units", "page_views", "sessions", "impressions",
                 "clicks", "orders", "units_ads", "ntb_units") and v is not None
               else v)
            for k, v in d.items()}


def _build_verification_payload(
    current_account: AccountSummary,
    prior_account: AccountSummary,
    current_ads: Optional[AdPerformance],
    prior_ads: Optional[AdPerformance],
    warnings: list[str],
) -> dict:
    compute_derived(current_account, current_ads or AdPerformance())
    compute_derived(prior_account, prior_ads or AdPerformance())

    deltas = build_deltas(current_account, prior_account,
                          current_ads or AdPerformance(),
                          prior_ads or AdPerformance())

    account_rows = []
    for f in ACCOUNT_FIELDS:
        ktype = KPI_TYPE.get(f, "number")
        account_rows.append({
            "field": f,
            "label": KPI_LABELS[f],
            "type": ktype,
            "current": getattr(current_account, f),
            "prior": getattr(prior_account, f),
            "delta": deltas[f],
        })

    ads_rows = []
    for f in ADS_FIELDS:
        ktype = KPI_TYPE.get(f, "number")
        ads_rows.append({
            "field": f,
            "label": KPI_LABELS[f],
            "type": ktype,
            "current": getattr(current_ads, f) if current_ads else None,
            "prior": getattr(prior_ads, f) if prior_ads else None,
            "delta": deltas[f],
        })

    return {
        "account_rows": account_rows,
        "ads_rows": ads_rows,
        "warnings": warnings,
    }


def _prior_period(current_start: str, current_end: str) -> tuple[str, str]:
    """Calculate prior-year period (same calendar dates, year - 1)."""
    try:
        fmt = "%d %b %Y"
        start = date.fromisoformat(current_start)
        end = date.fromisoformat(current_end)
        prior_start = start.replace(year=start.year - 1)
        prior_end = end.replace(year=end.year - 1)
        return prior_start.isoformat(), prior_end.isoformat()
    except Exception:
        return current_start, current_end


# ── Routes ────────────────────────────────────────────────────────────────────

@app.post("/api/parse")
async def parse_files(
    file_a: UploadFile = File(..., description="Current period — MerchantSpring Excel or weekly_report"),
    file_b: UploadFile = File(..., description="Prior year Business Report CSV"),
    file_c: UploadFile = File(..., description="Prior year Ads Campaign Report CSV/xlsx"),
    current_start: str = Form(...),
    current_end: str = Form(...),
    account_name: str = Form(...),
):
    """Parse the 3 source files and return KPIs for the verification step."""
    all_warnings: list[str] = []

    # Parse File A (current period)
    try:
        content_a = await file_a.read()
        data_a = merchantspring.parse(content_a, file_a.filename or "")
        all_warnings += data_a.warnings
    except ValueError as e:
        raise HTTPException(422, f"Error en Archivo A (período actual): {e}")

    # Parse File B (prior year Business Report)
    try:
        content_b = await file_b.read()
        data_b = business_report.parse(content_b)
        all_warnings += data_b.warnings
    except ValueError as e:
        raise HTTPException(422, f"Error en Archivo B (Business Report año anterior): {e}")

    # Parse File C (prior year Ads)
    try:
        content_c = await file_c.read()
        data_c = ads_report.parse(content_c, file_c.filename or "")
        all_warnings += data_c.warnings
    except ValueError as e:
        raise HTTPException(422, f"Error en Archivo C (Ads Report año anterior): {e}")

    current_account = data_a.account
    current_ads = data_a.ads or AdPerformance()
    prior_account = data_b.account
    prior_ads = data_c.ads or AdPerformance()

    # Fill TACOS/TROAS for prior ads using prior revenue
    if prior_account.revenue and prior_ads.ad_spend:
        rev = prior_account.revenue
        spend = prior_ads.ad_spend
        prior_ads.tacos_pct = spend / rev * 100
        prior_ads.troas = rev / spend

    prior_start, prior_end = _prior_period(current_start, current_end)

    payload = _build_verification_payload(
        current_account, prior_account, current_ads, prior_ads, all_warnings
    )
    payload["account_name"] = account_name
    payload["current_start"] = current_start
    payload["current_end"] = current_end
    payload["prior_start"] = prior_start
    payload["prior_end"] = prior_end

    return JSONResponse(payload)


@app.post("/api/generate")
async def generate_report(
    body: str = Form(...),                              # JSON payload with confirmed KPIs
    cover_image: Optional[UploadFile] = File(None),    # Optional cover photo
):
    """
    Accept confirmed KPI values (possibly edited by user) and
    generate PDF + Excel, returning them as a ZIP download.
    """
    try:
        data = json.loads(body)
    except json.JSONDecodeError as e:
        raise HTTPException(400, f"JSON inválido: {e}")

    account_name = data.get("account_name", "Account")
    current_start = data.get("current_start", "")
    current_end = data.get("current_end", "")
    prior_start = data.get("prior_start", "")
    prior_end = data.get("prior_end", "")
    currency = data.get("currency", "USD")
    week_number = data.get("week_number")

    period_current = f"{current_start} – {current_end}"
    period_prior = f"{prior_start} – {prior_end}"

    def row_to_obj(rows: list[dict], cls) -> object:
        obj = cls()
        for row in rows:
            f = row.get("field")
            val = row.get("current")
            if f and hasattr(obj, f):
                if val is not None:
                    ktype = KPI_TYPE.get(f, "number")
                    parsed = _safe_read(f, val, ktype)
                    setattr(obj, f, parsed)
        return obj

    def row_to_prior(rows: list[dict], cls) -> object:
        obj = cls()
        for row in rows:
            f = row.get("field")
            val = row.get("prior")
            if f and hasattr(obj, f):
                if val is not None:
                    ktype = KPI_TYPE.get(f, "number")
                    parsed = _safe_read(f, val, ktype)
                    setattr(obj, f, parsed)
        return obj

    account_rows = data.get("account_rows", [])
    ads_rows = data.get("ads_rows", [])

    current_account: AccountSummary = row_to_obj(account_rows, AccountSummary)
    prior_account: AccountSummary = row_to_prior(account_rows, AccountSummary)
    current_ads: AdPerformance = row_to_obj(ads_rows, AdPerformance)
    prior_ads: AdPerformance = row_to_prior(ads_rows, AdPerformance)

    compute_derived(current_account, current_ads)
    compute_derived(prior_account, prior_ads)

    cover_bytes: Optional[bytes] = None
    if cover_image and cover_image.filename:
        cover_bytes = await cover_image.read()

    # Generate both files
    try:
        xlsx_bytes = excel_gen.generate(
            account_name=account_name,
            period_current=period_current,
            period_prior=period_prior,
            current_account=current_account,
            prior_account=prior_account,
            current_ads=current_ads,
            prior_ads=prior_ads,
            week_number=week_number,
            currency=currency,
        )
    except Exception as e:
        log.exception("Excel generation failed")
        raise HTTPException(500, f"Error generando Excel: {e}")

    try:
        pdf_bytes = pdf_gen.generate(
            account_name=account_name,
            period_current=period_current,
            period_prior=period_prior,
            current_account=current_account,
            prior_account=prior_account,
            current_ads=current_ads,
            prior_ads=prior_ads,
            cover_image_bytes=cover_bytes,
            week_number=week_number,
            currency=currency,
        )
    except Exception as e:
        log.exception("PDF generation failed")
        raise HTTPException(500, f"Error generando PDF: {e}")

    xlsx_name = excel_gen.build_filename(account_name, week_number,
                                          period_current, period_prior)
    pdf_name = pdf_gen.build_filename(account_name, week_number,
                                       period_current, period_prior)

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(xlsx_name, xlsx_bytes)
        zf.writestr(pdf_name, pdf_bytes)
    zip_buf.seek(0)

    zip_filename = f"{account_name.replace('/', '-')} - YoY Report.zip"
    return StreamingResponse(
        zip_buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_filename}"'},
    )


@app.get("/healthz")
async def health():
    return {"status": "ok"}


# Serve the single-page frontend
app.mount("/", StaticFiles(directory="app/static", html=True), name="static")
