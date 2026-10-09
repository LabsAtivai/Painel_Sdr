from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, Request
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.schema import SDR, Agenda, Avanco, Confirmacao, DadoRelatorio, EmailEnviado
from app.templating import templates

router = APIRouter()
LIMITE = 15  # "Follow +15"
# Etapas encerradas/paradas do Streak: fora das tabelas dinâmicas de follow do Excel
FASES_INATIVAS = ("nutri", "sem interesse", "perdido", "cliente ganho", "repasse", "lead perdido")
PERIODOS = {"hoje": "Hoje", "ontem": "Ontem", "7d": "7 dias", "mes": "Mês"}
VISOES = ("ranking", "follows", "sem_data", "mais15", "avancos")


def _d(d: date) -> datetime:
    return datetime.combine(d, datetime.min.time())


@router.get("/")
def geral(request: Request, periodo: str = "hoje", db: Session = Depends(get_db)):
    hoje = date.today()
    if periodo not in PERIODOS:
        periodo = "hoje"
    p_ini, p_fim = {"hoje": (hoje, hoje), "ontem": (hoje - timedelta(days=1),) * 2, "7d": (hoje - timedelta(days=6), hoje),
                    "mes": (hoje.replace(day=1), hoje)}[periodo]
    seg = hoje - timedelta(days=hoje.weekday())
    sdrs = db.scalars(select(SDR).where(SDR.ativo.is_(True)).order_by(SDR.nome)).all()

    follows = {r[0]: r[1:] for r in db.execute(
        select(DadoRelatorio.sdr_id, func.count(), func.sum(case(((DadoRelatorio.dias_desde_ultimo_email > LIMITE) & _ativa(DadoRelatorio.fase), 1), else_=0)),
               func.max(DadoRelatorio.dias_atraso)).group_by(DadoRelatorio.sdr_id))}
    sem = dict(db.execute(select(Agenda.sdr_id, func.count()).where(
        Agenda.data_inicio >= _d(seg), Agenda.data_inicio < _d(seg + timedelta(days=7))).group_by(Agenda.sdr_id)).all())
    hoje_ag = dict(db.execute(select(Agenda.sdr_id, func.count()).where(
        Agenda.data_inicio >= _d(hoje), Agenda.data_inicio < _d(hoje + timedelta(days=1))).group_by(Agenda.sdr_id)).all())
    em_hoje = dict(db.execute(select(EmailEnviado.sdr_id, func.sum(EmailEnviado.quantidade)).where(
        EmailEnviado.data_registro >= p_ini, EmailEnviado.data_registro <= p_fim).group_by(EmailEnviado.sdr_id)).all())
    mes_ini = _d(hoje.replace(day=1))
    reun_mes = dict(db.execute(select(Agenda.sdr_id, func.count()).where(Agenda.data_inicio >= mes_ini, Agenda.data_inicio < _d(hoje + timedelta(days=1))).group_by(Agenda.sdr_id)).all())
    em_7 = dict(db.execute(select(EmailEnviado.sdr_id, func.sum(EmailEnviado.quantidade)).where(
        EmailEnviado.data_registro > hoje - timedelta(days=7)).group_by(EmailEnviado.sdr_id)).all())

    linhas = []
    for s in sdrs:
        f = follows.get(s.id, (0, 0, 0))
        linhas.append({"sdr": s, "follows": f[0], "mais15": f[1] or 0, "maior": f[2] or 0, "reunioes_sem": sem.get(s.id, 0),
                       "reunioes_hoje": hoje_ag.get(s.id, 0), "reunioes_mes": reun_mes.get(s.id, 0), "emails_hoje": em_hoje.get(s.id), "emails_7": em_7.get(s.id) or 0})
    linhas.sort(key=lambda l: (-l["mais15"], l["sdr"].nome))

    alertas = db.execute(
        select(DadoRelatorio, SDR.nome).join(SDR, SDR.id == DadoRelatorio.sdr_id, isouter=True)
        .where(DadoRelatorio.dias_desde_ultimo_email > LIMITE, _ativa(DadoRelatorio.fase)).order_by(DadoRelatorio.dias_desde_ultimo_email.desc()).limit(8)).all()
    kpi = {
        "follows": sum(l["follows"] for l in linhas), "mais15": sum(l["mais15"] for l in linhas),
        "reunioes_hoje": sum(l["reunioes_hoje"] for l in linhas), "reunioes_sem": sum(l["reunioes_sem"] for l in linhas),
        "emails_hoje": sum(l["emails_hoje"] or 0 for l in linhas),
        "confirmacoes": db.scalar(select(func.coalesce(func.sum(Confirmacao.quantidade), 0)).where(
            Confirmacao.data_registro >= _d(hoje - timedelta(days=7)))),
        "sem_coleta": [l["sdr"].nome for l in linhas if l["emails_hoje"] is None],
    }
    return templates.TemplateResponse(request, "geral.html", {"linhas": linhas, "alertas": alertas, "kpi": kpi, "periodo": periodo, "periodos": PERIODOS, "limite": LIMITE, "page": "geral"})


