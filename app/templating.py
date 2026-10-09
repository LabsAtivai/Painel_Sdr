from datetime import date, datetime
from pathlib import Path

from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models.schema import ExecutionLog
from app.services import sync_service

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
_env = templates.env

_DIAS = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]


def _dt(v, fmt="%d/%m/%Y %H:%M"):
    return v.strftime(fmt) if v else "—"


def _ago(v):
    if not v:
        return "nunca"
    s = int((datetime.now() - v).total_seconds())
    if s < 60:
        return "agora há pouco"
    if s < 3600:
        return f"há {s // 60} min"
    if s < 86400:
        return f"há {s // 3600} h"
    return f"há {s // 86400} d"


def _fase_class(fase):
    n = (fase or "").lower()
    if "avan" in n:
        return "avanco"
    if "encam" in n:
        return "encam"
    if "follow" in n:
        return "follow"
    return "outro"


def _weekday(v):
    return _DIAS[v.weekday()] if isinstance(v, (date, datetime)) else ""


def _mask(secret):
    return f"••••{secret[-4:]}" if secret and len(secret) > 4 else ("••••" if secret else "")


def sync_status():
    """Última execução por origem + se há sync rodando (barra global do topo)."""
    with SessionLocal() as db:
        last_ids = select(func.max(ExecutionLog.id)).where(ExecutionLog.modulo.isnot(None)).group_by(ExecutionLog.modulo)
        rows = db.scalars(select(ExecutionLog).where(ExecutionLog.id.in_(last_ids)).order_by(ExecutionLog.modulo)).all()
    return {
        "rodando": sync_service.is_running(),
        "origens": rows,
        "ultima": max((r.data_execucao for r in rows), default=None),
        "erros": [r.modulo for r in rows if r.status != "SUCCESS"],
    }


_env.filters.update(dt=_dt, ago=_ago, fase_class=_fase_class, weekday=_weekday, mask=_mask)
_env.globals["sync_status"] = sync_status
