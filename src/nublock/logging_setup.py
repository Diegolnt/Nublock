"""Configuración de `logging`: archivo rotativo + consola.

Regla de privacidad (NFR-09): nunca se loguean títulos de ventana.
"""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def setup_logging(log_dir: Path, verbose: bool = False) -> Path:
    """Configura el root logger y retorna la ruta del archivo de log."""
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "nublock.log"

    # maxBytes + backupCount: al llegar a 1 MB se rota a nublock.log.1 ... .3
    file_handler = RotatingFileHandler(
        log_file, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT))

    console_handler = logging.StreamHandler()  # escribe en stderr
    console_handler.setLevel(logging.INFO if verbose else logging.WARNING)
    console_handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.handlers.clear()  # evita handlers duplicados si se llama dos veces
    root.addHandler(file_handler)
    root.addHandler(console_handler)
    return log_file
