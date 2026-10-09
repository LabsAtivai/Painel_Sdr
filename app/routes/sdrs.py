from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.schema import SDR, Agenda, Confirmacao, DadoRelatorio, EmailEnviado
from app.templating import templates

router = APIRouter(prefix="/sdrs")


HISTORICO = (DadoRelatorio, Agenda, Confirmacao)


def _contagem(db: Session) -> dict:
    out: dict = {}
    for M in HISTORICO:
        for sid, n in db.execute(select(M.sdr_id, func.count()).group_by(M.sdr_id)):
            out[sid] = out.get(sid, 0) + n
    return out


def _back(msg: str):
    return RedirectResponse(f"/sdrs?msg={quote_plus(msg)}", status_code=303)


@router.get("")
def listar(request: Request, msg: str | None = None, db: Session = Depends(get_db)):
    counts = _contagem(db)
    sdrs = db.scalars(select(SDR).order_by(SDR.ativo.desc(), SDR.nome)).all()
    return templates.TemplateResponse(request, "sdrs.html", {
        "sdrs": sdrs, "counts": counts, "msg": msg, "page": "sdrs",
    })


@router.post("")
async def criar(request: Request, db: Session = Depends(get_db)):
    form = dict(await request.form())
    nome, email = (form.get("nome") or "").strip(), (form.get("email") or "").strip().lower()
    if not nome or "@" not in email:
        return _back("Informe nome e um e-mail válido")
    sdr = SDR(nome=nome[:100], email=email[:150])
    db.add(sdr)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return _back(f"E-mail já cadastrado: {email}")
    return _back(f"{nome} admitido")


@router.post("/{sdr_id}/editar")
async def editar(sdr_id: int, request: Request, db: Session = Depends(get_db)):
    sdr = db.get(SDR, sdr_id)
    if not sdr:
        return _back("SDR não encontrado")
    form = dict(await request.form())
    nome, email = (form.get("nome") or "").strip(), (form.get("email") or "").strip().lower()
    if not nome or "@" not in email:
        return _back("Informe nome e um e-mail válido")
    sdr.nome, sdr.email = nome[:100], email[:150]
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return _back(f"E-mail já cadastrado: {email}")
    return _back(f"{nome} atualizado")


@router.post("/{sdr_id}/status")
def alternar_status(sdr_id: int, db: Session = Depends(get_db)):
    sdr = db.get(SDR, sdr_id)
    if not sdr:
        return _back("SDR não encontrado")
    sdr.ativo = not sdr.ativo
    db.commit()
    return _back(f"{sdr.nome} reativado" if sdr.ativo else f"{sdr.nome} desligado; sai das próximas coletas, histórico preservado")


@router.post("/{sdr_id}/reatribuir")
def reatribuir(sdr_id: int, destino_id: int = Form(...), db: Session = Depends(get_db)):
    origem, destino = db.get(SDR, sdr_id), db.get(SDR, destino_id)
    if not origem or not destino or origem.id == destino.id:
        return _back("Escolha um SDR de destino diferente")
    n = sum(db.execute(update(M).where(M.sdr_id == sdr_id).values(sdr_id=destino_id)).rowcount for M in HISTORICO)
    db.execute(update(EmailEnviado).where(EmailEnviado.sdr_id == sdr_id).values(sdr_id=destino_id))
    db.commit()
    return _back(f"{n} registro(s) de {origem.nome} movidos para {destino.nome}")


@router.post("/{sdr_id}/excluir")
def excluir(sdr_id: int, db: Session = Depends(get_db)):
    sdr = db.get(SDR, sdr_id)
    if not sdr:
        return _back("SDR não encontrado")
    if _contagem(db).get(sdr_id):
        return _back("SDR tem histórico: reatribua os registros antes, ou apenas desligue")
    db.execute(EmailEnviado.__table__.delete().where(EmailEnviado.sdr_id == sdr_id))
    db.delete(sdr)
    db.commit()
    return _back("SDR excluído")
