"""IPDO do ONS por e-mail — destaques do submercado Nordeste.

    python main.py                          # IPDO de ontem (envia mesmo que já tenha ido)
    python main.py --se-pendente            # cron: só se o dia ainda não foi enviado
    python main.py --se-pendente --alertar-falha   # última chance do dia: avisa se não deu
    python main.py --data 19-10-2026 --previa previa.html   # só gera o HTML, não envia
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from ipdo import config, execucao


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data", help="data do arquivo IPDO-DD-MM-AAAA (padrão: ontem)")
    p.add_argument("--se-pendente", action="store_true", help="não reenvia o dia que já foi enviado")
    p.add_argument("--alertar-falha", action="store_true", help="manda e-mail de falha se não conseguir enviar")
    p.add_argument("--previa", type=Path, help="grava o HTML neste arquivo e não envia nada")
    a = p.parse_args(argv)
    dia = datetime.strptime(a.data, "%d-%m-%Y").date() if a.data else date.today() - timedelta(days=1)
    cfg = config.carregar()
    print(f"--- {datetime.now():%Y-%m-%d %H:%M:%S} IPDO {dia:%d/%m/%Y}")
    return execucao.executar(cfg, dia, se_pendente=a.se_pendente, alertar_falha=a.alertar_falha, previa=a.previa)


if __name__ == "__main__":
    sys.exit(main())
