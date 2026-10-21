from datetime import date
from email import message_from_bytes, policy
from pathlib import Path

import pytest
import requests

from ipdo import execucao
from ipdo.config import Config

PDF = (Path(__file__).parent / "fixtures" / "IPDO-19-10-2026.pdf").read_bytes()
DIA = date(2026, 10, 19)


@pytest.fixture
def cfg(tmp_path):
    return Config(email_user="robo@example.com", email_password="x", smtp_host="h", smtp_port=465,
                  destinatarios=["a@x.com"], drive_webhook_url="https://drive.example/exec", pasta_estado=tmp_path)


@pytest.fixture
def enviados(monkeypatch):
    lista = []
    monkeypatch.setattr(execucao.email_ipdo, "enviar", lambda cfg, msg: lista.append(message_from_bytes(msg.as_bytes(), policy=policy.default)))
    return lista


@pytest.fixture
def drive(monkeypatch):
    lista = []
    monkeypatch.setattr(execucao, "salvar_no_drive", lambda cfg, pdf, dia: lista.append(dia) or True)
    return lista


def baixa(monkeypatch, resultado):
    def falso(dia):
        if isinstance(resultado, Exception):
            raise resultado
        return resultado
    monkeypatch.setattr(execucao, "baixar_pdf", falso)


def test_envia_com_pdf_guarda_no_drive_e_marca_o_dia(cfg, enviados, drive, monkeypatch):
    baixa(monkeypatch, PDF)
    assert execucao.executar(cfg, DIA) == 0
    assert len(enviados) == 1 and drive == [DIA]
    assert enviados[0]["Subject"].startswith("IPDO · operação de 18/10/2026")
    nomes = [p.get_filename() for p in enviados[0].walk() if p.get_filename()]
    assert "IPDO-19-10-2026.pdf" in nomes
    assert execucao.ja_enviado(cfg.pasta_estado, DIA)


def test_se_pendente_nao_reenvia_o_mesmo_dia(cfg, enviados, drive, monkeypatch):
    baixa(monkeypatch, PDF)
    execucao.executar(cfg, DIA)
    assert execucao.executar(cfg, DIA, se_pendente=True) == 0
    assert len(enviados) == 1


def test_sem_se_pendente_reenvia_quando_pedido_na_mao(cfg, enviados, drive, monkeypatch):
    baixa(monkeypatch, PDF)
    execucao.executar(cfg, DIA)
    execucao.executar(cfg, DIA)
    assert len(enviados) == 2


def test_pdf_nao_publicado_nao_envia_nem_marca(cfg, enviados, drive, monkeypatch):
    baixa(monkeypatch, execucao.PdfIndisponivel("PDF ainda não publicado (HTTP 404)"))
    assert execucao.executar(cfg, DIA) == 1
    assert enviados == [] and drive == [] and not execucao.ja_enviado(cfg.pasta_estado, DIA)


def test_pdf_nao_publicado_na_ultima_chance_manda_alerta(cfg, enviados, drive, monkeypatch):
    baixa(monkeypatch, execucao.PdfIndisponivel("PDF ainda não publicado (HTTP 404)"))
    assert execucao.executar(cfg, DIA, alertar_falha=True) == 1
    assert enviados[0]["Subject"] == "IPDO · falha no envio de 19/10/2026"


def test_falha_do_drive_nao_impede_o_email(cfg, enviados, monkeypatch):
    baixa(monkeypatch, PDF)
    monkeypatch.setattr(execucao, "salvar_no_drive", lambda *a: False)
    assert execucao.executar(cfg, DIA) == 0 and len(enviados) == 1


def test_falha_no_envio_nao_marca_para_a_segunda_chance_tentar(cfg, drive, monkeypatch):
    baixa(monkeypatch, PDF)

    def falha(*a):
        raise OSError("smtp fora")
    monkeypatch.setattr(execucao.email_ipdo, "enviar", falha)
    assert execucao.executar(cfg, DIA) == 1
    assert not execucao.ja_enviado(cfg.pasta_estado, DIA)


