"""Carga inicial a partir do Controle SDrs.xlsx (primeira inicialização).

O arquivo contém credenciais: fica em DATA_DIR/seed/ (volume), nunca no Git nem na imagem.
Nada que venha da aba Credentials é logado.
"""
import os
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import DATA_DIR
from app.models.schema import SDR, Agenda, Confirmacao, DadoRelatorio, EmailEnviado, ExecutionLog
from app.services.credenciais import aplicar
from app.services.util import norm, parse_date, to_int

# De/Para histórico do EMAIL_MAPPING do app.js (conta Gmail -> nome do SDR); não é segredo
NOMES_POR_EMAIL = {
    "sdr7.ativa@gmail.com": "Esthela", "sdr0.ativaai@gmail.com": "Andrade", "sdr6.ativa@gmail.com": "Leo",
    "sdr.ativaai@gmail.com": "Deniel", "sdr3.1.ativa@gmail.com": "Bianca", "sdr2.ativaai@gmail.com": "Domingues",
    "sdr1.ativaai@gmail.com": "Julia", "sdr9.ativa@gmail.com": "Tura", "sdr4ativa@gmail.com": "Felipe",
}

ALIAS = {
    "sdr": ("e mail do criador", "nome do criador", "criador", "sdr", "emails", "responsavel", "nome do sdr"),
    "nome_criador": ("nome do criador", "criador"),
    "data_atual": ("data atual",),
    "cliente": ("cliente", "nome do cliente", "box", "nome"),
    "fase": ("fase atual", "fase", "etapa", "stage"),
    "pipeline": ("pipeline",),
    "total_emails": ("total de e mails", "total de e mails enviados", "total emails"),
    "emails_enviados": ("e mails enviados", "emails enviados"),
    "emails_recebidos": ("e mails recebidos", "emails recebidos"),
    "primeiro_email": ("primeiro e mail", "data do primeiro e mail"),
    "ultimo_email": ("ultimo e mail recebido", "data do ultimo e mail recebido", "data do ultimo e mail"),
    "follow_up": ("follow up", "data de follow up"),
    "dias_atraso": ("dias atraso", "dias de atraso", "dias em atraso", "atraso"),
    "notas": ("notas", "observacoes", "notes"),
    "data": ("data", "data registro"),
    "quantidade": ("enviados", "emails enviados", "quantidade", "total", "qtd"),
    "remetente": ("remetente", "de", "from"),
    "email": ("user email", "email"),
    "refresh_token": ("refresh token",),
    "client_id": ("client id",),
    "client_secret": ("client secret",),
}


def _rows(ws):
    """Linhas como dict por cabeçalho normalizado; para após 100 linhas vazias seguidas."""
    header, blanks = None, 0
    for vals in ws.iter_rows(values_only=True, max_row=300_000):
        if not any(v not in (None, "") for v in vals):
            blanks += 1
            if blanks > 100:
                return
            continue
        blanks = 0
        if header is None:
            if sum(v not in (None, "") for v in vals) >= 2:
                header = [norm(v) for v in vals]
            continue
        yield {h: v for h, v in zip(header, vals) if h}


def _get(row: dict, key: str):
    for a in ALIAS[key]:
        v = row.get(a)
        if v not in (None, ""):
            return v
    for a in ALIAS[key]:  # cabeçalhos longos/truncados: "quantidade de emails d..."
        if len(a) < 6:
            continue
        for k, v in row.items():
            if k.startswith(a + " ") and v not in (None, ""):
                return v
    return None


def _s(v, n=None):
    s = str(v).strip() if v not in (None, "") else None
    return s[:n] if s and n else s


class _Resolver:
    def __init__(self, db: Session):
        self.db = db
        self.by_key: dict[str, SDR] = {}
        self.vistos: set[int] = set()
        for s in db.scalars(select(SDR)):
            self._index(s)

    def _index(self, s: SDR):
        for k in (s.email, s.nome, s.email.split("@")[0], NOMES_POR_EMAIL.get(s.email)):
            if k:
                self.by_key[norm(k)] = s

    def get(self, ref, criar=True, nome=None) -> SDR | None:
        """Acha o SDR por e-mail ou nome. Inexistente (ex-SDR no histórico) vira cadastro INATIVO,
        para não entrar nas coletas, mas o histórico fica reatribuível."""
        ref = _s(ref)
        if not ref:
            return None
        s = self.by_key.get(norm(ref)) or self.by_key.get(norm(ref.split("@")[0]))
        if s:
            nome = _s(nome, 100)
            if nome and s.id not in self.vistos and s.nome in (NOMES_POR_EMAIL.get(s.email), s.email.split("@")[0]):
                s.nome = nome  # o Excel guarda o nome atual de quem usa a conta
                self._index(s)
            self.vistos.add(s.id)
            return s
        if not criar:
            return None
        gmail = "@" in ref and not ref.lower().endswith("@ativa.ai")
        email = ref.lower() if gmail else f"{norm(ref.split('@')[0]).replace(' ', '.') or 'sdr'}@pendente.local"
        s = SDR(nome=(_s(nome, 100) or ref.split("@")[0])[:100], email=email[:150], ativo=False)
        self.db.add(s)
        self.db.flush()
        self._index(s)
        self.vistos.add(s.id)
        return s


