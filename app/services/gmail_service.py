"""Gmail + Calendar via REST (OAuth refresh token por conta)."""
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import httpx

from app.services.credenciais import cfg

GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
CAL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
TOKEN_URL = "https://oauth2.googleapis.com/token"
# o que caracteriza um e-mail de confirmação (usado na coleta em lote e na busca direcionada)
CONFIRMACAO_Q = '("reuniao entre" OR "reunião entre" OR "proposta entre")'


@dataclass
class Creds:
    client_id: str
    client_secret: str
    refresh_token: str


def salesops_creds() -> Creds | None:
    c = Creds(cfg("SALESOPS_CLIENT_ID"), cfg("SALESOPS_CLIENT_SECRET"), cfg("SALESOPS_REFRESH_TOKEN"))
    return c if c.client_id and c.client_secret and c.refresh_token else None


def sdr_creds(sdr) -> Creds | None:
    if sdr.client_id and sdr.client_secret and sdr.refresh_token:
        return Creds(sdr.client_id, sdr.client_secret, sdr.refresh_token)
    return None


class Google:
    def __init__(self, creds: Creds):
        self._http = httpx.Client(timeout=30)
        r = self._http.post(TOKEN_URL, data={
            "client_id": creds.client_id, "client_secret": creds.client_secret,
            "refresh_token": creds.refresh_token, "grant_type": "refresh_token",
        })
        if r.status_code != 200:
            raise RuntimeError(f"OAuth falhou: {r.json().get('error_description') or r.json().get('error') or r.status_code}")
        self._http.headers["Authorization"] = f"Bearer {r.json()['access_token']}"

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._http.close()

    def _get(self, url, **params):
        r = self._http.get(url, params=params)
        r.raise_for_status()
        return r.json() if r.content else {}

    def profile(self) -> str:
        return self._get(f"{GMAIL}/profile").get("emailAddress", "")

    def _ids(self, q: str) -> list[str]:
        ids, token = [], None
        while True:
            d = self._get(f"{GMAIL}/messages", q=q, maxResults=500, **({"pageToken": token} if token else {}))
            ids += [m["id"] for m in d.get("messages", [])]
            token = d.get("nextPageToken")
            if not token or len(ids) > 20000:
                return ids

    def count_sent(self, day: date) -> int:
        return len(self._ids(f"in:sent after:{day:%Y/%m/%d} before:{day + timedelta(days=1):%Y/%m/%d}"))

    def calendar_events(self, start: datetime, end: datetime) -> list[dict]:
        d = self._get(CAL, timeMin=start.astimezone().isoformat(), timeMax=end.astimezone().isoformat(),
                      singleEvents="true", orderBy="startTime", maxResults=500)
        return d.get("items", [])

    def _message(self, mid: str) -> dict:
        """Lê UM e-mail completo: {id, from, subject, text, date}."""
        m = self._get(f"{GMAIL}/messages/{mid}", format="full")
        hdr = {h["name"].lower(): h["value"] for h in m["payload"].get("headers", [])}
        return {"id": mid, "from": hdr.get("from", ""), "subject": hdr.get("subject", ""),
                "text": _body_text(m["payload"])[:6000], "date": datetime.fromtimestamp(int(m["internalDate"]) / 1000)}

    def confirmation_messages(self, days: int, skip_ids: set[str] | frozenset[str] = frozenset()) -> list[dict]:
        """E-mails com "reuniao entre"/"proposta entre". Só baixa o corpo dos IDs que NÃO estão em skip_ids."""
        ids = self._ids(f"newer_than:{days}d {CONFIRMACAO_Q}")
        return [self._message(mid) for mid in ids if mid not in skip_ids]

    def find_confirmation(self, termos: list[str], inicio: datetime, fim: datetime) -> dict | None:
        """Busca direcionada: existe e-mail de confirmação que cite algum dos termos entre inicio e fim?

        Custa 1 chamada leve (maxResults=1, só o id); só lê o e-mail se achar. Devolve o e-mail ou None.
        """
        termos = list(dict.fromkeys(t.replace('"', " ").strip() for t in termos if t and len(t.strip()) >= 3))
        if not termos:
            return None
        ou = " OR ".join(f'"{t}"' for t in termos)
        q = f"{CONFIRMACAO_Q} ({ou}) after:{inicio:%Y/%m/%d} before:{fim:%Y/%m/%d}"
        achados = self._get(f"{GMAIL}/messages", q=q, maxResults=1, fields="messages/id").get("messages", [])
        return self._message(achados[0]["id"]) if achados else None


def _body_text(payload: dict) -> str:
    """Texto do e-mail (text/plain; se só houver HTML, remove as tags)."""
    import base64
    import re

    plain, html, stack = [], [], [payload]
    while stack:
        p = stack.pop()
        stack.extend(p.get("parts", []))
        data = p.get("body", {}).get("data")
        if not data:
            continue
        txt = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", errors="replace")
        (plain if p.get("mimeType") == "text/plain" else html if p.get("mimeType") == "text/html" else []).append(txt)
    return " ".join(plain) or re.sub(r"<[^>]+>", " ", " ".join(html))
