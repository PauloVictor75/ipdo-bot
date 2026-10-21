"""Rodada do dia: baixa o PDF do ONS, guarda no Drive, lê os destaques e manda o e-mail.

O cron roda duas vezes (11:00 e 13:00) com --se-pendente: a 2ª só age se a 1ª não enviou (PDF ainda não
publicado, ONS fora, SMTP fora). Na 2ª (--alertar-falha), se ainda não der, vai um e-mail de falha.
"""
from __future__ import annotations

import base64
import time
from datetime import date
from pathlib import Path

import requests

from ipdo import email_ipdo, extracao
from ipdo.config import Config

ACERVO_ONS = "https://www.ons.org.br/AcervoDigitalDocumentosEPublicacoes/"
PAUSA = 30  # segundos entre tentativas de download


class PdfIndisponivel(Exception):
    pass


def nome_arquivo(dia: date) -> str:
    return f"IPDO-{dia:%d-%m-%Y}.pdf"


def baixar_pdf(dia: date, tentativas: int = 3) -> bytes:
    url = ACERVO_ONS + nome_arquivo(dia)
    for n in range(1, tentativas + 1):
        try:
            r = requests.get(url, timeout=60)
        except requests.RequestException as erro:
            if n == tentativas:
                raise PdfIndisponivel(f"ONS fora do ar ou lento ({erro.__class__.__name__}).") from erro
            time.sleep(PAUSA)
            continue
        if r.status_code == 404:
            raise PdfIndisponivel("PDF ainda não publicado pelo ONS (HTTP 404).")
        if r.status_code != 200 or not r.content.startswith(b"%PDF"):
            raise PdfIndisponivel(f"O ONS não devolveu um PDF (HTTP {r.status_code}).")
        return r.content
    raise PdfIndisponivel("Não foi possível baixar o PDF.")  # pragma: no cover


def salvar_no_drive(cfg: Config, pdf: bytes, dia: date) -> bool:
    """Apps Script que guarda em IPDO/<ano>/<mês> no Google Drive. Falha não impede o e-mail."""
    if not cfg.drive_webhook_url:
        print("⚠️ IPDO_DRIVE_WEBHOOK_URL vazio: PDF não guardado no Drive.")
        return False
    corpo = {"tipo": "IPDO", "ano": f"{dia:%Y}", "mes": f"{dia:%m}", "nome_arquivo": nome_arquivo(dia),
             "pdf_base64": base64.b64encode(pdf).decode("ascii")}
    try:
        r = requests.post(cfg.drive_webhook_url, json=corpo, timeout=60)
    except requests.RequestException as erro:
        print(f"⚠️ Falha ao guardar o IPDO no Drive: {erro.__class__.__name__}")
        return False
    if r.status_code != 200:
        print(f"⚠️ Drive respondeu HTTP {r.status_code}.")
        return False
    return True


def _marcador(pasta: Path) -> Path:
    return pasta / "ultimo_envio.txt"


def ja_enviado(pasta: Path, dia: date) -> bool:
    try:
        return _marcador(pasta).read_text(encoding="utf-8").strip() == dia.isoformat()
    except OSError:
        return False


def registrar_envio(pasta: Path, dia: date) -> None:
    pasta.mkdir(parents=True, exist_ok=True)
    _marcador(pasta).write_text(dia.isoformat(), encoding="utf-8")


def _alertar(cfg: Config, dia: date, motivo: str) -> None:
    assunto, html, texto = email_ipdo.montar_falha(f"{dia:%d/%m/%Y}", motivo, cfg.cabecalho_url)
    try:
        email_ipdo.enviar(cfg, email_ipdo.montar_mensagem(cfg, assunto, html, texto))
    except Exception as erro:  # noqa: BLE001 — o alerta é o último recurso; só registra no log
        print(f"❌ Nem o e-mail de falha saiu: {erro.__class__.__name__}: {erro}")


def executar(cfg: Config, dia: date, *, se_pendente: bool = False, alertar_falha: bool = False,
             previa: Path | None = None) -> int:
    """0 = enviado (ou já tinha sido); 1 = não enviado (a próxima rodada tenta de novo)."""
    data_arquivo = f"{dia:%d/%m/%Y}"
    if se_pendente and ja_enviado(cfg.pasta_estado, dia):
        print(f"IPDO de {data_arquivo} já enviado — nada a fazer.")
        return 0
    try:
        pdf = baixar_pdf(dia)
    except PdfIndisponivel as erro:
        print(f"❌ {erro}")
        if alertar_falha:
            _alertar(cfg, dia, str(erro))
        return 1

    resultado = extracao.extrair(pdf)
    for aviso in resultado.avisos:
        print(f"⚠️ {aviso}")
    assunto = email_ipdo.montar_assunto(resultado, data_arquivo)
    html = email_ipdo.montar_html(resultado, data_arquivo, cfg.cabecalho_url)
    texto = email_ipdo.montar_texto(resultado, data_arquivo)
    if previa:
        previa.write_text(html, encoding="utf-8")
        print(f"Prévia gravada em {previa} (nada enviado).\n\n{assunto}\n\n{texto}")
        return 0

    if salvar_no_drive(cfg, pdf, dia):
        print("📁 IPDO guardado no Drive.")
    mensagem = email_ipdo.montar_mensagem(cfg, assunto, html, texto, (nome_arquivo(dia), pdf))
    try:
        email_ipdo.enviar(cfg, mensagem)
    except Exception as erro:  # noqa: BLE001
        print(f"❌ Falha ao enviar o e-mail: {erro.__class__.__name__}: {erro}")
        if alertar_falha:
            _alertar(cfg, dia, f"O e-mail não saiu: {erro.__class__.__name__}: {erro}")
        return 1
    registrar_envio(cfg.pasta_estado, dia)
    print(f"✅ {assunto} → {', '.join(cfg.destinatarios)}")
    return 0
