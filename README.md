# Controle SDRs (Python + SQLite)

Substitui as planilhas do Google Sheets. Coleta Streak CRM e Gmail/Agenda, grava em SQLite (`/data/database.db`) e exibe painel com 7 abas: Dashboard, Avanços & Follows, Agenda, Disparos, Analytics, SDRs, Logs. O botão "Executar sincronização agora" fica no topo de todas as telas.

## Variáveis de ambiente

| Var | Descrição |
|---|---|
| `SALESOPS_CLIENT_ID` / `SALESOPS_CLIENT_SECRET` / `SALESOPS_REFRESH_TOKEN` | OAuth do `salesops.ativa@gmail.com` (leitura de ZIPs). Escopo `gmail.readonly` |
| `SYNC_SINCE_DAYS` | Janela de busca de e-mails com ZIP (padrão 7) |
| `SYNC_INTERVAL_MIN` | Sync automática a cada N min (0 = só manual) |
| `PANEL_USER` / `PANEL_PASSWORD` | Basic auth do painel. **Defina**: o banco guarda API Keys |
| `APP_PORT` | Porta exposta (padrão 8000) |

API Key do Streak, chave do campo Follow-up e OAuth Gmail/Agenda de cada SDR (escopos `gmail.readonly` + `calendar.readonly`) são cadastradas na aba **SDRs**, sem tocar no código.

## Deploy no Portainer

Stacks → Add stack → Repository → URL do GitHub → `docker-compose.yml` → preencher variáveis → Deploy. Volume `sdr_data` persiste `/data`.

## Primeiro uso

1. Copie `Controle SDrs.xlsx` para `/data/seed/` **no volume** (nunca no Git: contém refresh tokens e client secrets). Na primeira subida o sistema importa Credentials, Dados do Relatóro, follows, Avanços, enviados, reuniões e Confirmacoes.
2. Aba **SDRs**: confira nomes e preencha a API Key do Streak e a chave de Follow-up de cada um. O Excel não traz as chaves do Streak.
3. **Executar sincronização agora**; resultado por módulo (STREAK, GMAIL, AGENDA, CONFIRMACOES) na aba Logs. Após o primeiro sync do Streak de um SDR, o histórico do Excel dele é substituído pelo dado ao vivo.

## Local

```
pip install -r requirements.txt
DATA_DIR=./data uvicorn app.main:app --reload
```
