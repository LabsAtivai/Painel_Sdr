"""Rotina diária: um botão coleta Gmail + Agenda + confirmações e a tela já mostra o relatório do grupo comercial."""
import threading
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.schema import SDR, Agenda, EmailEnviado, ExecutionLog
from app.services import sync_service
from app.services.confirmacao_match import Confirmacoes
from app.templating import templates

router = APIRouter()

MODULOS_ROTINA = ("GMAIL", "AGENDA", "CONFIRMACOES")
ENVIADOS = {"ontem": "Ontem", "hoje": "Hoje", "3d": "Há 3 dias"}
REUNIOES = {"hoje": "Hoje", "amanha": "Amanhã"}


def _d(d: date) -> datetime:
    return datetime.combine(d, datetime.min.time())


def dia_seguinte(hoje: date) -> date:
    """Próximo dia útil (sexta e fim de semana apontam para segunda)."""
    d = hoje + timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def dia_enviados(hoje: date, modo: str) -> date:
    return {"ontem": hoje - timedelta(days=1), "hoje": hoje, "3d": hoje - timedelta(days=3)}[modo]


def dia_reunioes(hoje: date, modo: str) -> date:
    return hoje if modo == "hoje" else dia_seguinte(hoje)


def rotulo(nome: str | None) -> str:
    nome = (nome or "").strip()
    return nome if "@" in nome else f"{nome}@ativa.ai"


def _estado_coleta(db: Session, hoje: date) -> list[dict]:
    """Módulos da rotina que não rodaram hoje ou falharam na última execução."""
    problemas = []
    for modulo in MODULOS_ROTINA:
        log = db.scalars(select(ExecutionLog).where(ExecutionLog.modulo == modulo).order_by(ExecutionLog.id.desc()).limit(1)).first()
        if log is None:
            problemas.append({"modulo": modulo, "texto": "ainda não rodou"})
        elif log.status != "SUCCESS":
            problemas.append({"modulo": modulo, "texto": f"falhou em {log.data_execucao:%d/%m %H:%M}"})
        elif log.data_execucao.date() != hoje:
            problemas.append({"modulo": modulo, "texto": f"última coleta em {log.data_execucao:%d/%m %H:%M}"})
    return problemas


@router.get("/rotina")
def rotina(request: Request, env: str | None = None, reu: str = "hoje", db: Session = Depends(get_db)):
    hoje = date.today()
    if env not in ENVIADOS:
        env = "3d" if hoje.weekday() == 0 else "ontem"  # segunda: o último dia útil foi há 3 dias
    if reu not in REUNIOES:
        reu = "hoje"
    d_env, d_reu = dia_enviados(hoje, env), dia_reunioes(hoje, reu)

    # ── e-mails enviados no dia escolhido ──
    sdrs = db.scalars(select(SDR).where(SDR.ativo.is_(True)).order_by(SDR.nome)).all()
    qtd = {sid: q for sid, q in db.execute(select(EmailEnviado.sdr_id, EmailEnviado.quantidade).where(EmailEnviado.data_registro == d_env))}
    enviados = [{"sdr": rotulo(s.nome), "qtd": qtd.get(s.id)} for s in sdrs]
    total_env = sum(e["qtd"] or 0 for e in enviados)
    maior = max((e["qtd"] or 0 for e in enviados), default=0) or 1
    for e in enviados:
        e["pct"] = round((e["qtd"] or 0) * 100 / maior)

    # ── reuniões do dia escolhido, agrupadas por SDR (propostas primeiro) ──
    rows = db.execute(
        select(Agenda, SDR.nome).join(SDR, SDR.id == Agenda.sdr_id, isouter=True)
        .where(Agenda.data_inicio >= _d(d_reu), Agenda.data_inicio < _d(d_reu + timedelta(days=1)))
        .order_by(Agenda.data_inicio)).all()
    conf = Confirmacoes(db, _d(d_reu), _d(d_reu + timedelta(days=1)))
    grupos: dict[str, dict] = {}
    for a, nome in rows:
        prop = "proposta" in (a.titulo_reuniao or "").lower()
        st = conf.status(a.titulo_reuniao, a.email_convidado, a.data_inicio)
        g = grupos.setdefault(rotulo(nome or "sem SDR"), {"itens": [], "total": 0, "propostas": 0, "sim": 0, "nao": 0})
        g["itens"].append({"titulo": a.titulo_reuniao or "(sem título)", "proposta": prop, "hora": a.data_inicio, "conf": st})
        g["total"] += 1
        g["propostas"] += prop
        g["sim"] += st is True
        g["nao"] += st is False
    for g in grupos.values():
        g["itens"].sort(key=lambda i: (not i["proposta"], i["hora"]))
        g["quali"] = g["total"] - g["propostas"]
    ordem = sorted(grupos.items())
    tot = {k: sum(g[k] for _, g in ordem) for k in ("total", "propostas", "quali", "sim", "nao")}

    return templates.TemplateResponse(request, "rotina.html", {
        "env": env, "reu": reu, "enviados_opcoes": ENVIADOS, "reunioes_opcoes": REUNIOES,
        "d_env": d_env, "d_reu": d_reu, "hoje": hoje,
        "enviados": enviados, "total_env": total_env, "sem_dado": [e["sdr"] for e in enviados if e["qtd"] is None],
        "grupos": ordem, "tot": tot, "sem_cobertura": any(i["conf"] is None for _, g in ordem for i in g["itens"]),
        "coleta": _estado_coleta(db, hoje), "rodando": sync_service.is_running(), "page": "rotina",
    })


@router.post("/rotina/atualizar")
def atualizar(env: str = Form(""), reu: str = Form("")):
    """Dispara a coleta em segundo plano e volta para a tela (que recarrega sozinha ao terminar)."""
    if not sync_service.is_running():
        threading.Thread(target=sync_service.run_sync, kwargs={"modulos": MODULOS_ROTINA, "trigger": "rotina"}, daemon=True).start()
    qs = "&".join(f"{k}={v}" for k, v in (("env", env), ("reu", reu)) if v)
    return RedirectResponse(f"/rotina{'?' + qs if qs else ''}", status_code=303)
