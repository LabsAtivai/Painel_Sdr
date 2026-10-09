"""Sim/Não de confirmação por reunião: existe e-mail recebido no SalesOps que cita a reunião?"""
import re
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.schema import ConfirmacaoEmail
from app.services.util import norm

_RUIDO = re.compile(r"\b(reuniao|reunioes|proposta|propostas|entre|ativa ai|ativaai|ativa|ai|e|com|de|da|do|x)\b")


def nucleo(titulo: str | None) -> str:
    """Título sem 'Reunião entre', 'Ativa.ai' e conectivos: sobra o nome da empresa/contato."""
    return re.sub(r"\s+", " ", _RUIDO.sub(" ", norm(titulo))).strip()


class Confirmacoes:
    def __init__(self, db: Session, ini: datetime, fim: datetime):
        self.cobertura = db.scalar(select(func.min(ConfirmacaoEmail.data)))
        self.emails = [(e.data, e.texto or "") for e in db.scalars(
            select(ConfirmacaoEmail).where(ConfirmacaoEmail.data >= ini - timedelta(days=45), ConfirmacaoEmail.data <= fim + timedelta(days=2)))]

    def status(self, titulo: str | None, convidado: str | None, quando: datetime) -> bool | None:
        """True/False; None quando não há e-mails coletados cobrindo a data (histórico anterior à coleta)."""
        if self.cobertura is None or quando < self.cobertura:
            return None
        t, core, guest = norm(titulo), nucleo(titulo), (convidado or "").lower()
        # fronteira de palavra: "ccm" não casa com "accmed"
        padrao = re.compile(r"(?<![a-z0-9])" + re.escape(core) + r"(?![a-z0-9])") if len(core) >= 3 else None
        for data, texto in self.emails:
            if not (quando - timedelta(days=45) <= data <= quando + timedelta(days=1)):
                continue
            if (t and t in texto) or (padrao and padrao.search(texto)) or (guest and guest in texto):
                return True
        return False
