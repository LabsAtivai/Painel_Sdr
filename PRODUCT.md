# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users
Gestor comercial / SalesOps da Ativa AI, pt-BR, uso diário em desktop (celular ocasional). Abre o painel para ver quem está atrasado nos follows, o que há na agenda de hoje/amanhã/segunda, quanto cada SDR disparou, e para administrar admissões/demissões de SDRs. Confirmado pelo usuário.

## Product Purpose
Substituir as planilhas do Google Sheets (Controle SDrs - Dashboard) por uma aplicação Python + SQLite que coleta do Streak CRM e do Gmail, consolida e exibe em abas. Sucesso: o gestor deixa de abrir planilhas, enxerga atrasos e agenda em segundos e dispara sincronização quando precisa.

## Positioning
Painel único e dono dos próprios dados (SQLite) que une Streak, Gmail e mapeamento de SDRs editável (De/Para) sem mexer em código.

## Operating Context
Docker/Portainer a partir do GitHub. Fontes: Streak CRM (API keys por SDR), Gmail (salesops.ativa@gmail.com e contas sdrX.ativa@gmail.com). Fases: Avanço, Follow Futuro, Encaminhamento. Reuniões identificadas por "reuniao entre" / "proposta entre".

## Capabilities and Constraints
5 abas: Dashboard (Avanços & Follows), Agenda de Reuniões (Hoje/Amanhã/Segunda/Semanal), E-mails Enviados, Gestão de SDRs (nome, e-mail, API key Streak, follow-up key, inativar, reatribuir histórico), Logs e Status de Sincronização. Botão "Executar Sincronização Agora" sempre visível. Stack fixa: FastAPI + Jinja2 + CSS próprio (app/static/app.css, sem Tailwind), SQLite em /data. API keys nunca exibidas por inteiro.

## Product Principles
1. Atraso e agenda primeiro: o que exige ação do gestor aparece antes do histórico.
2. Dados densos e escaneáveis; tabelas são o produto.
3. Estado de sincronização sempre honesto: quando atualizou, se falhou, de qual fonte.
4. Operações de pessoas (demitir, reatribuir) são explícitas e reversíveis ou confirmadas.

## Accessibility & Inclusion
Interface em português do Brasil; contraste legível em ambiente de escritório.
