"""Carga y validación de `config.yaml` con PyYAML + pydantic.

PyYAML convierte el texto YAML en dicts/listas de Python; pydantic valida esos
datos contra los modelos de abajo (tipos, rangos, valores permitidos) y entrega
objetos tipados. Si algo es inválido se lanza `ConfigError` con un mensaje claro.
"""

from __future__ import annotations

import re
from datetime import time
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

Productivity = Literal["productive", "neutral", "distracting"]
Action = Literal["notify", "warn", "block"]
Mode = Literal["soft", "strict"]
Weekday = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
WEEKDAYS: tuple[Weekday, ...] = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


class ConfigError(Exception):
    """Error al leer o validar el archivo de configuración."""


class StrictModel(BaseModel):
    # extra="forbid": una key desconocida (ej. un typo) es un error, no se ignora.
    # frozen=True: los objetos de config son inmutables después de cargarse.
    model_config = ConfigDict(extra="forbid", frozen=True)


class GeneralConfig(StrictModel):
    poll_interval_seconds: float = Field(default=1, gt=0)
    idle_threshold_seconds: float = Field(default=120, gt=0)
    data_retention_days: int = Field(default=90, ge=1)
    store_window_titles: bool = True
    observe_only: bool = True


class MatchConfig(StrictModel):
    """Matcher de una regla de clasificación. Debe tener exactamente una key."""

    process: str | None = None
    title_regex: str | None = None

    @field_validator("title_regex")
    @classmethod
    def _regex_compiles(cls, value: str | None) -> str | None:
        if value is not None:
            try:
                re.compile(value)
            except re.error as exc:
                raise ValueError(f"title_regex inválida {value!r}: {exc}") from exc
        return value

    @model_validator(mode="after")
    def _exactly_one(self) -> MatchConfig:
        given = [name for name in ("process", "title_regex") if getattr(self, name) is not None]
        if len(given) != 1:
            raise ValueError("match debe tener exactamente una key: 'process' o 'title_regex'")
        return self


class ClassificationRule(StrictModel):
    match: MatchConfig
    productivity: Productivity
    subcategory: str | None = None


class RuleTarget(StrictModel):
    """A qué aplica una regla. Si hay varias keys, deben cumplirse todas (AND)."""

    process: str | None = None
    subcategory: str | None = None
    productivity: Productivity | None = None

    @model_validator(mode="after")
    def _at_least_one(self) -> RuleTarget:
        if self.process is None and self.subcategory is None and self.productivity is None:
            raise ValueError(
                "target necesita al menos una key: process, subcategory o productivity"
            )
        return self


class DailyLimitRule(StrictModel):
    id: str
    type: Literal["daily_limit"]
    target: RuleTarget
    limit_minutes: float = Field(gt=0)
    action: Action = "notify"
    mode: Mode = "soft"
    # Solo para action=warn: segundos para salir de la app antes de bloquearla (FR-22).
    grace_seconds: float = Field(default=30, ge=0)


class ScheduleRule(StrictModel):
    id: str
    type: Literal["schedule"]
    days: list[Weekday] = Field(min_length=1)
    start: time
    end: time
    target: RuleTarget
    action: Action = "notify"
    mode: Mode = "soft"
    # Solo para action=warn: segundos para salir de la app antes de bloquearla (FR-22).
    grace_seconds: float = Field(default=30, ge=0)

    @field_validator("start", "end", mode="before")
    @classmethod
    def _reject_yaml_sexagesimal(cls, value: Any) -> Any:
        # YAML 1.1 lee `13:00` sin comillas como el entero 780 (base 60).
        if isinstance(value, int):
            raise ValueError('escribe la hora entre comillas, ej. "13:00"')
        return value


# `discriminator="type"`: pydantic mira el campo `type` para elegir el modelo correcto.
Rule = Annotated[DailyLimitRule | ScheduleRule, Field(discriminator="type")]


class PhoneDetectionConfig(StrictModel):
    enabled: bool = True
    fps: float = Field(default=2, gt=0, le=5)
    min_score: float = Field(default=0.4, ge=0, le=1)
    # Archivo dentro de attention.models_dir. Lite2 detecta teléfonos chicos mucho mejor que Lite0.
    model: str = "efficientdet_lite2.tflite"


class AttentionConfig(StrictModel):
    enabled: bool = True
    camera_index: int = Field(default=0, ge=0)
    process_fps: float = Field(default=8, gt=0, le=30)
    capture_width: int = Field(default=1280, ge=320)  # resolución pedida a la cámara
    frame_width: int = Field(default=640, ge=160)  # ancho al que se reduce para analizar la cara
    state_debounce_seconds: float = Field(default=2, ge=0)
    yaw_margin_deg: float = Field(default=8, ge=0)
    pitch_margin_deg: float = Field(default=6, ge=0)
    # Hysteresis: para *volver* a FOCUSED hay que estar este margen más adentro de la zona.
    hysteresis_deg: float = Field(default=3, ge=0)
    # Blendshapes eyeLookDown (0–1): ojos muy abajo con la cabeza al frente = LOOKING_DOWN.
    gaze_down_threshold: float = Field(default=0.6, ge=0, le=1)
    camera_retry_seconds: float = Field(default=10, gt=0)
    # Open question 3 del PRD: la cámara solo se usa durante focus sessions.
    only_during_focus: bool = True
    monitors: int = Field(default=1, ge=1, le=4)  # puntos de calibración por monitor
    models_dir: Path = Path("models")
    phone_detection: PhoneDetectionConfig = PhoneDetectionConfig()
    attention_exempt: list[MatchConfig] = []


