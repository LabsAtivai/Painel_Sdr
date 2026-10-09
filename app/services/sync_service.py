"""Orquestra as coletas (Streak, e-mails enviados, agenda, confirmações) e grava no SQLite."""
import threading
import time
from datetime import date, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.schema import SDR, Agenda, Confirmacao, ConfirmacaoEmail, DadoRelatorio, EmailEnviado, ExecutionLog
from app.services import gmail_service, streak_service
from app.services.credenciais import cfg
from app.services.util import norm

_lock = threading.Lock()
MODULOS = ("STREAK", "GMAIL", "AGENDA", "CONFIRMACOES")
KEYWORD = ("reuniao entre", "reunioes entre", "proposta entre", "propostas entre")


def is_running() -> bool:
    return _lock.locked()


class Result:
    def __init__(self):
        self.n, self.ok, self.fail, self.lines = 0, 0, 0, []

    def good(self, msg: str, n: int = 0):
        self.ok += 1
        self.n += n
        self.lines.append(msg)

    def bad(self, msg: str):
        self.fail += 1
        self.lines.append(msg)

    @property
    def status(self) -> str:
        return "ERROR" if self.fail and not self.ok else "SUCCESS"


def _active(db: Session):
    return db.scalars(select(SDR).where(SDR.ativo.is_(True)).order_by(SDR.nome)).all()


def _with_google(db: Session, r: Result, fn):
    """Roda fn(sdr, google) para cada SDR ativo com OAuth; registra falha por SDR."""
    sdrs = [(s, gmail_service.sdr_creds(s)) for s in _active(db)]
    sdrs = [(s, c) for s, c in sdrs if c]
    if not sdrs:
        r.bad("Nenhum SDR ativo com Client ID/Secret/Refresh Token (aba SDRs)")
    for s, c in sdrs:
        try:
            with gmail_service.Google(c) as g:
                r.good(f"{s.nome}: {fn(s, g)}", 1)
        except Exception as e:
            db.rollback()
            r.bad(f"{s.nome}: {type(e).__name__}: {e}")


def sync_streak(db: Session, r: Result):
    sdrs = [s for s in _active(db) if s.streak_api_key]
    if not sdrs:
        r.bad("Nenhum SDR ativo com API Key do Streak (aba SDRs)")
    for s in sdrs:
        try:
            boxes = streak_service.fetch_boxes(s.streak_api_key, s.follow_up_key)
        except Exception as e:
            r.bad(f"{s.nome}: {type(e).__name__}: {e}")
            continue
        # dado ao vivo substitui o histórico do Excel e o snapshot anterior deste SDR
        db.execute(delete(DadoRelatorio).where(DadoRelatorio.sdr_id == s.id))
        db.add_all(DadoRelatorio(sdr_id=s.id, origem="STREAK", **b) for b in boxes)
        db.commit()
        r.good(f"{s.nome}: {len(boxes)} boxes", len(boxes))


def sync_emails(db: Session, r: Result):
    def run(s: SDR, g):
        for back in range(4):  # hoje + 3 dias anteriores
            day = date.today() - timedelta(days=back)
            total = g.count_sent(day)
            row = db.scalar(select(EmailEnviado).where(EmailEnviado.sdr_id == s.id, EmailEnviado.data_registro == day))
            if row:
                row.quantidade = total
            else:
                db.add(EmailEnviado(sdr_id=s.id, data_registro=day, quantidade=total))
        db.commit()
        return "ok"

    _with_google(db, r, run)


def _periodo(d: date) -> str:
    hoje = date.today()
    prox_seg = hoje + timedelta(days=7 - hoje.weekday())
    return "HOJE" if d == hoje else "AMANHA" if d == hoje + timedelta(days=1) else "SEGUNDA" if d == prox_seg else "SEMANAL"


