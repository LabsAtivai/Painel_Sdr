from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _now() -> datetime:
    return datetime.now()


class SDR(Base):
    __tablename__ = "sdrs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nome: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(150), unique=True)
    streak_api_key: Mapped[str | None] = mapped_column(String(255))
    follow_up_key: Mapped[str | None] = mapped_column(String(50))
    refresh_token: Mapped[str | None] = mapped_column(Text)
    client_id: Mapped[str | None] = mapped_column(Text)
    client_secret: Mapped[str | None] = mapped_column(Text)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=_now)


class DadoRelatorio(Base):
    """Base do Streak (substitui 'Dados do Relatóro', 'follows' e 'Avanços')."""

    __tablename__ = "dados_relatorio"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sdr_id: Mapped[int | None] = mapped_column(ForeignKey("sdrs.id"), index=True)
    cliente: Mapped[str | None] = mapped_column(String(150))
    fase: Mapped[str | None] = mapped_column(String(50), index=True)
    pipeline: Mapped[str | None] = mapped_column(String(50))
    total_emails: Mapped[int] = mapped_column(Integer, default=0)
    emails_enviados: Mapped[int] = mapped_column(Integer, default=0)
    emails_recebidos: Mapped[int] = mapped_column(Integer, default=0)
    primeiro_email: Mapped[datetime | None] = mapped_column(DateTime)
    ultimo_email_recebido: Mapped[datetime | None] = mapped_column(DateTime)
    follow_up: Mapped[datetime | None] = mapped_column(DateTime)
    dias_atraso: Mapped[int] = mapped_column(Integer, default=0)
    dias_desde_ultimo_email: Mapped[int] = mapped_column(Integer, default=0)
    notas: Mapped[str | None] = mapped_column(Text)
    data_atualizacao: Mapped[datetime] = mapped_column(DateTime, default=_now)
    origem: Mapped[str] = mapped_column(String(10), default="STREAK", index=True)  # STREAK | SEED


class Agenda(Base):
    __tablename__ = "reunioes_agenda"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sdr_id: Mapped[int | None] = mapped_column(ForeignKey("sdrs.id"), index=True)
    email_convidado: Mapped[str | None] = mapped_column(String(150))
    titulo_reuniao: Mapped[str | None] = mapped_column(String(255))
    data_inicio: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    data_fim: Mapped[datetime | None] = mapped_column(DateTime)
    descricao: Mapped[str | None] = mapped_column(Text)
    tipo_periodo: Mapped[str | None] = mapped_column(String(20))  # HOJE, AMANHA, SEGUNDA, SEMANAL
    data_criacao: Mapped[datetime] = mapped_column(DateTime, default=_now)


