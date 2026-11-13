"""Credenciais versionadas dos SDRs e configurações do sistema (painel > variáveis de ambiente)."""
import os
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.schema import SDR, Config, CredencialVersao

CAMPOS = ("streak_api_key", "follow_up_key", "client_id", "client_secret", "refresh_token")
SEGREDOS = ("streak_api_key", "client_secret", "refresh_token")

# chave -> (rótulo, é segredo, ajuda)
CONFIGS = {
    "SALESOPS_CLIENT_ID": ("SalesOps · Client ID", False, "OAuth da conta salesops.ativa@gmail.com"),
    "SALESOPS_CLIENT_SECRET": ("SalesOps · Client Secret", True, ""),
    "SALESOPS_REFRESH_TOKEN": ("SalesOps · Refresh Token", True, "Escopo gmail.readonly"),
    "SYNC_SINCE_DAYS": ("Janela de confirmações (dias)", False, "Padrão 7"),
    "SYNC_INTERVAL_MIN": ("Sincronizar a cada (min)", False, "0 = só manual"),
}


def cfg(chave: str, default: str = "") -> str:
    with SessionLocal() as db:
        row = db.get(Config, chave)
    if row and row.valor:
        return row.valor
    return os.getenv(chave, default)


def set_cfg(db: Session, chave: str, valor: str | None):
    row = db.get(Config, chave)
    if row:
        row.valor, row.atualizado_em = valor, datetime.now()
    else:
        db.add(Config(chave=chave, valor=valor))


def versao_atual(db: Session, sdr_id: int) -> int:
    return db.scalar(select(func.coalesce(func.max(CredencialVersao.versao), 0)).where(CredencialVersao.sdr_id == sdr_id))


def aplicar(db: Session, sdr: SDR, novos: dict, motivo: str = "", exato: bool = False) -> int | None:
    """Grava uma nova versão se algo mudou. Vazio mantém o valor atual, salvo exato=True (restaurar).
    Retorna o número da nova versão, ou None se nada mudou."""
    atual = {c: getattr(sdr, c) for c in CAMPOS}
    final = dict(atual)
    for c in CAMPOS:
        v = novos.get(c)
        v = v.strip() if isinstance(v, str) else v
        if exato:
            final[c] = v or None
        elif v:
            final[c] = v
    if final == atual and versao_atual(db, sdr.id):
        return None
    for c, v in final.items():
        setattr(sdr, c, v)
    n = versao_atual(db, sdr.id) + 1
    db.execute(update(CredencialVersao).where(CredencialVersao.sdr_id == sdr.id).values(ativa=False))
    db.add(CredencialVersao(sdr_id=sdr.id, versao=n, motivo=(motivo or "")[:200] or None, ativa=True, **final))
    return n


def importar_planilha_credenciais(db: Session, path, motivo: str) -> tuple[int, int]:
    """Lê só a aba Credentials do xlsx (user_email, refresh_token, client_id, client_secret). -> (criados, atualizados)."""
    import openpyxl

    from app.services.seed_xlsx import NOMES_POR_EMAIL, _get, _rows, _s
    from app.services.util import norm

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        ws = next((wb[n] for n in wb.sheetnames if norm(n) == "credentials"), None)
        if ws is None:
            raise ValueError("aba 'Credentials' não encontrada no arquivo")
        criados = atualizados = 0
        for r in _rows(ws):
            email = (_s(_get(r, "email")) or "").lower()
            if not email:
                continue
            sdr = db.scalar(select(SDR).where(SDR.email == email))
            novo = sdr is None
            if novo:
                sdr = SDR(nome=NOMES_POR_EMAIL.get(email, email.split("@")[0]), email=email)
                db.add(sdr)
                db.flush()
            vals = {k: _s(_get(r, k)) for k in ("refresh_token", "client_id", "client_secret")}
            if aplicar(db, sdr, vals, motivo):
                criados += novo
                atualizados += not novo
        db.commit()
        return criados, atualizados
    finally:
        wb.close()