AlertState = Literal["LOOKING_AWAY", "LOOKING_DOWN", "PHONE"]


class InterventionsConfig(StrictModel):
    grace_seconds: dict[AlertState, float] = {"LOOKING_AWAY": 10, "LOOKING_DOWN": 15, "PHONE": 3}
    escalation_seconds: list[float] = Field(default=[0, 10, 20], min_length=3, max_length=3)
    cooldown_seconds: float = Field(default=30, ge=0)
    sound: bool = True
    sound_name: str = "Glass"  # un sonido de /System/Library/Sounds

    @field_validator("escalation_seconds")
    @classmethod
    def _ascending(cls, value: list[float]) -> list[float]:
        if value != sorted(value) or value[0] < 0:
            raise ValueError("escalation_seconds debe ser creciente y >= 0, ej. [0, 10, 20]")
        return value

    @field_validator("grace_seconds")
    @classmethod
    def _all_states(cls, value: dict[str, float]) -> dict[str, float]:
        missing = {"LOOKING_AWAY", "LOOKING_DOWN", "PHONE"} - value.keys()
        if missing:
            raise ValueError(f"faltan grace_seconds para: {sorted(missing)}")
        return value


class FocusSessionConfig(StrictModel):
    default_minutes: int = Field(default=50, ge=1)
    break_minutes: int = Field(default=10, ge=0)
    block_distracting: bool = True
    mode: Mode = "soft"


class BlockingConfig(StrictModel):
    """M6: bloqueo de apps (FR-50) y fricción del modo strict (FR-23)."""

    # Strict: para desactivar algo hay que esperar `friction_seconds` y escribir esta frase.
    confirmation_phrase: str = Field(default="Elijo distraerme ahora", min_length=5)
    friction_seconds: int = Field(default=60, ge=0)
    # Estos procesos nunca se cierran a la fuerza (solo se ocultan): cerrar el browser
    # cerraría todas sus pestañas. Bloquear sitios puntuales es trabajo de M7.
    never_terminate: list[str] = [
        "Google Chrome",
        "Safari",
        "firefox",
        "Arc",
        "Brave Browser",
        "Microsoft Edge",
        "Opera",
    ]


DOMAIN_PATTERN = re.compile(
    r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$"
)


class SiteConfig(StrictModel):
    """Un sitio (dominio) con su categoría, para bloquearlo vía /etc/hosts (M7)."""

    domain: str
    productivity: Productivity = "distracting"
    subcategory: str | None = None
    always: bool = False  # bloqueado siempre mientras Nublock corre (salvo "Pausar todo")

    @field_validator("domain", mode="before")
    @classmethod
    def _valid_domain(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = value.strip().lower().removeprefix("https://").removeprefix("http://")
            value = value.split("/")[0].removeprefix("www.")
            if not DOMAIN_PATTERN.match(value):
                raise ValueError(f"dominio inválido: {value!r} (ej. youtube.com)")
        return value


class SiteBlockingConfig(StrictModel):
    enabled: bool = True
    # Además del dominio, se bloquean estos subdominios (en /etc/hosts no hay comodines).
    subdomains: list[str] = ["www", "m", "mobile"]


class DashboardConfig(StrictModel):
    enabled: bool = True
    port: int = Field(default=8765, ge=1024, le=65535)


class Config(StrictModel):
    general: GeneralConfig = GeneralConfig()
    classification_rules: list[ClassificationRule] = []
    rules: list[Rule] = []
    attention: AttentionConfig = AttentionConfig()
    interventions: InterventionsConfig = InterventionsConfig()
    focus_session: FocusSessionConfig = FocusSessionConfig()
    blocking: BlockingConfig = BlockingConfig()
    sites: list[SiteConfig] = []
    site_blocking: SiteBlockingConfig = SiteBlockingConfig()
    dashboard: DashboardConfig = DashboardConfig()

    @model_validator(mode="after")
    def _unique_rule_ids(self) -> Config:
        ids = [rule.id for rule in self.rules]
        duplicated = sorted({rule_id for rule_id in ids if ids.count(rule_id) > 1})
        if duplicated:
            raise ValueError(f"ids de reglas duplicados: {duplicated}")
        return self


def load_config(path: Path | None) -> Config:
    """Lee y valida un config YAML. Con `path=None` retorna la config por defecto."""
    if path is None:
        return Config()
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"no existe el archivo de config: {path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"YAML inválido en {path}: {exc}") from exc
    if raw is None:  # archivo vacío
        raw = {}
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: el nivel superior del YAML debe ser un mapping (key: value)")
    try:
        return Config.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(f"config inválida en {path}:\n{exc}") from exc
