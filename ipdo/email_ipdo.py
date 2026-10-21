"""E-mail do IPDO (HTML com tabelas, compatível com Gmail e Outlook) e envio por SMTP com SSL."""
from __future__ import annotations

import smtplib
import time
from email.mime.application import MIMEApplication
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from html import escape

from ipdo.config import RAIZ, Config
from ipdo.extracao import Resultado, Secao

LOGO = RAIZ / "assets" / "logo.png"
PAUSA = 20  # segundos antes da 2ª tentativa de envio

# cor da barra lateral de cada seção, na ordem de extracao.TITULOS
_CORES = ("#185FA5", "#2E7D32", "#BA7517", "#A32D2D", "#3B6D11", "#546E7A")
_FONTE = "font-family:Arial, Helvetica, sans-serif;"


def montar_assunto(r: Resultado, data_arquivo: str) -> str:
    quando = f"operação de {r.data_operacao}" if r.data_operacao else f"arquivo de {data_arquivo}"
    return f"IPDO · {quando} · Nordeste" + (" · ⚠ confira o PDF" if r.avisos else "")


def _conteudo_html(s: Secao) -> str:
    if s.faltou:
        return (f'<p style="margin:0; {_FONTE} font-size:13px; color:#B26A00; font-weight:bold;">'
                "⚠ Bloco não encontrado no PDF — confira o PDF anexo.</p>")
    if not s.itens:
        return f'<p style="margin:0; {_FONTE} font-size:13px; color:#78909C; font-style:italic;">Nada a relatar.</p>'
    partes = []
    for item in s.itens:
        if item.rotulo:
            partes.append(f'<p style="margin:8px 0 2px; {_FONTE} font-size:13px; font-weight:bold; color:#263238;">'
                          f"{escape(item.rotulo)}</p>")
        lis = "".join(f'<li style="margin-bottom:4px;">{escape(f)}</li>' for f in item.frases)
        partes.append(f'<ul style="margin:0; padding-left:18px; {_FONTE} font-size:13px; line-height:1.6; '
                      f'color:#263238;">{lis}</ul>')
    return "".join(partes)


def _secao_html(s: Secao, cor: str) -> str:
    return f"""
        <tr><td style="padding:0 24px 14px;">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
                 style="border:1px solid #E0E6ED; border-left:4px solid {cor}; border-radius:6px;">
            <tr><td style="padding:10px 14px 4px; {_FONTE} font-size:13px; font-weight:bold; color:{cor};">{escape(s.titulo)}</td></tr>
            <tr><td style="padding:2px 14px 12px;">{_conteudo_html(s)}</td></tr>
          </table>
        </td></tr>"""


def _avisos_html(avisos: list[str]) -> str:
    if not avisos:
        return ""
    lis = "".join(f"<li>{escape(a)}</li>" for a in avisos)
    return f"""
        <tr><td style="padding:0 24px 16px;">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
                 style="background:#FFF4E5; border:1px solid #F0B35B; border-radius:6px;">
            <tr><td style="padding:10px 14px; {_FONTE} font-size:13px; color:#7A4A00;">
              <strong>⚠ Confira o PDF anexo</strong> — a leitura automática encontrou diferenças:
              <ul style="margin:6px 0 0; padding-left:18px;">{lis}</ul>
            </td></tr>
          </table>
        </td></tr>"""


def _fundo_cabecalho(url: str) -> str:
    """Imagem de fundo opcional (IPDO_CABECALHO_URL); sem ela, ou no Outlook desktop, fica o azul #062a57."""
    if not url:
        return 'bgcolor="#062a57" style="background-color:#062a57; padding:18px;"'
    url = escape(url)
    return (f'background="{url}" bgcolor="#062a57" style="background-color:#062a57; background-image:url(\'{url}\'); '
            'background-size:600px 110px; background-repeat:no-repeat; background-position:center center; padding:18px;"')


def _pagina(rotulo: str, data: str, corpo: str, cabecalho_url: str = "") -> str:
    return f"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0; padding:0; background-color:#F4F6F9;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#F4F6F9; padding:24px 0;">
  <tr><td align="center">
    <table role="presentation" width="600" cellpadding="0" cellspacing="0"
           style="width:600px; max-width:600px; background-color:#FFFFFF; border-radius:12px; overflow:hidden;">
      <tr><td {_fundo_cabecalho(cabecalho_url)}>
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
          <td width="24%" style="vertical-align:middle;"><img src="cid:logo" alt="Logo" width="96" style="display:block; width:96px;"></td>
          <td width="42%" style="vertical-align:middle; border-left:1px solid #5b7299; padding:2px 0 2px 16px;">
            <h1 style="margin:0; color:#FFFFFF; {_FONTE} font-size:20px; line-height:24px;">IPDO</h1>
            <p style="margin:4px 0 0; color:#dbe5f5; {_FONTE} font-size:10px; letter-spacing:0.6px;">INFORMATIVO PRELIMINAR DIÁRIO DA OPERAÇÃO</p>
          </td>
          <td width="34%" style="vertical-align:middle; text-align:right;">
            <p style="margin:0; color:#FFFFFF; {_FONTE} font-size:10px; letter-spacing:0.6px;">{escape(rotulo)}</p>
            <p style="margin:6px 0 0; color:#FFFFFF; {_FONTE} font-size:16px; font-weight:bold;">{escape(data)}</p>
          </td>
        </tr></table>
      </td></tr>
      {corpo}
      <tr><td style="background-color:#ECEFF1; padding:7px 40px; text-align:center; border-top:1px solid #E0E0E0;">
        <p style="margin:0; {_FONTE} font-size:9px; color:#78909C;"><strong style="color:#263238;">IPDO</strong> · Fonte: ONS · Mensagem automática, não responda</p>
      </td></tr>
    </table>
  </td></tr>
