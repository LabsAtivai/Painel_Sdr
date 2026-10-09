import threading
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.schema import ExecutionLog
from app.services import sync_service
from app.templating import templates

router = APIRouter()


@router.get("/logs")
def logs(request: Request, origem: str | None = None, db: Session = Depends(get_db)):
    stmt = select(ExecutionLog).order_by(ExecutionLog.id.desc()).limit(150)
    if origem:
        stmt = stmt.where(ExecutionLog.modulo == origem)
    return templates.TemplateResponse(request, "logs.html", {
        "logs": db.scalars(stmt).all(), "origem": origem, "origens": sync_service.MODULOS, "page": "logs",
    })


@router.post("/sync")
def sync_now(next: str = Form("/logs")):
    if not sync_service.is_running():
        threading.Thread(target=sync_service.run_sync, kwargs={"trigger": "manual"}, daemon=True).start()
    dest = next if urlparse(next).netloc == "" and next.startswith("/") and not next.startswith("//") else "/logs"
    return RedirectResponse(dest, status_code=303)


@router.get("/api/sync-status")
def sync_status():
    return JSONResponse({"rodando": sync_service.is_running()})
