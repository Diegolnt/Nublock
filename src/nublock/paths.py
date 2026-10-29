"""Rutas por defecto (config, base de datos, logs) según el OS, vía platformdirs."""

import os
from pathlib import Path

import platformdirs

APP_NAME = "nublock"


def default_config_path() -> Path:
    """macOS: ~/Library/Application Support/nublock/config.yaml"""
    return platformdirs.user_config_path(APP_NAME) / "config.yaml"


def default_db_path() -> Path:
    """macOS: ~/Library/Application Support/nublock/nublock.db"""
    return platformdirs.user_data_path(APP_NAME) / "nublock.db"


def default_log_dir() -> Path:
    """macOS: ~/Library/Logs/nublock"""
    return platformdirs.user_log_path(APP_NAME)


def default_calibration_path() -> Path:
    """macOS: ~/Library/Application Support/nublock/calibration.json (solo ángulos)."""
    return platformdirs.user_data_path(APP_NAME) / "calibration.json"


def default_app_path() -> Path:
    """La app de macOS. Si Nublock.app lanzó este proceso, es esa (variable NUBLOCK_APP);
    si no, ~/Applications/Nublock.app (visible en Spotlight y Launchpad)."""
    from_app = os.environ.get("NUBLOCK_APP")
    return Path(from_app) if from_app else Path.home() / "Applications" / "Nublock.app"


def legacy_app_path() -> Path:
    """Donde vivía Nublock.app antes de M8 (solo notificaciones); se migra al instalar."""
    return platformdirs.user_data_path(APP_NAME) / "Nublock.app"


def project_root() -> Path:
    """Raíz del repo (instalación editable: src/nublock/paths.py -> ../../)."""
    return Path(__file__).resolve().parents[2]


def resolve_models_dir(models_dir: Path) -> Path:
    """`attention.models_dir` sin depender del directorio actual.

    Nublock.app arranca el proceso desde tu home, no desde el repo: una ruta relativa como
    `models` se busca en el directorio actual, en la carpeta de datos y en la raíz del repo.
    """
    if models_dir.is_absolute():
        return models_dir
    bundled = os.environ.get("NUBLOCK_MODELS_DIR")  # la release trae los modelos dentro de la app
    if bundled and Path(bundled).is_dir():
        return Path(bundled)
    candidates = [
        Path.cwd() / models_dir,
        platformdirs.user_data_path(APP_NAME) / models_dir,
        project_root() / models_dir,
    ]
    return next((path for path in candidates if path.is_dir()), candidates[0])
