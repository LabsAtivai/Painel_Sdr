# Specification Document (spec.md)

## 1. Contexto e Objetivo Geral

Substituir inteiramente a gestão baseada na planilha Google Sheets/Excel **Controle SDrs.xlsx** (ID `15XBHreEoGaWl8-ctys_0Jfj1OYLWd7Koe3iN40z6Z6M`) e nos scripts desacoplados em Node.js do ZIP `negativacaoSendgrid-main`.

A nova solução é um sistema unificado em **Python + SQLite** que automatiza a extração de dados do Streak CRM e do Gmail, gerencia a agenda de reuniões e a contagem de e-mails, e expõe um **Painel Web com Abas** e um **Menu de Gestão de SDRs** para admissões, demissões e reatribuição de histórico. Containerizado via Docker e publicado via Portainer integrado ao GitHub.

## 2. Mapeamento: Abas do Excel × Fontes no ZIP × Módulos do Sistema

| Aba no Controle SDrs.xlsx | Conteúdo / Função | Fonte de origem no ZIP | Destino no novo sistema |
|---|---|---|---|
| Dashboard | Métricas consolidadas, KPIs de SDRs, avanços, follows e e-mails | Consolidado de `app.js` e `follows.mjs` | Aba 1 – Dashboard Geral (queries dinâmicas) |
| Dados do Relatóro | Base bruta do Streak (15.900+ registros): clientes, fases, e-mails, atrasos | `sdrs.mjs`, `follows.mjs`, `app.js` (API Streak) | Tabela `dados_relatorio` |
| follows | Histórico de follow-ups e movimentação de pipeline (14.500+) | API Streak (`/api/v1/boxes`) | Tabela `dados_relatorio` |
| Avanços | Negócios que avançaram (Avanço, Follow Futuro, Encaminhamento) | API Streak | Tabela `dados_relatorio` |
| Follow +15 | Leads com mais de 15 dias sem follow-up | Cálculo `dias_atraso > 15` | Filtro dinâmico na Aba 2 |
| Reunioes do Dia Atual | Agendamentos do dia por SDR | `reunioesHoje.js` (Gmail/Calendar) | Tabela `reunioes_agenda` (HOJE) |
| Reunioes do Dia Seguinte | Agendamentos do próximo dia útil | `reunioesAmanha.js`, `reunioesSegunda.js` | Tabela `reunioes_agenda` (AMANHÃ/SEGUNDA) |
| ReunioeSemana / Reunioes 1 ano | Histórico semanal e anual | `reunioesSemanais.js` | Tabela `reunioes_agenda`, agregação semana/mês |
| enviados / consolidadoEnviados | E-mails enviados por SDR por data | `enviadossdrs.cjs` (Gmail API) | Tabela `emails_enviados` |
| Confirmacoes | Confirmações recebidas em salesops.ativa@gmail.com | Parsing de e-mails recebidos | Tabela `confirmacoes` |
| Credentials | Refresh tokens OAuth e client secrets dos SDRs | Aba Credentials, `service-account-credentials.json` | Colunas de `sdrs` e variáveis de ambiente |
| Contagem de Reuniões / respostas | Conversão, no-shows, taxas de resposta | Planilhas históricas de analytics | Aba 5 – Analytics & Conversão |

## 3. Requisitos Funcionais

### RF-01: Migração e Importação Inicial (Seed)
Na primeira inicialização, ler as abas do `Controle SDrs.xlsx` e persistir `Credentials`, `Dados do Relatóro`, `follows`, `Avanços`, `enviados`, reuniões e `Confirmacoes` nas tabelas correspondentes.

### RF-02: Coleta Automática do Streak CRM
API `https://api.streak.com/api/v1` com a API Key de cada SDR. Calcular:
- `dias_atraso`: dias entre hoje e a data de follow-up;
- `dias_desde_ultimo_email`: dias desde o último e-mail trocado;
- fase (Avanço, Follow Futuro, Encaminhamento, Qualificação, Proposta).

### RF-03: Coleta Automática do Gmail & SalesOps
- Contagem diária de disparos por SDR (Gmail API).
- Monitorar `salesops.ativa@gmail.com` para confirmações de reunião; identificar "reuniao entre" / "proposta entre" no assunto/corpo.
- Agenda de reuniões dos SDRs (Calendar API, mesmas credenciais OAuth).

