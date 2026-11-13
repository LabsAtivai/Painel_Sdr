from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.schema import SDR, Agenda, Confirmacao, ContagemReuniao, EmailEnviado, Resposta
from app.templating import templates

router = APIRouter()


@router.get("/analytics")
def analytics(request: Request, dias: int = 90, ano: int | None = None, mes: int = 0, db: Session = Depends(get_db)):
    dias = dias if dias in (30, 90, 365) else 90
    C, Rp = ContagemReuniao, Resposta
    anos = [a for (a,) in db.execute(select(func.strftime("%Y", C.data)).distinct().order_by(func.strftime("%Y", C.data).desc()))]
    ano = ano or (int(anos[0]) if anos else date.today().year)

    def periodo(col, stmt):
        stmt = stmt.where(func.strftime("%Y", col) == str(ano))
        return stmt.where(func.strftime("%m", col) == f"{mes:02d}") if mes else stmt

    nome = func.coalesce(SDR.nome, "(sem SDR)")
    S = lambda c: func.coalesce(func.sum(c), 0)  # noqa: E731
    funil = db.execute(periodo(C.data, select(
        nome, S(C.diretas), S(C.follow_up), S(C.qualificacao), S(C.proposta), S(C.venda), S(C.ns_qualificacao), S(C.ns_proposta), S(C.com_decisor))
        .select_from(C).join(SDR, SDR.id == C.sdr_id, isouter=True)).group_by(nome)).all()
    funil = sorted(funil, key=lambda r: -(r[3] + r[4]))
    tot_f = [sum(r[i] for r in funil) for i in range(1, 9)]
    mensal = db.execute(select(func.strftime("%m", C.data), S(C.qualificacao), S(C.proposta), S(C.venda), S(C.ns_qualificacao + C.ns_proposta))
                        .where(func.strftime("%Y", C.data) == str(ano)).group_by(func.strftime("%m", C.data)).order_by(func.strftime("%m", C.data))).all()
    resp = db.execute(periodo(Rp.data, select(nome, S(Rp.enviado), S(Rp.aberto), S(Rp.respondido)).select_from(Rp)
                              .join(SDR, SDR.id == Rp.sdr_id, isouter=True)).group_by(nome).order_by(S(Rp.respondido).desc())).all()
    desde = date.today() - timedelta(days=dias)
    desde_dt = datetime.combine(desde, datetime.min.time())
    titulo = func.lower(Agenda.titulo_reuniao)

    ag = {(s, bool(p)): n for s, p, n in db.execute(
        select(Agenda.sdr_id, titulo.like("%proposta%"), func.count()).where(Agenda.data_inicio >= desde_dt, Agenda.data_inicio < datetime.now())
        .group_by(Agenda.sdr_id, titulo.like("%proposta%")))}
    em = dict(db.execute(select(EmailEnviado.sdr_id, func.sum(EmailEnviado.quantidade)).where(EmailEnviado.data_registro >= desde).group_by(EmailEnviado.sdr_id)).all())
    cf = dict(db.execute(select(Confirmacao.sdr_id, func.sum(Confirmacao.quantidade)).where(Confirmacao.data_registro >= desde_dt).group_by(Confirmacao.sdr_id)).all())

    linhas = []
    for s in db.scalars(select(SDR).order_by(SDR.nome)):
        reun, prop, env, conf = ag.get((s.id, False), 0), ag.get((s.id, True), 0), em.get(s.id) or 0, cf.get(s.id) or 0
        total = reun + prop
        if not (total or env or conf):
            continue
        linhas.append({"sdr": s, "reunioes": reun, "propostas": prop, "total": total, "emails": env, "confirmacoes": conf,
                       "conv": (prop * 100 / total) if total else None, "por_mil": (total * 1000 / env) if env else None})
    linhas.sort(key=lambda l: -l["total"])

    sem = db.execute(select(func.strftime("%Y-%W", Agenda.data_inicio), func.count()).where(Agenda.data_inicio >= desde_dt, Agenda.data_inicio < datetime.now())
                     .group_by(func.strftime("%Y-%W", Agenda.data_inicio)).order_by(func.strftime("%Y-%W", Agenda.data_inicio))).all()
    tot_r, tot_p = sum(l["reunioes"] for l in linhas), sum(l["propostas"] for l in linhas)
    return templates.TemplateResponse(request, "analytics.html", {
        "funil": funil, "tot_f": tot_f, "mensal": mensal, "resp": resp, "anos": anos, "ano": ano, "mes": mes,
        "linhas": linhas, "semanas": sem, "dias": dias, "maior_sem": max((n for _, n in sem), default=0) or 1,
        "tot": {"reunioes": tot_r, "propostas": tot_p, "conv": (tot_p * 100 / (tot_r + tot_p)) if tot_r + tot_p else None,
                "emails": sum(l["emails"] for l in linhas)}, "page": "analytics"})