class EmailEnviado(Base):
    __tablename__ = "emails_enviados"
    __table_args__ = (UniqueConstraint("sdr_id", "data_registro"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sdr_id: Mapped[int] = mapped_column(ForeignKey("sdrs.id"), index=True)
    data_registro: Mapped[date] = mapped_column(Date)
    quantidade: Mapped[int] = mapped_column(Integer, default=0)


class Confirmacao(Base):
    __tablename__ = "confirmacoes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sdr_id: Mapped[int | None] = mapped_column(ForeignKey("sdrs.id"), index=True)
    remetente: Mapped[str | None] = mapped_column(String(150))
    quantidade: Mapped[int] = mapped_column(Integer, default=0)
    data_registro: Mapped[datetime | None] = mapped_column(DateTime)


class ExecutionLog(Base):
    __tablename__ = "execution_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    data_execucao: Mapped[datetime] = mapped_column(DateTime, default=_now)
    modulo: Mapped[str | None] = mapped_column(String(50))  # STREAK, GMAIL, AGENDA, CONFIRMACOES, SEED
    status: Mapped[str] = mapped_column(String(20))  # SUCCESS, ERROR
    registros_processados: Mapped[int] = mapped_column(Integer, default=0)
    detalhes: Mapped[str | None] = mapped_column(Text)


class CredencialVersao(Base):
    """Histórico versionado das credenciais de cada SDR (snapshot completo a cada mudança)."""

    __tablename__ = "sdr_credenciais_versoes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sdr_id: Mapped[int] = mapped_column(ForeignKey("sdrs.id"), index=True)
    versao: Mapped[int] = mapped_column(Integer)
    streak_api_key: Mapped[str | None] = mapped_column(String(255))
    follow_up_key: Mapped[str | None] = mapped_column(String(50))
    refresh_token: Mapped[str | None] = mapped_column(Text)
    client_id: Mapped[str | None] = mapped_column(Text)
    client_secret: Mapped[str | None] = mapped_column(Text)
    motivo: Mapped[str | None] = mapped_column(String(200))
    ativa: Mapped[bool] = mapped_column(Boolean, default=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Config(Base):
    """Configurações do sistema editáveis no painel (sobrepõem variáveis de ambiente)."""

    __tablename__ = "configuracoes"

    chave: Mapped[str] = mapped_column(String(60), primary_key=True)
    valor: Mapped[str | None] = mapped_column(Text)
    atualizado_em: Mapped[datetime] = mapped_column(DateTime, default=_now)


class ContagemReuniao(Base):
    """Aba 'Contagem de Reuniões': funil diário por SDR (base das tabelas dinâmicas de conversão/no-show)."""

    __tablename__ = "contagem_reunioes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sdr_id: Mapped[int | None] = mapped_column(ForeignKey("sdrs.id"), index=True)
    data: Mapped[date] = mapped_column(Date, index=True)
    diretas: Mapped[int] = mapped_column(Integer, default=0)
    follow_up: Mapped[int] = mapped_column(Integer, default=0)
    qualificacao: Mapped[int] = mapped_column(Integer, default=0)
    proposta: Mapped[int] = mapped_column(Integer, default=0)
    venda: Mapped[int] = mapped_column(Integer, default=0)
    ns_proposta: Mapped[int] = mapped_column(Integer, default=0)  # no-show em proposta
    ns_qualificacao: Mapped[int] = mapped_column(Integer, default=0)  # no-show em qualificação
    com_decisor: Mapped[int] = mapped_column(Integer, default=0)


class Resposta(Base):
    """Aba 'respostas': envios, aberturas e respostas de prospecção por SDR/dia."""

    __tablename__ = "respostas_prospeccao"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sdr_id: Mapped[int | None] = mapped_column(ForeignKey("sdrs.id"), index=True)
    prospeccao: Mapped[str | None] = mapped_column(String(30))
    data: Mapped[date] = mapped_column(Date, index=True)
    enviado: Mapped[int] = mapped_column(Integer, default=0)
    aberto: Mapped[int] = mapped_column(Integer, default=0)
    respondido: Mapped[int] = mapped_column(Integer, default=0)


class Avanco(Base):
    """Aba 'Avanços': leads que avançaram (Avanço, Follow Futuro, Encaminhamento...)."""

    __tablename__ = "avancos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sdr_id: Mapped[int | None] = mapped_column(ForeignKey("sdrs.id"), index=True)
    fase: Mapped[str | None] = mapped_column(String(60), index=True)
    canal: Mapped[str | None] = mapped_column(String(40))
    email_contato: Mapped[str | None] = mapped_column(String(150))
    contato: Mapped[str | None] = mapped_column(String(150))
    empresa: Mapped[str | None] = mapped_column(String(150))
    porte: Mapped[str | None] = mapped_column(String(30))
    segmento: Mapped[str | None] = mapped_column(String(100))
    cargo: Mapped[str | None] = mapped_column(String(100))
    estado: Mapped[str | None] = mapped_column(String(60))
    data: Mapped[date | None] = mapped_column(Date, index=True)


class ConfirmacaoEmail(Base):
    """E-mail de confirmação recebido em salesops.ativa@gmail.com (base do Sim/Não de confirmação por reunião)."""

    __tablename__ = "confirmacoes_emails"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[str] = mapped_column(String(40), unique=True)
    sdr_id: Mapped[int | None] = mapped_column(ForeignKey("sdrs.id"), index=True)
    remetente: Mapped[str | None] = mapped_column(String(150))
    assunto: Mapped[str | None] = mapped_column(String(300))
    texto: Mapped[str | None] = mapped_column(Text)  # assunto + corpo normalizados (busca por título/convidado)
    data: Mapped[datetime] = mapped_column(DateTime, index=True)
