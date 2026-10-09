import tempfile
from pathlib import Path
from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.schema import SDR, CredencialVersao
from app.services import credenciais as cred
from app.services import gmail_service, streak_service
from app.templating import templates

router = APIRouter(prefix="/credenciais")
MAX_UPLOAD = 60 * 1024 * 1024


def _back(msg: str, sdr_id: int | None = None):
    anchor = f"#sdr-{sdr_id}" if sdr_id else ""
    return RedirectResponse(f"/credenciais?msg={quote_plus(msg)}{anchor}", status_code=303)


@router.get("")
def pagina(request: Request, db: Session = Depends(get_db)):
    sdrs = db.scalars(select(SDR).order_by(SDR.ativo.desc(), SDR.nome)).all()
    versoes: dict[int, list] = {s.id: [] for s in sdrs}
    for v in db.scalars(select(CredencialVersao).order_by(CredencialVersao.sdr_id, CredencialVersao.versao.desc())):
        versoes.setdefault(v.sdr_id, []).append(v)
    configs = [{"chave": k, "rotulo": r, "segredo": sec, "ajuda": h, "valor": cred.cfg(k)} for k, (r, sec, h) in cred.CONFIGS.items()]
    return templates.TemplateResponse(request, "credenciais.html", {
        "sdrs": sdrs, "versoes": versoes, "configs": configs, "page": "credenciais"})


@router.post("/sdr")
async def novo_sdr(request: Request, db: Session = Depends(get_db)):
    f = dict(await request.form())
    nome, email = (f.get("nome") or "").strip(), (f.get("email") or "").strip().lower()
    if not nome or "@" not in email:
        return _back("Informe nome e um e-mail válido")
    sdr = SDR(nome=nome[:100], email=email[:150])
    db.add(sdr)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return _back(f"E-mail já cadastrado: {email}")
    cred.aplicar(db, sdr, f, f.get("motivo") or "Cadastro inicial")
    db.commit()
    return _back(f"{nome} adicionado", sdr.id)


@router.post("/{sdr_id}/versao")
async def nova_versao(sdr_id: int, request: Request, db: Session = Depends(get_db)):
    sdr = db.get(SDR, sdr_id)
    if not sdr:
        return _back("SDR não encontrado")
    f = dict(await request.form())
    n = cred.aplicar(db, sdr, f, f.get("motivo") or "Atualização manual")
    db.commit()
    return _back(f"{sdr.nome}: versão v{n} criada" if n else f"{sdr.nome}: nada mudou, nenhuma versão criada", sdr_id)


@router.post("/{sdr_id}/restaurar/{versao_id}")
def restaurar(sdr_id: int, versao_id: int, db: Session = Depends(get_db)):
    sdr, v = db.get(SDR, sdr_id), db.get(CredencialVersao, versao_id)
    if not sdr or not v or v.sdr_id != sdr_id:
        return _back("Versão não encontrada")
    n = cred.aplicar(db, sdr, {c: getattr(v, c) for c in cred.CAMPOS}, f"Restaurada da v{v.versao}", exato=True)
    db.commit()
    return _back(f"{sdr.nome}: v{v.versao} restaurada como v{n}" if n else f"{sdr.nome}: v{v.versao} já é a versão atual", sdr_id)


@router.post("/{sdr_id}/testar")
def testar(sdr_id: int, db: Session = Depends(get_db)):
    sdr = db.get(SDR, sdr_id)
    if not sdr:
        return _back("SDR não encontrado")
    out = []
    if sdr.streak_api_key:
        try:
            out.append("Streak OK: " + streak_service.testar(sdr.streak_api_key))
        except Exception as e:
            out.append(f"Streak FALHOU: {type(e).__name__} {str(e)[:120]}")
    else:
        out.append("Streak: sem API Key")
    c = gmail_service.sdr_creds(sdr)
    if c:
        try:
            with gmail_service.Google(c) as g:
                out.append(f"Google OK (conta {g.profile()})")
        except Exception as e:
            out.append(f"Google FALHOU: {type(e).__name__} {str(e)[:120]}")
    else:
        out.append("Google: faltam Client ID/Secret/Refresh Token")
    return _back(f"{sdr.nome} · " + " · ".join(out), sdr_id)


@router.post("/config")
async def salvar_config(request: Request, db: Session = Depends(get_db)):
    f = dict(await request.form())
    n = 0
    for k, (_, segredo, _h) in cred.CONFIGS.items():
        v = (f.get(k) or "").strip()
        if v:
            cred.set_cfg(db, k, v)
            n += 1
        elif f.get(f"limpar_{k}"):
            cred.set_cfg(db, k, None)
            n += 1
    db.commit()
    return _back(f"{n} configuração(ões) salva(s)")


@router.post("/importar")
async def importar(arquivo: UploadFile = File(...), db: Session = Depends(get_db)):
    if not (arquivo.filename or "").lower().endswith(".xlsx"):
        return _back("Envie um arquivo .xlsx")
    dados = await arquivo.read(MAX_UPLOAD + 1)
    if len(dados) > MAX_UPLOAD:
        return _back("Arquivo maior que 60 MB")
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "upload.xlsx"
        p.write_bytes(dados)
        try:
            criados, atualizados = cred.importar_planilha_credenciais(db, p, f"Importado de {Path(arquivo.filename).name}")
        except Exception as e:
            db.rollback()
            return _back(f"Falha ao importar: {type(e).__name__}: {e}")
    return _back(f"Importação: {criados} SDR(s) criado(s), {atualizados} atualizado(s) (nova versão cada)")
