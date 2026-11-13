"""Diagnóstico das credenciais do SalesOps: mostra, passo a passo, o que o Google responde (sem imprimir segredos).

Uso (na pasta Painel_Sdr-master, com o painel parado ou rodando):   python diag_salesops.py
"""
from datetime import date, timedelta

import httpx

from app.services.credenciais import cfg

TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"


def mostra(r: httpx.Response) -> None:
    corpo = r.text.replace("\n", " ")
    print(f"   HTTP {r.status_code} | content-type={r.headers.get('content-type')} | tamanho={len(r.text)}")
    print(f"   corpo: {corpo[:300]!r}")


cid, sec, tok = (cfg(k) or "" for k in ("SALESOPS_CLIENT_ID", "SALESOPS_CLIENT_SECRET", "SALESOPS_REFRESH_TOKEN"))
print("0) Valores salvos no painel")
print(f"   Client ID : {len(cid)} caracteres, começa com {cid[:12]!r}, termina com {cid[-25:]!r}")
print(f"   Secret    : {len(sec)} caracteres, começa com {sec[:6]!r}")
print(f"   Token     : {len(tok)} caracteres, começa com {tok[:4]!r}")
for nome, v in (("Client ID", cid), ("Secret", sec), ("Token", tok)):
    if v != v.strip() or any(c in v for c in " \n\r\t"):
        print(f"   ATENÇÃO: {nome} tem espaço/quebra de linha escondido — recole sem espaços")

with httpx.Client(timeout=30) as http:
    print("\n1) Trocar o Refresh Token por um Access Token")
    r = http.post(TOKEN_URL, data={"client_id": cid.strip(), "client_secret": sec.strip(),
                                   "refresh_token": tok.strip(), "grant_type": "refresh_token"})
    mostra(r)
    if r.status_code != 200:
        raise SystemExit("\nParou no passo 1: o Google não aceitou as credenciais (veja o corpo acima).")
    http.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    try:
        print("   escopo concedido:", r.json().get("scope"))
    except ValueError:
        pass

    print("\n2) De qual conta é esse token?")
    r = http.get(f"{GMAIL}/profile")
    mostra(r)

    q = '("reuniao entre" OR "reunião entre" OR "proposta entre")'
    print("\n3) Buscar e-mails de confirmação (últimos 14 dias)")
    r = http.get(f"{GMAIL}/messages", params={"q": f"newer_than:14d {q}", "maxResults": 5})
    mostra(r)

    print("\n4) Busca direcionada (a mesma que o painel usa por reunião)")
    ini, fim = date.today() - timedelta(days=45), date.today() + timedelta(days=2)
    r = http.get(f"{GMAIL}/messages", params={"q": f'{q} ("Nenhum Termo Existe Aqui") after:{ini:%Y/%m/%d} before:{fim:%Y/%m/%d}',
                                              "maxResults": 1, "fields": "messages/id"})
    mostra(r)
