"""Leitura da seção "4 - Destaques da Operação" do IPDO (Informativo Preliminar Diário da Operação, ONS).

Como o PDF é montado (conferido em PDFs de maio a outubro de 2026):
- os destaques são texto corrido em **Courier New**, divididos em blocos "* TÍTULO" (Courier negrito);
- títulos de seção ("4 - Destaques…", "5 - Gerações…"), tabelas e rodapés são **Arial**.

Por isso lemos o PDF de dois jeitos e comparamos:
- pela fonte: só o texto em Courier entre os títulos "4 -" e "5 -" (as tabelas da seção 3, que o pypdf
  mistura no meio do texto, ficam de fora sozinhas);
- pelo texto: o texto inteiro da página, filtrando rodapés e linhas de tabela.
Se as duas leituras discordam, se falta um bloco esperado ou aparece um bloco novo, o resultado leva um
aviso — o e-mail sai assim mesmo, com o PDF anexo, mas nunca diz "Nada a relatar" sem o PDF dizer.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from io import BytesIO

from pypdf import PdfReader

TITULOS = (
    "Carga e produção – Submercado Nordeste",
    "Restrição de geração renovável – Submercado Nordeste",
    "Intercâmbio de energia – Submercado Nordeste",
    "Ocorrências",
    "Integração de novas instalações",
    "Informações adicionais",
)

# blocos "* TÍTULO" que o ONS sempre publica na seção 4 (comparados sem acento)
BLOCOS = {
    "CARGA E PRODUCAO": "CARGA E PRODUÇÃO DE ENERGIA POR SUBMERCADO",
    "TRANSFERENCIA": "TRANSFERÊNCIA DE ENERGIA ENTRE SUBMERCADOS",
    "RESTRICAO": "RESTRIÇÃO DE GERAÇÃO RENOVÁVEL",
    "INTERCAMBIO INTERNACIONAL": "INTERCÂMBIO INTERNACIONAL",
    "OCORRENCIA": "OCORRÊNCIAS",
    "INTEGRACAO": "INTEGRAÇÃO DE NOVAS INSTALAÇÕES",
    "INFORMACOES ADICIONAIS": "INFORMAÇÕES ADICIONAIS",
}

_RODAPE = re.compile(r"^(OPERADOR NACIONAL DO SISTEMA|INFORMATIVO PRELIMINAR DA OPERA)", re.IGNORECASE)
_TABELA = re.compile(r"^(SIN|[\d.,%\s+-]+|Energia Armazenada.*|Capacidade Máxima.*|Armazenamento ao final.*"
                     r"|Variação (em relação|acumulada).*)$", re.IGNORECASE)
_SUBMERCADO = re.compile(r"^Submercado\s+([^:]+?)\s*:\s*(.*)$", re.IGNORECASE)
_FRASE = re.compile(r"(?<=\.)\s+(?=[A-ZÀ-ÖØ-Ý])")  # inclui "À" ("Às 17h03 ocorreu…")


@dataclass
class Item:
    rotulo: str
    frases: list[str]


@dataclass
class Secao:
    titulo: str
    itens: list[Item]          # vazio = o PDF diz "Nada a relatar"
    faltou: bool = False       # o bloco não foi encontrado no PDF (vai com aviso)


@dataclass
class Resultado:
    data_operacao: str | None
    secoes: list[Secao]
    avisos: list[str] = field(default_factory=list)


def sem_acento(txt: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", txt) if unicodedata.category(c) != "Mn").upper()


def limpar(txt: str) -> str:
    """Tira os espaços que o PDF põe antes da pontuação e no meio de horários ('06 h59' → '06h59')."""
    txt = txt.replace("\xad", "").replace("​", "").replace("﻿", "")
    txt = re.sub(r"\s+", " ", txt)
    txt = re.sub(r" +([.,;:])", r"\1", txt)
    txt = re.sub(r"(\d) h(\d)", r"\1h\2", txt)
    txt = txt.replace("Centro -Oeste", "Centro-Oeste")
    return txt.strip()


# ── leitura do PDF ────────────────────────────────────────────────────────

def texto_do_pdf(pdf_bytes: bytes) -> str:
    return "\n".join((p.extract_text() or "") for p in PdfReader(BytesIO(pdf_bytes)).pages)


def texto_courier(pdf_bytes: bytes) -> str:
    """Só o texto em Courier entre os títulos (em Arial) '4 - Destaques da Operação' e '5 - …'."""
    partes, estado = [], {"dentro": False, "achou": False}

    def visitar(texto, _cm, _tm, fonte, _tamanho):
        nome = (fonte or {}).get("/BaseFont", "")
        if "Courier" in nome:
            if estado["dentro"]:
                partes.append(texto)
        elif re.match(r"\s*4\s*-\s*Destaques", texto, re.IGNORECASE):
            estado["dentro"] = estado["achou"] = True
        elif estado["dentro"] and re.match(r"\s*5\s*-\s*\S", texto):
            estado["dentro"] = False

    for pagina in PdfReader(BytesIO(pdf_bytes)).pages:
        pagina.extract_text(visitor_text=visitar)
        partes.append("\n")
    return "4 - Destaques da Operação\n" + "".join(partes) if estado["achou"] else ""


def data_da_operacao(texto: str) -> str | None:
    """O arquivo IPDO-19-10 pode trazer a operação do dia 18/10: a data certa é a do cabeçalho."""
    m = re.search(r"OPERA[ÇC][ÃA]O DO DIA\s*-\s*(\d{2}/\d{2}/\d{4})", texto, re.IGNORECASE)
    return m.group(1) if m else None


def blocos_destaques(texto: str) -> dict[str, list[str]]:
    """{'CARGA E PRODUÇÃO DE ENERGIA POR SUBMERCADO': [linhas], ...} da seção 4; {} se ela não existe."""
    m = re.search(r"^\s*4\s*-\s*Destaques da Opera[cç][aã]o\s*$", texto, re.IGNORECASE | re.MULTILINE)
    if not m:
        return {}
    resto = texto[m.end():]
    fim = re.search(r"^\s*5\s*-\s*\S", resto, re.MULTILINE)
    blocos, atual = {}, None
    for linha in (resto[:fim.start()] if fim else resto).splitlines():
        linha = linha.strip()
        if not linha or _RODAPE.match(linha) or _TABELA.match(linha):
            continue
        if linha.startswith("*"):
            atual = re.sub(r"\s+", " ", linha.lstrip("* ")).strip().upper()
            blocos[atual] = []
        elif atual:
            blocos[atual].append(linha)
    return blocos


# ── montagem das seções do e-mail ─────────────────────────────────────────

def frases(linhas: list[str]) -> list[str]:
    """Junta as linhas quebradas pelo PDF e separa em frases; 'Nada a relatar' vira lista vazia."""
    lista = [f.strip() for f in _FRASE.split(limpar(" ".join(linhas))) if len(f.strip()) > 3]
    return [] if all(re.fullmatch(r"nada a relatar\.?", f, re.IGNORECASE) for f in lista) else lista


def por_submercado(linhas: list[str], nome: str = "Nordeste") -> list[str]:
    """Linhas depois de 'Submercado Nordeste :' até o próximo 'Submercado X :'."""
    saida, dentro = [], False
    for linha in linhas:
        m = _SUBMERCADO.match(linha)
        if m:
            dentro = sem_acento(m.group(1)).startswith(sem_acento(nome))
            if dentro and m.group(2):
                saida.append(m.group(2))
        elif dentro:
            saida.append(linha)
    return saida


def _eh_rotulo(linha: str) -> bool:
    """Linha de rótulo acima do texto da ocorrência ('Ocorrência no Rio de Janeiro', 'Maranhão')."""
    if re.search(r"[\d.,:;()]", linha):
        return False
    return sem_acento(linha).startswith("OCORRENCIA") or len(linha) <= 30


def ocorrencias(linhas: list[str]) -> list[Item]:
    """Uma ocorrência por rótulo: 'Rede de Operação · Maranhão' + as frases do texto."""
    itens, rede, local, corpo = [], "", "", []
    anterior_fechou = True  # a linha anterior terminou frase (ou é o começo do bloco)

    def fecha():
        texto = frases(corpo)
        if texto:
            itens.append(Item(" · ".join(x for x in (rede, local) if x), texto))
        corpo.clear()

    for linha in linhas:
        m = re.match(r"^Ocorr[eê]ncias? na (Rede de .+)$", linha, re.IGNORECASE)
        if m and anterior_fechou:
            fecha()
            rede, local = m.group(1), ""
        elif anterior_fechou and _eh_rotulo(linha):
            fecha()
            local = linha
        else:
            corpo.append(linha)
            anterior_fechou = linha.rstrip().endswith(".")
            continue
        anterior_fechou = True
    fecha()
    return itens


def _bloco(blocos, chave):
    return next((v for k, v in blocos.items() if sem_acento(k).startswith(chave)), None)


def montar_secoes(blocos: dict[str, list[str]]) -> list[Secao]:
    def simples(titulo, linhas):
        if linhas is None:
            return Secao(titulo, [], faltou=True)
        lista = frases(linhas)
        return Secao(titulo, [Item("", lista)] if lista else [])

    carga, restricao = _bloco(blocos, "CARGA E PRODUCAO"), _bloco(blocos, "RESTRICAO")
    transf, ocorr = _bloco(blocos, "TRANSFERENCIA"), _bloco(blocos, "OCORRENCIA")
    intercambio = None if transf is None else [
        f for f in frases(transf) if re.search(r"submercado\s+Nordeste", f, re.IGNORECASE)]
    return [
        simples(TITULOS[0], None if carga is None else por_submercado(carga)),
        simples(TITULOS[1], None if restricao is None else por_submercado(restricao)),
        Secao(TITULOS[2], [], faltou=True) if intercambio is None
        else Secao(TITULOS[2], [Item("", intercambio)] if intercambio else []),
        Secao(TITULOS[3], [], faltou=True) if ocorr is None else Secao(TITULOS[3], ocorrencias(ocorr)),
        simples(TITULOS[4], _bloco(blocos, "INTEGRACAO")),
        simples(TITULOS[5], _bloco(blocos, "INFORMACOES ADICIONAIS")),
    ]


def _vazias() -> list[Secao]:
    return [Secao(t, [], faltou=True) for t in TITULOS]


def analisar(texto_fonte: str, texto_simples: str) -> Resultado:
    """Compara as duas leituras e devolve as seções + os avisos para o e-mail."""
    avisos = []
    data = data_da_operacao(texto_simples) or data_da_operacao(texto_fonte)
    if not data:
        avisos.append("Data da operação não encontrada no cabeçalho do PDF.")
    pela_fonte, pelo_texto = blocos_destaques(texto_fonte), blocos_destaques(texto_simples)
    if not pela_fonte and not pelo_texto:
        avisos.append("A seção \"4 - Destaques da Operação\" não foi encontrada no PDF — confira o PDF anexo.")
        return Resultado(data, _vazias(), avisos)
    if not pela_fonte:
        avisos.append("A leitura pela fonte do PDF falhou; os destaques vieram só do texto — confira o PDF anexo.")
    blocos = pela_fonte or pelo_texto

    achados = {chave for chave in BLOCOS for k in blocos if sem_acento(k).startswith(chave)}
    for chave, nome in BLOCOS.items():
        if chave not in achados:
            avisos.append(f"O bloco \"* {nome}\" não está no PDF — o formato do IPDO pode ter mudado.")
    for k in blocos:
        if not any(sem_acento(k).startswith(chave) for chave in BLOCOS):
            avisos.append(f"Bloco novo no PDF: \"* {k}\" — não entra no e-mail, veja no PDF anexo.")

    secoes = montar_secoes(blocos)
    if pela_fonte and pelo_texto:
        for minha, outra in zip(secoes, montar_secoes(pelo_texto)):
            if minha.itens != outra.itens:
                avisos.append(f"{minha.titulo}: as duas leituras do PDF não bateram — confira no PDF anexo.")
    return Resultado(data, secoes, avisos)


def extrair(pdf_bytes: bytes) -> Resultado:
    """Nunca levanta exceção: PDF ilegível vira um resultado com aviso (o e-mail sai com o PDF anexo)."""
    try:
        simples = texto_do_pdf(pdf_bytes)
    except Exception as erro:  # noqa: BLE001 — qualquer falha do pypdf vira aviso no e-mail
        return Resultado(None, _vazias(), [f"Não foi possível ler o PDF ({erro.__class__.__name__}: {erro})."])
    try:
        fonte = texto_courier(pdf_bytes)
    except Exception:  # noqa: BLE001
        fonte = ""
    return analisar(fonte, simples)