def _ranking(request: Request, sdr_id, fase, q, mais15, db: Session):
    def filtered(stmt):
        if sdr_id == 0:
            stmt = stmt.where(DadoRelatorio.sdr_id.is_(None))
        elif sdr_id:
            stmt = stmt.where(DadoRelatorio.sdr_id == sdr_id)
        if fase:
            stmt = stmt.where(DadoRelatorio.fase == fase)
        if q:
            stmt = stmt.where(DadoRelatorio.cliente.ilike(f"%{q}%"))
        if mais15:
            stmt = stmt.where(DadoRelatorio.dias_atraso > LIMITE)
        return stmt

    D = DadoRelatorio
    por_fase = dict(db.execute(filtered(select(D.fase, func.count()).group_by(D.fase))).all())
    total = sum(por_fase.values())
    em_atraso = db.scalar(filtered(select(func.count()).select_from(D).where(D.dias_atraso > 0)))
    acima = db.scalar(filtered(select(func.count()).select_from(D).where(D.dias_atraso > LIMITE)))

    nome = func.coalesce(SDR.nome, "(sem SDR)")
    cnt = lambda cond: func.coalesce(func.sum(case((cond, 1), else_=0)), 0)  # noqa: E731
    fa = func.lower(func.coalesce(D.fase, ""))
    por_sdr = db.execute(filtered(
        select(nome, func.count(), cnt(fa.like("%avan%")), cnt(fa.like("%encam%")), cnt(fa.like("%follow%")),
               cnt(D.dias_atraso > LIMITE), func.coalesce(func.max(D.dias_atraso), 0))
        .select_from(D).join(SDR, SDR.id == D.sdr_id, isouter=True)
        .group_by(nome).order_by(cnt(D.dias_atraso > LIMITE).desc(), func.count().desc()))).all()
    linhas = db.execute(filtered(
        select(D, SDR.nome).join(SDR, SDR.id == D.sdr_id, isouter=True)
        .order_by(D.dias_atraso.desc(), D.follow_up.asc()).limit(200))).all()
    maior = max((r.dias_atraso for r, _ in linhas), default=0) or 1
    return templates.TemplateResponse(request, "follows.html", {
        "total": total, "em_atraso": em_atraso, "acima": acima, "por_fase": por_fase, "por_sdr": por_sdr,
        "linhas": linhas, "maior": maior, "limite": LIMITE,
        "sdrs": db.scalars(select(SDR).order_by(SDR.nome)).all(),
        "fases_disp": [r[0] for r in db.execute(select(D.fase).distinct().order_by(D.fase)) if r[0]],
        "f": {"sdr_id": sdr_id, "fase": fase, "q": q or "", "mais15": mais15}, "page": "follows",
    })


def _ativa(col):
    f = func.lower(func.coalesce(col, ""))
    cond = ~f.like("%" + FASES_INATIVAS[0] + "%")
    for k in FASES_INATIVAS[1:]:
        cond = cond & ~f.like("%" + k + "%")
    return cond


