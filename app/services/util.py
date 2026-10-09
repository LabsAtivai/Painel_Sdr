import re
import unicodedata
from datetime import date, datetime

_DATE_FORMATS = (
    "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y",
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
)


def norm(s) -> str:
    s = unicodedata.normalize("NFD", str(s or ""))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def parse_date(v) -> datetime | None:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, datetime):
        return v
    if isinstance(v, date):
        return datetime.combine(v, datetime.min.time())
    if isinstance(v, (int, float)):
        try:
            return datetime.fromtimestamp(v / 1000 if v > 1e11 else v)
        except (OverflowError, OSError, ValueError):
            return None
    s = str(v).strip()
    if not s or norm(s) in ("n a", "na", "null", "none"):
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def to_int(v, default: int | None = 0) -> int | None:
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return int(v)
    m = re.search(r"-?\d+", str(v or ""))
    return int(m.group()) if m else default


def days_since(d: datetime | None) -> int:
    return max((datetime.now() - d).days, 0) if d else 0