def _credentials(db: Session, ws, res: _Resolver) -> int:
    n = 0
    for r in _rows(ws):
        email = (_s(_get(r, "email")) or "").lower()
        if not email:
            continue
        s = res.by_key.get(norm(email))
        if not s:
            s = SDR(nome=NOMES_POR_EMAIL.get(email, email.split("@")[0]), email=email)
            db.add(s)
            db.flush()
            res._index(s)
        aplicar(db, s, {k: _s(_get(r, k)) for k in ("refresh_token", "client_id", "client_secret")}, "Seed do Controle SDrs.xlsx")
        n += 1
    return n


def _dados(db: Session, ws, res: _Resolver) -> int:
    n = 0
    for r in _rows(ws):
        cliente = _s(_get(r, "cliente"), 150)
        if not cliente:
            continue
        fu = parse_date(_get(r, "follow_up"))
        ult = parse_date(_get(r, "ultimo_email"))
        ref = parse_date(_get(r, "data_atual")) or datetime.now()  # atraso medido na data do snapshot
        atraso = _get(r, "dias_atraso")
        atraso = to_int(atraso) if atraso is not None else (max((ref - fu).days, 0) if fu else 0)
        sdr = res.get(_get(r, "sdr"), nome=_get(r, "nome_criador"))
        db.add(DadoRelatorio(
            sdr_id=sdr.id if sdr else None, cliente=cliente, fase=_s(_get(r, "fase"), 50),
            pipeline=_s(_get(r, "pipeline"), 50), total_emails=to_int(_get(r, "total_emails")),
            emails_enviados=to_int(_get(r, "emails_enviados")), emails_recebidos=to_int(_get(r, "emails_recebidos")),
            primeiro_email=parse_date(_get(r, "primeiro_email")), ultimo_email_recebido=ult, follow_up=fu,
            dias_atraso=max(atraso or 0, 0), dias_desde_ultimo_email=max((ref - ult).days, 0) if ult else 0,
            notas=_s(_get(r, "notas")), origem="SEED"))
        n += 1
    return n


def _agenda(db: Session, ws, res: _Resolver, vistos: set) -> int:
    """Abas de reunião têm layouts diferentes (algumas sem cabeçalho): lê pelo conteúdo da linha."""
    n = 0
    for vals in ws.iter_rows(values_only=True, max_row=100_000):
        cells = [v for v in vals if v not in (None, "")]
        if len(cells) < 3 or not isinstance(cells[0], str):
            continue
        datas = [parse_date(v) for v in cells if isinstance(v, datetime) or (isinstance(v, str) and v[:2].isdigit() and ("/" in v or "-" in v))]
        datas = [d for d in datas if d and d.year > 2000]
        strs = [str(c).strip() for c in cells if isinstance(c, str)]
        email = next((x for x in strs[1:] if "@" in x and " " not in x), None)
        titulo = max((x for x in strs[1:] if x != email and parse_date(x) is None), key=len, default=None)
        if not datas or not titulo or len(titulo) < 4:
            continue
        sdr = res.get(strs[0])
        k = (sdr.id if sdr else None, datas[0], titulo[:255])
        if k in vistos:
            continue
        vistos.add(k)
        db.add(Agenda(sdr_id=k[0], email_convidado=(email or "")[:150] or None, titulo_reuniao=k[2], data_inicio=datas[0],
                      data_fim=datas[1] if len(datas) > 1 else None, tipo_periodo="SEMANAL"))
        n += 1
    return n


def _enviados(ws, res: _Resolver, acc: dict) -> None:
    for r in _rows(ws):
        d, sdr = parse_date(_get(r, "data")), res.get(_get(r, "sdr"))
        if d and sdr:
            acc[(sdr.id, d.date())] = to_int(_get(r, "quantidade"))


def _confirmacoes(db: Session, ws, res: _Resolver) -> int:
    n = 0
    for r in _rows(ws):
        rem = _s(_get(r, "remetente"), 150)
        if not rem:
            continue
        sdr = res.get(rem, criar=False)
        q = _get(r, "quantidade")
        db.add(Confirmacao(sdr_id=sdr.id if sdr else None, remetente=rem, quantidade=to_int(q, 1) if q is not None else 1,
                           data_registro=parse_date(_get(r, "data"))))
        n += 1
    return n


def seed_path() -> Path | None:
    for p in (os.getenv("SEED_XLSX_PATH"), DATA_DIR / "seed" / "Controle SDrs.xlsx", Path("seed") / "Controle SDrs.xlsx"):
        if p and Path(p).is_file():
            return Path(p)
    return None


