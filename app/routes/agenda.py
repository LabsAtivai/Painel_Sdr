from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.schema import SDR, Agenda
from app.services.confirmacao_match import Confirmacoes
from app.templating import templates

router = APIRouter()


def _d(d: date) -> datetime:
    return datetime.combine(d, datetime.min.time())


def _janela(filtro: str):
    hoje = date.today()
    seg_semana = hoje - timedelta(days=hoje.weekday())
    prox_seg = hoje + timedelta(days=7 - hoje.weekday())
    dia = {"hoje": hoje, "amanha": hoje + timedelta(days=1), "segunda": prox_seg}
    if filtro in dia:
        return dia[filtro], dia[filtro] + timedelta(days=1)
    return seg_semana, seg_semana + timedelta(days=7)


@router.get("/agenda")
def agenda(request: Request, filtro: str = "hoje", db: Session = Depends(get_db)):
    if filtro not in ("hoje", "amanha", "segunda", "semana"):
        filtro = "hoje"
    ini, fim = _janela(filtro)
    eventos = db.execute(
        select(Agenda, SDR.nome).join(SDR, SDR.id == Agenda.sdr_id, isouter=True)
        .where(Agenda.data_inicio >= _d(ini), Agenda.data_inicio < _d(fim)).order_by(Agenda.data_inicio)).all()
    conf = Confirmacoes(db, _d(ini), _d(fim))
    dias: dict[date, list] = {}
    for r, nome in eventos:
        dias.setdefault(r.data_inicio.date(), []).append((r, nome, conf.status(r.titulo_reuniao, r.email_convidado, r.data_inicio)))

    sem_ini, sem_fim = _janela("semana")
    semana = db.execute(
        select(Agenda, SDR.nome).join(SDR, SDR.id == Agenda.sdr_id)
        .where(Agenda.data_inicio >= _d(sem_ini), Agenda.data_inicio < _d(sem_fim))).all()
    conf_sem = Confirmacoes(db, _d(sem_ini), _d(sem_fim))
    metricas: dict[str, dict[str, int]] = {}
    for r, nome in semana:
        m = metricas.setdefault(nome, {"REUNIAO": 0, "PROPOSTA": 0, "SIM": 0, "NAO": 0})
        m["PROPOSTA" if "proposta" in (r.titulo_reuniao or "").lower() else "REUNIAO"] += 1
        st = conf_sem.status(r.titulo_reuniao, r.email_convidado, r.data_inicio)
        if st is not None:
            m["SIM" if st else "NAO"] += 1
    return templates.TemplateResponse(request, "agenda.html", {
        "filtro": filtro, "ini": ini, "fim": fim - timedelta(days=1), "dias": dias, "total": len(eventos),
        "metricas": sorted(metricas.items()), "cobertura": conf.cobertura, "sem_ini": sem_ini, "sem_fim": sem_fim - timedelta(days=1), "page": "agenda",
    })
