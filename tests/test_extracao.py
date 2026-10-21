from functools import lru_cache
from pathlib import Path

import pytest

from ipdo import extracao

FIX = Path(__file__).parent / "fixtures"
PDFS = sorted(FIX.glob("IPDO-*.pdf"))


def ler(nome):
    return (FIX / nome).read_bytes()


@lru_cache(maxsize=None)
def extraido(nome):
    """Cada PDF real é lido uma vez só (ler os 11 PDFs pelos dois métodos custa ~4 s cada)."""
    return extracao.extrair(ler(nome))


def secao(resultado, prefixo):
    return next(s for s in resultado.secoes if s.titulo.startswith(prefixo))


def tudo(s):
    return " ".join(f for item in s.itens for f in [item.rotulo, *item.frases])


# ── amostra real (maio a outubro de 2026) ──────────────────────────────────

def test_amostra_tem_os_11_pdfs():
    assert len(PDFS) == 11


@pytest.mark.parametrize("pdf", PDFS, ids=lambda p: p.stem)
def test_todo_pdf_da_amostra_sai_sem_aviso(pdf):
    r = extraido(pdf.name)
    assert r.avisos == []
    assert r.data_operacao is not None
    assert [s.titulo for s in r.secoes] == list(extracao.TITULOS)


@pytest.mark.parametrize("pdf", PDFS, ids=lambda p: p.stem)
def test_todo_pdf_da_amostra_tem_restricao_do_nordeste(pdf):
    s = secao(extraido(pdf.name), "Restrição")
    assert s.itens and "Valor máximo:" in tudo(s) and "MW" in tudo(s)


def test_data_vem_do_cabecalho_e_nao_do_nome_do_arquivo():
    assert extraido("IPDO-19-10-2026.pdf").data_operacao == "18/10/2026"
    assert extraido("IPDO-18-05-2026.pdf").data_operacao == "18/05/2026"


def test_restricao_19_10():
    s = secao(extraido("IPDO-19-10-2026.pdf"), "Restrição")
    assert s.itens[0].frases == [
        "Valor máximo: 2.062 MW.",
        "Período: Das 07h00 às 22h54.",
        "Motivos: Controle de inequação regional e fluxo sistêmico de operação normal e controle de frequência.",
    ]


def test_restricao_nao_pega_outro_submercado():
    s = secao(extraido("IPDO-19-10-2026.pdf"), "Restrição")
    assert "2.403" not in tudo(s) and "50 MW" not in tudo(s)  # Sudeste e Sul


def test_carga_e_intercambio_19_10():
    r = extraido("IPDO-19-10-2026.pdf")
    assert secao(r, "Carga").itens[0].frases == [
        "A geração hidráulica foi inferior ao programado, no período de ponta de carga, devido à "
        "indisponibilidade de unidades geradoras no complexo de Paulo Afonso."]
    assert secao(r, "Intercâmbio").itens[0].frases == [
        "O intercâmbio do submercado Nordeste foi inferior ao programado devido à geração eólica "
        "inferior ao previsto neste submercado."]


def test_ocorrencia_com_rede_e_estado_19_10():
    s = secao(extraido("IPDO-19-10-2026.pdf"), "Ocorrências")
    assert len(s.itens) == 1
    item = s.itens[0]
    assert item.rotulo == "Rede de Operação · Maranhão"
    assert item.frases[0] == "Interrupção de carga: 480 MW."
    assert any("SE São Luís II" in f and "17h03" in f for f in item.frases)
    assert item.frases[-1] == "A normalização da carga foi realizada das 17h37 às 18h30."


def test_ocorrencia_sem_rotulo_11_06():
    s = secao(extraido("IPDO-11-06-2026.pdf"), "Ocorrências")
    assert len(s.itens) == 1 and s.itens[0].rotulo == ""
    assert "Consequência: interrupção de 180 MW da Neoenergia Coelba, no sul do estado da Bahia." in s.itens[0].frases


def test_ocorrencia_com_local_29_07():
    s = secao(extraido("IPDO-29-07-2026.pdf"), "Ocorrências")
    assert s.itens[0].rotulo == "Ocorrência no Rio de Janeiro"
    assert "SE Grajaú" in tudo(s) and "17h35" in tudo(s)


