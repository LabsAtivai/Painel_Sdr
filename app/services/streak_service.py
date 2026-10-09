"""Streak CRM: boxes do primeiro pipeline de cada SDR."""
import base64
import time
from datetime import datetime

import httpx

from app.services.util import days_since

BASE = "https://api.streak.com/api/v1"
PAGE = 100
MAX_PAGES = 100


def basic_token(key: str) -> str:
    """Aceita a chave crua do Streak ou o token Basic já em base64 ('chave:')."""
    k = key.strip()
    try:
        if base64.b64decode(k, validate=True).decode().endswith(":"):
            return k
    except Exception:
        pass
    return base64.b64encode(f"{k}:".encode()).decode()


def _get(client: httpx.Client, url: str, retries: int = 3):
    for attempt in range(retries + 1):
        r = client.get(url)
        if r.status_code == 429:
            time.sleep(2**attempt)
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"Streak: rate limit persistente em {url}")


def _ts(v) -> datetime | None:
    return datetime.fromtimestamp(v / 1000) if isinstance(v, (int, float)) and v > 0 else None


def fetch_boxes(api_key: str, follow_up_key: str | None) -> list[dict]:
    headers = {"accept": "application/json", "authorization": f"Basic {basic_token(api_key)}"}
    out: list[dict] = []
    with httpx.Client(headers=headers, timeout=30) as c:
        pipes = _get(c, f"{BASE}/pipelines")
        if not isinstance(pipes, list) or not pipes:
            raise RuntimeError("nenhum pipeline encontrado")
        pipe = pipes[0]
        pkey = pipe.get("pipelineKey") or pipe.get("key")
        stages = pipe.get("stages") or {}
        for page in range(MAX_PAGES):
            time.sleep(0.12)  # Streak pede <10 req/s
            data = _get(c, f"{BASE}/pipelines/{pkey}/boxes?limit={PAGE}&page={page}&sortBy=lastUpdatedTimestamp")
            # docs: a resposta indica hasNextPage; sem o flag (lista pura), página cheia = pode haver mais
            if isinstance(data, dict):
                boxes, has_next = data.get("results") or data.get("boxes") or [], bool(data.get("hasNextPage"))
            elif isinstance(data, list):
                boxes, has_next = data, len(data) >= PAGE
            else:
                break
            for b in boxes:
                fu = _ts((b.get("fields") or {}).get(follow_up_key)) if follow_up_key else None
                recebido = _ts(b.get("lastEmailReceivedTimestamp"))
                ultimo = recebido or _ts(b.get("lastEmailTimestamp")) or _ts(b.get("lastEmailSentTimestamp"))
                enviados = int(b.get("totalNumberOfSentEmails") or 0)
                recebidos = int(b.get("totalNumberOfReceivedEmails") or 0)
                out.append({
                    "cliente": (b.get("name") or "")[:150],
                    "fase": (stages.get(b.get("stageKey")) or {}).get("name", "N/A")[:50],
                    "pipeline": (pipe.get("name") or "")[:50],
                    "total_emails": int(b.get("totalNumberOfEmails") or (enviados + recebidos)),
                    "emails_enviados": enviados,
                    "emails_recebidos": recebidos,
                    "primeiro_email": _ts(b.get("firstEmailTimestamp")),
                    "ultimo_email_recebido": recebido,
                    "follow_up": fu,
                    "dias_atraso": days_since(fu),
                    "dias_desde_ultimo_email": days_since(ultimo),
                    "notas": (b.get("notes") or None),
                })
            if not has_next or not boxes:
                break
    return out


def testar(api_key: str) -> str:
    """Valida a chave: devolve o nome do primeiro pipeline."""
    with httpx.Client(headers={"accept": "application/json", "authorization": f"Basic {basic_token(api_key)}"}, timeout=20) as c:
        pipes = _get(c, f"{BASE}/pipelines")
    if not isinstance(pipes, list) or not pipes:
        raise RuntimeError("chave válida, mas sem pipelines")
    return f"{len(pipes)} pipeline(s), primeiro: {pipes[0].get('name', '?')}"
