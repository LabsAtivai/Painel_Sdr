import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles

from app.database import SessionLocal, init_db
from app.routes import agenda, analytics, credenciais, dashboard, emails, logs, rotina, sdrs
from app.services import seed_xlsx, sync_service

_basic = HTTPBasic(auto_error=False)


def require_auth(cred: HTTPBasicCredentials | None = Depends(_basic)):
    """Basic auth opcional: ativa se PANEL_USER e PANEL_PASSWORD estiverem definidos."""
    user, pwd = os.getenv("PANEL_USER"), os.getenv("PANEL_PASSWORD")
    if not (user and pwd):
        return
    ok = cred and secrets.compare_digest(cred.username, user) and secrets.compare_digest(cred.password, pwd)
    if not ok:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, headers={"WWW-Authenticate": "Basic"})


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    with SessionLocal() as db:
        seed_xlsx.import_seed(db)
        seed_xlsx.import_extras(db)
    sync_service.start_scheduler()
    yield


app = FastAPI(title="Controle SDRs", lifespan=lifespan, dependencies=[Depends(require_auth)])
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
for r in (dashboard, agenda, rotina, emails, analytics, sdrs, credenciais, logs):
    app.include_router(r.router)


@app.get("/health", include_in_schema=False)
def health():
    return {"ok": True}
