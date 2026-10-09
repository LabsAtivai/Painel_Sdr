from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.schema import SDR, Confirmacao, EmailEnviado
from app.templating import templates

router = APIRouter()


@router.get("/emails")
def emails(request: Request, db: Session = Depends(get_db)):
    hoje = date.today()
    dias = [hoje - timedelta(days=i) for i in range(13, -1, -1)]
    mapa = {(s, d): t for s, d, t in db.execute(
        select(EmailEnviado.sdr_id, EmailEnviado.data_registro, EmailEnviado.quantidade).where(EmailEnviado.data_registro >= dias[0]))}
    linhas = []
    for s in db.scalars(select(SDR).where(SDR.ativo.is_(True)).order_by(SDR.nome)):
        serie = [mapa.get((s.id, d)) for d in dias]
        linhas.append({"sdr": s, "serie": serie, "hoje": serie[-1], "ontem": serie[-2],
                       "sete": sum(v or 0 for v in serie[-7:]), "catorze": sum(v or 0 for v in serie), "tem": any(v is not None for v in serie)})
    linhas.sort(key=lambda l: -l["sete"])
    maior = max((v or 0 for l in linhas for v in l["serie"]), default=0) or 1

    desde = datetime.combine(hoje - timedelta(days=30), datetime.min.time())
    conf = db.execute(
        select(func.coalesce(SDR.nome, Confirmacao.remetente), func.sum(Confirmacao.quantidade), func.max(Confirmacao.data_registro))
        .select_from(Confirmacao).join(SDR, SDR.id == Confirmacao.sdr_id, isouter=True)
        .where(Confirmacao.data_registro >= desde).group_by(func.coalesce(SDR.nome, Confirmacao.remetente))
        .order_by(func.sum(Confirmacao.quantidade).desc())).all()
    return templates.TemplateResponse(request, "emails.html", {
        "linhas": linhas, "dias": dias, "maior": maior, "conf": conf,
        "tot_hoje": sum(l["hoje"] or 0 for l in linhas), "tot_sete": sum(l["sete"] for l in linhas), "page": "emails"})