def test_integracao_15_10():
    s = secao(extraido("IPDO-15-10-2026.pdf"), "Integração")
    assert "Sete Pontes" in tudo(s) and "Relevância Operativa:" in tudo(s)


def test_nada_a_relatar_vira_secao_vazia():
    r = extraido("IPDO-17-07-2026.pdf")
    assert secao(r, "Intercâmbio").itens == []
    assert secao(r, "Ocorrências").itens == []


# ── formato que muda: nunca "Nada a relatar" em silêncio ───────────────────

def _texto(*blocos, cabecalho=True):
    partes = ["INFORMATIVO PRELIMINAR DA OPERAÇÃO DO DIA - 18/10/2026"] if cabecalho else []
    partes += ["4 - Destaques da Operação"]
    for titulo, linhas in blocos:
        partes += [f"* {titulo}", *linhas]
    partes += ["5 - Gerações Térmicas"]
    return "\n".join(partes)


COMPLETO = [
    ("CARGA E PRODUÇÃO DE ENERGIA POR SUBMERCADO", ["Submercado Nordeste :", "Carga inferior ao previsto ."]),
    ("TRANSFERÊNCIA DE ENERGIA ENTRE SUBMERCADOS", ["Nada a relatar ."]),
    ("RESTRIÇÃO DE GERAÇÃO RENOVÁVEL", ["Submercado Nordeste :", "Valor máximo : 10 MW ."]),
    ("INTERCÂMBIO INTERNACIONAL", ["Nada a relatar ."]),
    ("OCORRÊNCIAS", ["Nada a relatar ."]),
    ("INTEGRAÇÃO DE NOVAS INSTALAÇÕES", ["Nada a relatar ."]),
    ("INFORMAÇÕES ADICIONAIS", ["Nada a relatar ."]),
]


def test_texto_completo_sai_sem_aviso():
    r = extracao.analisar(_texto(*COMPLETO), _texto(*COMPLETO))
    assert r.avisos == [] and secao(r, "Carga").itens[0].frases == ["Carga inferior ao previsto."]


def test_bloco_que_sumiu_gera_aviso():
    sem_ocorrencias = [b for b in COMPLETO if b[0] != "OCORRÊNCIAS"]
    r = extracao.analisar(_texto(*sem_ocorrencias), _texto(*sem_ocorrencias))
    assert any("OCORRÊNCIAS" in a for a in r.avisos)
    assert secao(r, "Ocorrências").itens == [] and secao(r, "Ocorrências").faltou


def test_bloco_novo_gera_aviso():
    com_novo = COMPLETO + [("ALERTA DE CONTINGÊNCIA", ["Algo novo ."])]
    r = extracao.analisar(_texto(*com_novo), _texto(*com_novo))
    assert any("ALERTA DE CONTINGÊNCIA" in a for a in r.avisos)


def test_metodos_que_discordam_geram_aviso():
    outro = [(t, ["Submercado Nordeste :", "Outra coisa ."] if t.startswith("CARGA") else l) for t, l in COMPLETO]
    r = extracao.analisar(_texto(*COMPLETO), _texto(*outro))
    assert any("Carga" in a and "confira" in a.lower() for a in r.avisos)


def test_sem_secao_4_pela_fonte_usa_o_texto_e_avisa():
    r = extracao.analisar("", _texto(*COMPLETO))
    assert r.avisos and secao(r, "Carga").itens[0].frases == ["Carga inferior ao previsto."]


def test_sem_secao_4_em_nenhum_metodo():
    r = extracao.analisar("", "outro documento qualquer")
    assert r.avisos and all(s.faltou for s in r.secoes)


def test_sem_data_no_cabecalho_avisa():
    r = extracao.analisar(_texto(*COMPLETO, cabecalho=False), _texto(*COMPLETO, cabecalho=False))
    assert r.data_operacao is None and any("data" in a.lower() for a in r.avisos)


def test_pdf_invalido_nao_quebra():
    r = extracao.extrair(b"isto nao e um pdf")
    assert r.avisos and all(s.faltou for s in r.secoes)


def test_limpar():
    assert extracao.limpar("Das 06 h59 às 13 h11 .") == "Das 06h59 às 13h11."
    assert extracao.limpar("Sudeste/Centro -Oeste :") == "Sudeste/Centro-Oeste:"
