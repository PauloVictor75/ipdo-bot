from email import message_from_bytes

import pytest

from ipdo import email_ipdo
from ipdo.config import Config
from ipdo.extracao import TITULOS, Item, Resultado, Secao


def resultado(avisos=(), data="18/10/2026"):
    secoes = [Secao(t, []) for t in TITULOS]
    secoes[1] = Secao(TITULOS[1], [Item("", ["Valor máximo: 2.062 MW.", "Período: Das 07h00 às 22h54."])])
    secoes[3] = Secao(TITULOS[3], [Item("Rede de Operação · Maranhão", ["Interrupção de carga: 480 MW <SE>."])])
    secoes[5] = Secao(TITULOS[5], [], faltou=True)
    return Resultado(data, secoes, list(avisos))


CFG = Config(email_user="robo@example.com", email_password="x", smtp_host="smtp.zoho.com", smtp_port=465,
             destinatarios=["a@x.com", "b@x.com"], drive_webhook_url="", pasta_estado=None)


def test_assunto_usa_a_data_da_operacao():
    assert email_ipdo.montar_assunto(resultado(), "19/10/2026") == "IPDO · operação de 18/10/2026 · Nordeste"


def test_assunto_com_aviso_pede_conferencia():
    assert email_ipdo.montar_assunto(resultado(["x"]), "19/10/2026").endswith("· ⚠ confira o PDF")


def test_assunto_sem_data_no_pdf_usa_a_do_arquivo():
    assert "arquivo de 19/10/2026" in email_ipdo.montar_assunto(resultado(data=None), "19/10/2026")


def test_html_tem_cabecalho_secoes_e_escapa_texto():
    html = email_ipdo.montar_html(resultado(), "19/10/2026")
    assert "cid:logo" in html and "background-image" not in html
    for titulo in TITULOS:
        assert titulo in html
    assert "Valor máximo: 2.062 MW." in html
    assert "Rede de Operação · Maranhão" in html
    assert "&lt;SE&gt;" in html and "<SE>" not in html
    assert "Nada a relatar." in html


def test_secao_que_faltou_nao_diz_nada_a_relatar():
    html = email_ipdo.montar_html(resultado(), "19/10/2026")
    trecho = html[html.index(TITULOS[5]):]
    assert "não encontrado no PDF" in trecho[:600]


def test_html_mostra_avisos():
    html = email_ipdo.montar_html(resultado(["O bloco X sumiu"]), "19/10/2026")
    assert "O bloco X sumiu" in html and "Confira o PDF anexo" in html
    assert "O bloco X sumiu" not in email_ipdo.montar_html(resultado(), "19/10/2026")


def test_texto_simples():
    texto = email_ipdo.montar_texto(resultado(["aviso 1"]), "19/10/2026")
    assert "operação de 18/10/2026" in texto and "- Valor máximo: 2.062 MW." in texto
    assert "[Rede de Operação · Maranhão]" in texto and "aviso 1" in texto


def test_mensagem_tem_remetente_destinatarios_logo_e_pdf():
    msg = email_ipdo.montar_mensagem(CFG, "Assunto", "<p>oi</p>", "oi", ("IPDO-19-10-2026.pdf", b"%PDF-1.4 x"))
    lida = message_from_bytes(msg.as_bytes())
    assert lida["From"] == "IPDO Bot <robo@example.com>"
    assert lida["To"] == "a@x.com, b@x.com"
    partes = {p.get_content_type(): p for p in lida.walk()}
    assert "image/png" in partes and partes["image/png"]["Content-ID"] == "<logo>"
    pdf = partes["application/pdf"]
    assert pdf.get_filename() == "IPDO-19-10-2026.pdf" and pdf.get_payload(decode=True) == b"%PDF-1.4 x"


def test_enviar_usa_ssl_e_login(monkeypatch):
    chamadas = []

    class SMTP:
        def __init__(self, host, port, timeout):
            chamadas.append(("conecta", host, port))

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def login(self, u, s):
            chamadas.append(("login", u))

        def send_message(self, m, to_addrs=None):
            chamadas.append(("envia", tuple(to_addrs)))

    monkeypatch.setattr(email_ipdo.smtplib, "SMTP_SSL", SMTP)
    email_ipdo.enviar(CFG, email_ipdo.montar_mensagem(CFG, "A", "<p/>", "t"))
    assert chamadas == [("conecta", "smtp.zoho.com", 465), ("login", "robo@example.com"),
                        ("envia", ("a@x.com", "b@x.com"))]


def test_enviar_repete_uma_vez_em_erro_de_rede(monkeypatch):
    tentativas = []

    class SMTP:
        def __init__(self, *a, **k):
            tentativas.append(1)
            if len(tentativas) == 1:
                raise OSError("rede")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def login(self, *a):
            pass

        def send_message(self, *a, **k):
            pass

    monkeypatch.setattr(email_ipdo.smtplib, "SMTP_SSL", SMTP)
    monkeypatch.setattr(email_ipdo, "PAUSA", 0)
    email_ipdo.enviar(CFG, email_ipdo.montar_mensagem(CFG, "A", "<p/>", "t"))
    assert len(tentativas) == 2


def test_enviar_desiste_depois_de_duas_falhas(monkeypatch):
    class SMTP:
        def __init__(self, *a, **k):
            raise OSError("rede")

    monkeypatch.setattr(email_ipdo.smtplib, "SMTP_SSL", SMTP)
    monkeypatch.setattr(email_ipdo, "PAUSA", 0)
    with pytest.raises(OSError):
        email_ipdo.enviar(CFG, email_ipdo.montar_mensagem(CFG, "A", "<p/>", "t"))


def test_email_de_falha():
    assunto, html, texto = email_ipdo.montar_falha("19/10/2026", "PDF ainda não publicado (HTTP 404)")
    assert assunto == "IPDO · falha no envio de 19/10/2026"
    assert "PDF ainda não publicado (HTTP 404)" in html and "PDF ainda não publicado (HTTP 404)" in texto


def test_cabecalho_com_imagem_configurada():
    html = email_ipdo.montar_html(resultado(), "19/10/2026", cabecalho_url="https://exemplo.com/topo.jpg")
    assert "background-image:url('https://exemplo.com/topo.jpg')" in html