def test_pdf_ilegivel_ainda_envia_com_aviso(cfg, enviados, drive, monkeypatch):
    baixa(monkeypatch, b"%PDF-1.4 quebrado")
    assert execucao.executar(cfg, DIA) == 0
    assert "confira o PDF" in enviados[0]["Subject"]


def test_previa_grava_html_sem_enviar_nem_drive(cfg, enviados, drive, monkeypatch, tmp_path):
    baixa(monkeypatch, PDF)
    saida = tmp_path / "previa.html"
    assert execucao.executar(cfg, DIA, previa=saida) == 0
    assert enviados == [] and drive == [] and "2.062 MW" in saida.read_text(encoding="utf-8")
    assert not execucao.ja_enviado(cfg.pasta_estado, DIA)


# ── download ──────────────────────────────────────────────────────────────

class Resp:
    def __init__(self, status, conteudo=b""):
        self.status_code, self.content = status, conteudo


def test_baixar_monta_a_url_do_ons(monkeypatch):
    urls = []
    monkeypatch.setattr(execucao.requests, "get", lambda url, timeout: urls.append(url) or Resp(200, b"%PDF-1.4"))
    assert execucao.baixar_pdf(DIA) == b"%PDF-1.4"
    assert urls == ["https://www.ons.org.br/AcervoDigitalDocumentosEPublicacoes/IPDO-19-10-2026.pdf"]


def test_baixar_404_e_nao_publicado_sem_repetir(monkeypatch):
    chamadas = []
    monkeypatch.setattr(execucao.requests, "get", lambda url, timeout: chamadas.append(1) or Resp(404))
    with pytest.raises(execucao.PdfIndisponivel, match="404"):
        execucao.baixar_pdf(DIA)
    assert len(chamadas) == 1


def test_baixar_repete_em_erro_de_rede(monkeypatch):
    respostas = [requests.Timeout(), requests.ConnectionError(), Resp(200, b"%PDF-1.4")]

    def get(url, timeout):
        r = respostas.pop(0)
        if isinstance(r, Exception):
            raise r
        return r
    monkeypatch.setattr(execucao.requests, "get", get)
    monkeypatch.setattr(execucao, "PAUSA", 0)
    assert execucao.baixar_pdf(DIA) == b"%PDF-1.4"


def test_baixar_recusa_o_que_nao_e_pdf(monkeypatch):
    monkeypatch.setattr(execucao.requests, "get", lambda url, timeout: Resp(200, b"<html>manutencao</html>"))
    with pytest.raises(execucao.PdfIndisponivel):
        execucao.baixar_pdf(DIA)


def test_drive_manda_o_mesmo_payload_do_script_antigo(cfg, monkeypatch):
    enviados = []

    def post(url, json, timeout):
        enviados.append((url, json))
        return Resp(200)
    monkeypatch.setattr(execucao.requests, "post", post)
    assert execucao.salvar_no_drive(cfg, b"%PDF", DIA) is True
    url, corpo = enviados[0]
    assert url == "https://drive.example/exec"
    assert {k: corpo[k] for k in ("tipo", "ano", "mes", "nome_arquivo")} == {
        "tipo": "IPDO", "ano": "2026", "mes": "10", "nome_arquivo": "IPDO-19-10-2026.pdf"}


def test_drive_sem_url_ou_com_erro_nao_quebra(cfg, monkeypatch):
    def post(*a, **k):
        raise requests.ConnectionError()
    monkeypatch.setattr(execucao.requests, "post", post)
    assert execucao.salvar_no_drive(cfg, b"%PDF", DIA) is False
    cfg.drive_webhook_url = ""
    assert execucao.salvar_no_drive(cfg, b"%PDF", DIA) is False
