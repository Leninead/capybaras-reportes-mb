import re
from typing import Optional


def parse_number(val) -> Optional[float]:
    """Parse '$1,234.56', '12.5%', '1.234,56' etc. into float. Returns None for empty/dash."""
    if val is None:
        return None
    s = str(val).strip()
    if s in ("", "--", "—", "N/A", "n/a", "#N/A", "#VALUE!", "#REF!"):
        return None
    # Remove currency symbols, spaces; keep digits, dot, comma, minus
    s = re.sub(r"[^\d.,\-]", "", s)
    if not s or s in ("-", "."):
        return None
    # Handle European decimal comma: "1.234,56" → detect if last separator is comma
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        # Could be thousands separator ("1,234") or decimal ("1,5")
        parts = s.split(",")
        if len(parts) == 2 and len(parts[1]) <= 2:
            s = s.replace(",", ".")
        else:
            s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def find_col(headers: list, aliases: list) -> Optional[str]:
    """Return the first header that matches any alias (exact first, then case-insensitive)."""
    for alias in aliases:
        if alias in headers:
            return alias
    lower_map = {h.lower(): h for h in headers}
    for alias in aliases:
        if alias.lower() in lower_map:
            return lower_map[alias.lower()]
    return None
