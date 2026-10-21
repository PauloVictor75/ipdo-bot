"""Configuração lida de arquivos .env (nada de senha no código). Modelo em .env.example.

- IPDO_CREDENCIAIS (opcional): .env compartilhado com outros robôs — EMAIL_USER, EMAIL_PASSWORD,
  EMAIL_SMTP_HOST, EMAIL_SMTP_PORT. Sem ele, tudo vem do .env do projeto.
- <projeto>/.env: IPDO_EMAIL_TO (vírgulas), IPDO_DRIVE_WEBHOOK_URL (Apps Script que guarda o PDF no Drive),
  IPDO_REMETENTE e IPDO_CABECALHO_URL (visual do e-mail).
Variáveis de ambiente de mesmo nome têm prioridade.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CREDENCIAIS = Path(os.environ.get("IPDO_CREDENCIAIS", RAIZ / ".env"))


@dataclass
class Config:
    email_user: str
    email_password: str
    smtp_host: str
    smtp_port: int
    destinatarios: list[str]
    drive_webhook_url: str
    pasta_estado: Path | None
    remetente: str = "IPDO Bot"
    cabecalho_url: str = ""


def ler_env(caminho: Path) -> dict[str, str]:
    valores = {}
    try:
        linhas = caminho.read_text(encoding="utf-8").splitlines()
    except OSError:
        return valores
    for linha in linhas:
        linha = linha.strip()
        if linha and not linha.startswith("#") and "=" in linha:
            chave, valor = linha.split("=", 1)
            valores[chave.strip()] = valor.strip().strip('"').strip("'")
    return valores


def carregar(credenciais: Path = CREDENCIAIS, local: Path = RAIZ / ".env") -> Config:
    valores = {**ler_env(credenciais), **ler_env(local), **os.environ}
    faltando = [c for c in ("EMAIL_USER", "EMAIL_PASSWORD", "IPDO_EMAIL_TO") if not valores.get(c)]
    if faltando:
        raise SystemExit(f"Configuração incompleta: falta {', '.join(faltando)} ({credenciais} ou {local}).")
    return Config(
        email_user=valores["EMAIL_USER"],
        email_password=valores["EMAIL_PASSWORD"],
        smtp_host=valores.get("EMAIL_SMTP_HOST", "smtp.zoho.com"),
        smtp_port=int(valores.get("EMAIL_SMTP_PORT", "465")),
        destinatarios=[d.strip() for d in valores["IPDO_EMAIL_TO"].split(",") if d.strip()],
        drive_webhook_url=valores.get("IPDO_DRIVE_WEBHOOK_URL", ""),
        pasta_estado=Path(valores.get("IPDO_PASTA_ESTADO", RAIZ / "estado")),
        remetente=valores.get("IPDO_REMETENTE", "IPDO Bot"),
        cabecalho_url=valores.get("IPDO_CABECALHO_URL", ""),
    )