</table>
</body></html>"""


def montar_html(r: Resultado, data_arquivo: str, cabecalho_url: str = "") -> str:
    data = r.data_operacao or data_arquivo
    intro = (f'<tr><td style="padding:20px 24px 14px; {_FONTE} font-size:14px; color:#455A64;">'
             f"Destaques do IPDO para o submercado <strong>Nordeste</strong> — operação de {escape(data)}. "
             "O PDF completo segue em anexo.</td></tr>")
    corpo = intro + _avisos_html(r.avisos) + "".join(_secao_html(s, c) for s, c in zip(r.secoes, _CORES))
    return _pagina("OPERAÇÃO DO DIA", data, corpo, cabecalho_url)


def montar_texto(r: Resultado, data_arquivo: str) -> str:
    linhas = [f"IPDO — Destaques do submercado Nordeste — operação de {r.data_operacao or data_arquivo}", ""]
    if r.avisos:
        linhas += ["⚠ CONFIRA O PDF ANEXO:", *[f"  * {a}" for a in r.avisos], ""]
    for s in r.secoes:
        linhas.append(s.titulo.upper())
        if s.faltou:
            linhas.append("  ⚠ Bloco não encontrado no PDF — confira o PDF anexo.")
        elif not s.itens:
            linhas.append("  Nada a relatar.")
        for item in s.itens:
            if item.rotulo:
                linhas.append(f"  [{item.rotulo}]")
            linhas += [f"  - {f}" for f in item.frases]
        linhas.append("")
    return "\n".join(linhas)


def montar_falha(data_arquivo: str, motivo: str, cabecalho_url: str = "") -> tuple[str, str, str]:
    assunto = f"IPDO · falha no envio de {data_arquivo}"
    corpo = (f'<tr><td style="padding:20px 24px; {_FONTE} font-size:14px; color:#455A64;">'
             f"O IPDO de <strong>{escape(data_arquivo)}</strong> não foi enviado hoje.<br><br>"
             f'<span style="color:#A32D2D;">{escape(motivo)}</span></td></tr>')
    texto = f"O IPDO de {data_arquivo} não foi enviado hoje.\n\n{motivo}\n"
    return assunto, _pagina("FALHA", data_arquivo, corpo, cabecalho_url), texto


def montar_mensagem(cfg: Config, assunto: str, html: str, texto: str,
                    anexo: tuple[str, bytes] | None = None) -> MIMEMultipart:
    msg = MIMEMultipart("mixed")
    msg["From"] = formataddr((cfg.remetente, cfg.email_user))
    msg["To"] = ", ".join(cfg.destinatarios)
    msg["Subject"] = assunto
    alternativa = MIMEMultipart("alternative")
    alternativa.attach(MIMEText(texto, "plain", "utf-8"))
    relacionado = MIMEMultipart("related")
    relacionado.attach(MIMEText(html, "html", "utf-8"))
    logo = MIMEImage(LOGO.read_bytes(), _subtype="png")
    logo.add_header("Content-ID", "<logo>")
    logo.add_header("Content-Disposition", "inline", filename="logo.png")
    relacionado.attach(logo)
    alternativa.attach(relacionado)
    msg.attach(alternativa)
    if anexo:
        nome, conteudo = anexo
        pdf = MIMEApplication(conteudo, _subtype="pdf")
        pdf.add_header("Content-Disposition", "attachment", filename=nome)
        msg.attach(pdf)
    return msg


def enviar(cfg: Config, msg: MIMEMultipart, tentativas: int = 2) -> None:
    """SMTP por SSL (465); repete uma vez em erro de rede/SMTP. A última falha sobe para quem chamou."""
    for n in range(1, tentativas + 1):
        try:
            with smtplib.SMTP_SSL(cfg.smtp_host, cfg.smtp_port, timeout=30) as smtp:
                smtp.login(cfg.email_user, cfg.email_password)
                smtp.send_message(msg, to_addrs=cfg.destinatarios)
            return
        except (smtplib.SMTPException, OSError):
            if n == tentativas:
                raise
            time.sleep(PAUSA)