def sync_agenda(db: Session, r: Result):
    today = datetime.combine(date.today(), datetime.min.time())
    start, end = today - timedelta(days=today.weekday()), today + timedelta(days=8)

    def run(s: SDR, g):
        events = g.calendar_events(start, end)
        db.execute(delete(Agenda).where(Agenda.sdr_id == s.id, Agenda.data_inicio >= start))
        n = 0
        for ev in events:
            titulo = ev.get("summary") or ""
            if not any(k in norm(titulo) for k in KEYWORD):
                continue
            try:
                def _dt(x):
                    raw = x.get("dateTime") or x.get("date")
                    return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone().replace(tzinfo=None)
                ini, fim = _dt(ev["start"]), _dt(ev["end"])
            except Exception:
                continue
            guest = next((a.get("email") for a in ev.get("attendees", []) if a.get("email", "").lower() != s.email.lower()), None)
            db.add(Agenda(sdr_id=s.id, email_convidado=guest, titulo_reuniao=titulo[:255], data_inicio=ini, data_fim=fim,
                          descricao=ev.get("description"), tipo_periodo=_periodo(ini.date())))
            n += 1
        db.commit()
        return f"{n} evento(s)"

    _with_google(db, r, run)


def sync_confirmacoes(db: Session, r: Result):
    creds = gmail_service.salesops_creds()
    if not creds:
        r.bad("SALESOPS_CLIENT_ID / SECRET / REFRESH_TOKEN não configurados")
        return
    from email.utils import parseaddr

    days = int(cfg("SYNC_SINCE_DAYS", "7") or 7)
    with gmail_service.Google(creds) as g:
        msgs = g.confirmation_messages(days)
    by_email = {s.email.lower(): s for s in db.scalars(select(SDR))}
    novos = 0
    for m in msgs:
        if db.scalar(select(ConfirmacaoEmail.id).where(ConfirmacaoEmail.message_id == m["id"])):
            continue
        addr = parseaddr(m["from"])[1].lower()
        s = by_email.get(addr)
        db.add(ConfirmacaoEmail(message_id=m["id"], sdr_id=s.id if s else None, remetente=addr[:150], assunto=m["subject"][:300],
                                texto=norm(m["subject"] + " " + m["text"]) + " " + (m["text"] + m["subject"]).lower(), data=m["date"]))
        novos += 1
    db.flush()
    # contagens por remetente/dia (tabela 'confirmacoes' do spec) recompostas a partir dos e-mails da janela
    inicio = datetime.combine(date.today() - timedelta(days=days), datetime.min.time())
    db.execute(delete(Confirmacao).where(Confirmacao.data_registro >= inicio))
    cont: dict = {}
    for e in db.scalars(select(ConfirmacaoEmail).where(ConfirmacaoEmail.data >= inicio)):
        k = (e.sdr_id, e.remetente, e.data.date())
        cont[k] = cont.get(k, 0) + 1
    for (sid, rem, day), q in cont.items():
        db.add(Confirmacao(sdr_id=sid, remetente=rem, quantidade=q, data_registro=datetime.combine(day, datetime.min.time())))
    db.commit()
    r.good(f"{len(msgs)} e-mail(s) na janela de {days} dia(s), {novos} novo(s)", novos)


JOBS = {"STREAK": sync_streak, "GMAIL": sync_emails, "AGENDA": sync_agenda, "CONFIRMACOES": sync_confirmacoes}


def run_sync(modulos: tuple[str, ...] = MODULOS, trigger: str = "manual") -> bool:
    """Roda as coletas em sequência, um log por módulo. False se já houver sync em andamento."""
    if not _lock.acquire(blocking=False):
        return False
    try:
        with SessionLocal() as db:
            for m in modulos:
                r = Result()
                try:
                    JOBS[m](db, r)
                except Exception as e:
                    db.rollback()
                    r.bad(f"{type(e).__name__}: {e}")
                db.add(ExecutionLog(modulo=m, status=r.status, registros_processados=r.n,
                                    detalhes="\n".join([f"gatilho={trigger}", *r.lines])))
                db.commit()
        return True
    finally:
        _lock.release()


def start_scheduler() -> None:
    """Checa a cada minuto o intervalo configurado (painel ou SYNC_INTERVAL_MIN) e dispara a sincronização."""
    def loop():
        ultimo = datetime.now()
        while True:
            time.sleep(60)
            try:
                minutos = int(cfg("SYNC_INTERVAL_MIN", "0") or 0)
            except ValueError:
                minutos = 0
            if minutos > 0 and (datetime.now() - ultimo).total_seconds() >= minutos * 60:
                ultimo = datetime.now()
                run_sync(trigger="agendado")

    threading.Thread(target=loop, daemon=True, name="sync-scheduler").start()
