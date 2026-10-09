"""Gmail + Calendar via REST (OAuth refresh token por conta)."""
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import httpx

from app.services.credenciais import cfg

GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
CAL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
TOKEN_URL = "https://oauth2.googleapis.com/token"


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
        return r.json()

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

    def confirmation_messages(self, days: int) -> list[dict]:
        """E-mails recebidos com "reuniao entre"/"proposta entre": [{id, from, subject, text, date}]."""
        q = f'newer_than:{days}d ("reuniao entre" OR "reunião entre" OR "proposta entre")'
        out = []
        for mid in self._ids(q):
            m = self._get(f"{GMAIL}/messages/{mid}", format="full")
            hdr = {h["name"].lower(): h["value"] for h in m["payload"].get("headers", [])}
            out.append({"id": mid, "from": hdr.get("from", ""), "subject": hdr.get("subject", ""),
                        "text": _body_text(m["payload"])[:6000], "date": datetime.fromtimestamp(int(m["internalDate"]) / 1000)})
        return out


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