### RF-04: Menu de Gestão Dinâmica de SDRs (De/Para)
Cadastro, edição, inativação e reatribuição. Por SDR: nome, e-mail corporativo, API Key do Streak, `FOLLOW_UP_KEY`, Client ID, Client Secret e Refresh Token do Gmail. Na demissão: inativar e reatribuir em lote o histórico ao novo SDR.

### RF-05: Interface Web em Abas
1. **Dashboard Geral:** KPIs, reuniões por SDR, volume de e-mails, alertas de atraso.
2. **Avanços & Follows (Streak):** listagem com filtros por SDR e fase; destaque para follows > 15 dias.
3. **Agenda de Reuniões:** Hoje, Amanhã, Segunda-feira e métricas semanais.
4. **Disparos & Métricas de E-mail:** e-mails enviados e confirmações recebidas.
5. **Analytics & Conversão:** conversão reunião→proposta, volume vs. resultado, desempenho histórico. No-show só quando existir fonte de dados.
6. **Gestão de SDRs (De/Para):** CRUD de SDRs e credenciais.
7. **Logs & Sincronização:** status das rotinas, botão "Executar Agora" e Data de Atualização.

## 4. Esquema do Banco (SQLite) — `data/database.db`

```sql
CREATE TABLE sdrs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome VARCHAR(100) NOT NULL,
    email VARCHAR(150) NOT NULL UNIQUE,
    streak_api_key VARCHAR(255),
    follow_up_key VARCHAR(50),
    refresh_token TEXT,
    client_id TEXT,
    client_secret TEXT,
    ativo BOOLEAN DEFAULT 1,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE dados_relatorio (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sdr_id INTEGER REFERENCES sdrs(id),
    cliente VARCHAR(150),
    fase VARCHAR(50),
    pipeline VARCHAR(50),
    total_emails INTEGER DEFAULT 0,
    emails_enviados INTEGER DEFAULT 0,
    emails_recebidos INTEGER DEFAULT 0,
    primeiro_email DATETIME,
    ultimo_email_recebido DATETIME,
    follow_up DATETIME,
    dias_atraso INTEGER DEFAULT 0,
    dias_desde_ultimo_email INTEGER DEFAULT 0,
    notas TEXT,
    data_atualizacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE reunioes_agenda (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sdr_id INTEGER REFERENCES sdrs(id),
    email_convidado VARCHAR(150),
    titulo_reuniao VARCHAR(255),
    data_inicio DATETIME,
    data_fim DATETIME,
    descricao TEXT,
    tipo_periodo VARCHAR(20),   -- HOJE, AMANHA, SEGUNDA, SEMANAL
    data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE emails_enviados (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sdr_id INTEGER REFERENCES sdrs(id),
    data_registro DATE,
    quantidade INTEGER DEFAULT 0
);

CREATE TABLE confirmacoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sdr_id INTEGER REFERENCES sdrs(id),
    remetente VARCHAR(150),
    quantidade INTEGER DEFAULT 0,
    data_registro DATETIME
);

CREATE TABLE execution_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    data_execucao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    modulo VARCHAR(50),
    status VARCHAR(20),         -- SUCCESS, ERROR
    registros_processados INTEGER DEFAULT 0,
    detalhes TEXT
);
```

Extensões da implementação: `dados_relatorio.origem` (STREAK | SEED), para trocar o histórico do Excel pelo dado ao vivo do Streak sem duplicar; `UNIQUE(sdr_id, data_registro)` em `emails_enviados`.

## 5. Estrutura do Projeto

```
/
├── app/
│   ├── main.py, database.py, models/schema.py, templating.py
│   ├── services/   streak_service, gmail_service, sync_service, seed_xlsx, util
│   ├── routes/     dashboard (abas 1-2), agenda, emails, analytics, sdrs, logs
│   ├── templates/, static/
├── data/           # volume Docker: database.db e seed/Controle SDrs.xlsx
├── Dockerfile, docker-compose.yml, requirements.txt, README.md
```

## 6. Segurança

O `Controle SDrs.xlsx` contém refresh tokens e client secrets. **Nunca** versionar no GitHub: fica em `data/seed/` (volume), fora do Git e da imagem (`.gitignore` e `.dockerignore`). O painel deve ter Basic Auth (`PANEL_USER`/`PANEL_PASSWORD`); a UI mostra segredos só mascarados.