def import_seed(db: Session) -> dict[str, int] | None:
    """Roda uma vez: só com a tabela sdrs vazia e o xlsx presente. Retorna contagens por destino."""
    path = seed_path()
    if not path or db.scalar(select(SDR.id).limit(1)):
        return None
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    sheets = {norm(n): wb[n] for n in wb.sheetnames}
    res, out, vistos = _Resolver(db), {}, set()

    def pick(*names):
        return [ws for k, ws in sheets.items() if k in names]

    for ws in pick("credentials"):
        out["credentials"] = _credentials(db, ws, res)
    # 'follows' e 'Avanços' são históricos de movimentação do mesmo Streak: importá-los junto duplicaria cada box.
    for ws in pick("dados do relatoro", "dados do relatorio"):
        out["dados_relatorio"] = _dados(db, ws, res)
    out["agenda"] = sum(_agenda(db, ws, res, vistos) for k, ws in sheets.items()
                        if k.startswith("reunio") and "contagem" not in k and "teste" not in k)
    acc: dict = {}
    for ws in pick("consolidadoenviados", "enviados"):  # histórico primeiro; 'enviados' prevalece no mesmo dia
        _enviados(ws, res, acc)
    db.add_all(EmailEnviado(sdr_id=sd, data_registro=d, quantidade=q) for (sd, d), q in acc.items())
    out["enviados"] = len(acc)
    for ws in pick("confirmacoes"):
        out["confirmacoes"] = _confirmacoes(db, ws, res)
    wb.close()
    db.add(ExecutionLog(modulo="SEED", status="SUCCESS", registros_processados=sum(out.values()),
                        detalhes=f"{path.name}: " + ", ".join(f"{k}={v}" for k, v in out.items())))
    db.commit()
    return out


def _n(v) -> int:
    return to_int(v) if isinstance(v, (int, float)) else 0


def import_extras(db: Session) -> dict[str, int] | None:
    """Tabelas que alimentam as tabelas dinâmicas do Excel: Contagem de Reuniões, respostas e Avanços.
    Roda uma vez (tabelas vazias) quando o xlsx está disponível."""
    from sqlalchemy import func

    from app.models.schema import Avanco, ContagemReuniao, Resposta

    path = seed_path()
    if not path or db.scalar(select(func.count()).select_from(ContagemReuniao)):
        return None
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    sheets = {norm(n): wb[n] for n in wb.sheetnames}
    res, out = _Resolver(db), {}
    ws = sheets.get("contagem de reunioes")
    n = 0
    if ws is not None:
        for v in ws.iter_rows(min_row=2, values_only=True, max_row=20_000):
            d, nome = parse_date(v[9]) if len(v) > 9 else None, _s(v[0])
            nums = [_n(x) for x in v[1:9]]
            if not nome or not d or not any(nums):
                continue  # linhas futuras/em branco do calendário
            s = res.get(nome)
            db.add(ContagemReuniao(sdr_id=s.id if s else None, data=d.date(), diretas=nums[0], follow_up=nums[1], qualificacao=nums[2],
                                   proposta=nums[3], venda=nums[4], ns_proposta=nums[5], ns_qualificacao=nums[6], com_decisor=nums[7]))
            n += 1
    out["contagem_reunioes"] = n
    ws, n = sheets.get("respostas"), 0
    if ws is not None:
        for v in ws.iter_rows(min_row=2, values_only=True, max_row=20_000):
            d, nome = parse_date(v[8]) if len(v) > 8 else None, _s(v[0])
            if not nome or not d or not any(_n(x) for x in v[2:5]):
                continue
            s = res.get(nome)
            db.add(Resposta(sdr_id=s.id if s else None, prospeccao=_s(v[1], 30), data=d.date(), enviado=_n(v[2]), aberto=_n(v[3]), respondido=_n(v[4])))
            n += 1
    out["respostas"] = n
    ws, n = next((w for k, w in sheets.items() if k.startswith("avanco")), None), 0
    if ws is not None:
        for v in ws.iter_rows(values_only=True, max_row=50_000):
            nome, fase = _s(v[0]) if len(v) > 0 else None, _s(v[1]) if len(v) > 1 else None
            if not nome or not fase or len(v) < 14:
                continue
            s = res.get(nome)
            d = parse_date(v[13])
            db.add(Avanco(sdr_id=s.id if s else None, fase=fase[:60], canal=_s(v[2], 40), email_contato=_s(v[3], 150), contato=_s(v[7], 150),
                          empresa=_s(v[8], 150), porte=_s(v[9], 30), segmento=_s(v[10], 100), cargo=_s(v[11], 100), estado=_s(v[12], 60),
                          data=d.date() if d else None))
            n += 1
    out["avancos"] = n
    wb.close()
    db.add(ExecutionLog(modulo="SEED", status="SUCCESS", registros_processados=sum(out.values()),
                        detalhes="Tabelas dinâmicas do Excel: " + ", ".join(f"{k}={v}" for k, v in out.items())))
    db.commit()
    return out