def pivot_follows(db: Session, visao: str, sdr_id: int | None, q: str | None, por_grupo: int = 150):
    """Tabelas dinâmicas do Dashboard do Excel: SDR > Fase > Cliente com SUM de dias de atraso e dias desde o último e-mail."""
    D = DadoRelatorio
    stmt = select(D, func.coalesce(SDR.nome, "(sem SDR)")).join(SDR, SDR.id == D.sdr_id, isouter=True).where(_ativa(D.fase))
    if visao == "follows":  # com data de follow-up já vencida
        stmt = stmt.where(D.follow_up.isnot(None), D.dias_atraso > 0).order_by(D.dias_atraso.desc())
    elif visao == "sem_data":
        stmt = stmt.where(D.follow_up.is_(None)).order_by(D.dias_desde_ultimo_email.desc())
    else:  # mais15: mais de 15 dias desde o último e-mail
        stmt = stmt.where(D.dias_desde_ultimo_email > LIMITE).order_by(D.dias_desde_ultimo_email.desc())
    if sdr_id == 0:
        stmt = stmt.where(D.sdr_id.is_(None))
    elif sdr_id:
        stmt = stmt.where(D.sdr_id == sdr_id)
    if q:
        stmt = stmt.where(D.cliente.ilike(f"%{q}%"))
    grupos: dict[str, dict] = {}
    for r, nome in db.execute(stmt):
        g = grupos.setdefault(nome, {"fases": {}, "n": 0, "atraso": 0, "ult": 0})
        f = g["fases"].setdefault(r.fase or "Sem fase", {"rows": [], "n": 0, "atraso": 0, "ult": 0})
        for t in (g, f):
            t["n"] += 1
            t["atraso"] += r.dias_atraso or 0
            t["ult"] += r.dias_desde_ultimo_email or 0
        if len(f["rows"]) < por_grupo:
            f["rows"].append(r)
    ordem = sorted(grupos.items(), key=lambda kv: -kv[1]["n"])
    total = {"n": sum(g["n"] for _, g in ordem), "atraso": sum(g["atraso"] for _, g in ordem), "ult": sum(g["ult"] for _, g in ordem)}
    return ordem, total


def pivot_avancos(db: Session, sdr_id: int | None, q: str | None, dias: int):
    """Dashboard A:C do Excel: SDR > Fase > contatos que avançaram."""
    stmt = select(Avanco, func.coalesce(SDR.nome, "(sem SDR)")).join(SDR, SDR.id == Avanco.sdr_id, isouter=True).order_by(Avanco.data.desc())
    if dias:
        stmt = stmt.where(Avanco.data >= date.today() - timedelta(days=dias))
    if sdr_id:
        stmt = stmt.where(Avanco.sdr_id == sdr_id)
    if q:
        stmt = stmt.where(Avanco.empresa.ilike(f"%{q}%") | Avanco.contato.ilike(f"%{q}%"))
    grupos: dict[str, dict] = {}
    for r, nome in db.execute(stmt):
        g = grupos.setdefault(nome, {"fases": {}, "n": 0})
        f = g["fases"].setdefault(r.fase or "Sem fase", {"rows": [], "n": 0})
        g["n"] += 1
        f["n"] += 1
        if len(f["rows"]) < 50:
            f["rows"].append(r)
    ordem = sorted(grupos.items(), key=lambda kv: -kv[1]["n"])
    return ordem, sum(g["n"] for _, g in ordem)


@router.get("/follows")
def follows_pivot(request: Request, visao: str = "ranking", sdr_id: int | None = None, fase: str | None = None,
                  q: str | None = None, mais15: int = 0, dias: int | None = None, db: Session = Depends(get_db)):
    if dias is None:
        dias = 365  # avanços: último ano por padrão (o histórico completo passa de 13 mil linhas)
    if visao not in VISOES:
        visao = "ranking"
    if visao == "ranking":
        return _ranking(request, sdr_id, fase, q, mais15, db)
    sdrs = db.scalars(select(SDR).order_by(SDR.nome)).all()
    ctx = {"visao": visao, "limite": LIMITE, "sdrs": sdrs, "f": {"sdr_id": sdr_id, "q": q or "", "dias": dias}, "page": "follows"}
    if visao == "avancos":
        grupos, total = pivot_avancos(db, sdr_id, q, dias)
        ctx.update(grupos=grupos, total_av=total)
    else:
        grupos, total = pivot_follows(db, visao, sdr_id, q)
        ctx.update(grupos=grupos, total=total)
    return templates.TemplateResponse(request, "follows_pivot.html", ctx)
