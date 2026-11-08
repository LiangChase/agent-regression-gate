"""Layered configuration loading and validation.

Precedence is built-in defaults < YAML < environment < CLI overrides.
Secret values are never loaded into GateConfig; live mode only checks that the
provider's documented environment variable exists.
"""

from __future__ import annotations

import os
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit, urlunsplit

import yaml

from .errors import ConfigurationError


class _UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that fails instead of silently taking the last duplicate key."""


def _construct_unique_mapping(loader: _UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False):
    loader.flatten_mapping(node)
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as exc:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping", node.start_mark,
                "found an unhashable key", key_node.start_mark,
            ) from exc
        if duplicate:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping", node.start_mark,
                f"found duplicate key '{key}'", key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping
)


@dataclass(slots=True)
class SutConfig:
    base_url: str = "http://127.0.0.1:8000"
    start_mode: str = "external"
    health_path: str = "/health"
    request_timeout_seconds: float = 60.0


@dataclass(slots=True)
class RunConfig:
    cases_path: Path = Path("cases/airline")
    reports_dir: Path = Path("reports")
    baselines_dir: Path = Path("baselines")


@dataclass(slots=True)
class ModelConfig:
    execution_mode: str = "deterministic"
    provider: str = "deepseek"


@dataclass(slots=True)
class LoggingConfig:
    level: str = "INFO"
    format: str = "json"


@dataclass(slots=True)
class GateConfig:
    sut: SutConfig = field(default_factory=SutConfig)
    run: RunConfig = field(default_factory=RunConfig)
    model: ModelConfig = field(default_factory=ModelConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    config_path: Path | None = None

    def safe_dict(self) -> dict[str, Any]:
        """Return effective settings suitable for console output or diagnostics."""
        value = asdict(self)
        value["config_path"] = str(self.config_path) if self.config_path else None
        value["run"] = {key: str(item) for key, item in value["run"].items()}
        value["sut"]["base_url"] = safe_url(self.sut.base_url)
        return value


_ALLOWED_KEYS = {
    "sut": {"base_url", "start_mode", "health_path", "request_timeout_seconds"},
    "run": {"cases_path", "reports_dir", "baselines_dir"},
    "model": {"execution_mode", "provider"},
    "logging": {"level", "format"},
}

_ENV_KEYS = {
    "GATE_SUT_BASE_URL": ("sut", "base_url"),
    "GATE_SUT_START_MODE": ("sut", "start_mode"),
    "GATE_SUT_HEALTH_PATH": ("sut", "health_path"),
    "GATE_REQUEST_TIMEOUT_SECONDS": ("sut", "request_timeout_seconds"),
    "GATE_CASES_PATH": ("run", "cases_path"),
    "GATE_REPORTS_DIR": ("run", "reports_dir"),
    "GATE_BASELINES_DIR": ("run", "baselines_dir"),
    "GATE_MODEL_EXECUTION_MODE": ("model", "execution_mode"),
    "GATE_MODEL_PROVIDER": ("model", "provider"),
    "GATE_LOG_LEVEL": ("logging", "level"),
    "GATE_LOG_FORMAT": ("logging", "format"),
}


def safe_url(value: str) -> str:
    """Remove user info and query/fragment material from a URL for display."""
    try:
        parts = urlsplit(value)
        if not parts.scheme or not parts.netloc:
            return "[invalid-url]"
        hostname = parts.hostname or ""
        if parts.port:
            hostname = f"{hostname}:{parts.port}"
        return urlunsplit((parts.scheme, hostname, parts.path, "", ""))
    except (TypeError, ValueError):
        return "[invalid-url]"


def _mapping(value: Any, *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ConfigurationError(f"Configuration section '{label}' must be a mapping.")
    return value


def _validate_yaml_shape(raw: Any, path: Path) -> dict[str, dict[str, Any]]:
    if raw is None:
        raw = {}
    if not isinstance(raw, Mapping):
        raise ConfigurationError(f"Configuration file '{path}' must contain a YAML mapping.")
    result: dict[str, dict[str, Any]] = {}
    for section, fields in raw.items():
        if section not in _ALLOWED_KEYS:
            raise ConfigurationError(f"Unknown configuration section '{section}' in '{path}'.")
        section_values = dict(_mapping(fields, label=str(section)))
        unknown = set(section_values) - _ALLOWED_KEYS[section]
        if unknown:
            names = ", ".join(sorted(str(item) for item in unknown))
            raise ConfigurationError(f"Unknown setting(s) in '{section}': {names}.")
        result[section] = section_values
    return result


def _coerce(section: str, key: str, value: Any) -> Any:
    if section == "sut" and key == "request_timeout_seconds":
        try:
            result = float(value)
        except (TypeError, ValueError) as exc:
            raise ConfigurationError("GATE_REQUEST_TIMEOUT_SECONDS must be a number.") from exc
        if not math.isfinite(result) or result <= 0:
            raise ConfigurationError("SUT request timeout must be greater than zero.")
        return result
    if section == "run" and key in {"cases_path", "reports_dir", "baselines_dir"}:
        return Path(value)
    if not isinstance(value, str):
        if section == "sut" and key == "base_url":
            raise ConfigurationError("SUT base_url must be a URL string.")
        return str(value) if value is not None else ""
    return value.strip()


def load_config(
    config_path: str | Path | None = None,
    *,
    env: Mapping[str, str] | None = None,
    cli_overrides: Mapping[str, Mapping[str, Any]] | None = None,
    require_config_file: bool = True,
) -> GateConfig:
    """Load, layer, and validate configuration without retaining secret values."""
    environment = os.environ if env is None else env
    selected_path = config_path or environment.get("GATE_CONFIG") or "config/gate.yaml"
    path = Path(selected_path)
    if not path.is_file():
        if require_config_file:
            raise ConfigurationError(
                f"Config file '{path}' was not found. Copy config/gate.example.yaml to "
                "config/gate.yaml, or pass --config <path>."
            )
        raw: dict[str, dict[str, Any]] = {}
    else:
        try:
            raw_data = yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)
        except yaml.YAMLError as exc:
            # Do not include parser source snippets; they may contain a pasted secret.
            mark = getattr(exc, "problem_mark", None)
            location = f" at line {mark.line + 1}" if mark else ""
            raise ConfigurationError(f"Invalid YAML in '{path}'{location}.") from exc
        except OSError as exc:
            raise ConfigurationError(f"Cannot read config file '{path}'.") from exc
        raw = _validate_yaml_shape(raw_data, path)

    merged: dict[str, dict[str, Any]] = {
        "sut": asdict(SutConfig()),
        "run": {key: str(value) for key, value in asdict(RunConfig()).items()},
        "model": asdict(ModelConfig()),
        "logging": asdict(LoggingConfig()),
    }
    for section, values in raw.items():
        merged[section].update(values)
    for env_key, (section, key) in _ENV_KEYS.items():
        if env_key in environment:
            merged[section][key] = environment[env_key]
    if cli_overrides:
        for section, values in cli_overrides.items():
            if section not in _ALLOWED_KEYS:
                raise ConfigurationError(f"Unknown CLI override section '{section}'.")
            for key, value in values.items():
                if key not in _ALLOWED_KEYS[section]:
                    raise ConfigurationError(f"Unknown CLI override '{section}.{key}'.")
                if value is not None:
                    merged[section][key] = value

    typed: dict[str, dict[str, Any]] = {}
    for section, values in merged.items():
        typed[section] = {key: _coerce(section, key, value) for key, value in values.items()}

    result = GateConfig(
        sut=SutConfig(**typed["sut"]),
        run=RunConfig(**typed["run"]),
        model=ModelConfig(**typed["model"]),
        logging=LoggingConfig(**typed["logging"]),
        config_path=path.resolve() if path.is_file() else path,
    )
    validate_config(result, environment)
    return result


def validate_config(config: GateConfig, env: Mapping[str, str] | None = None) -> None:
    environment = os.environ if env is None else env
    if config.sut.start_mode not in {"external", "process", "compose"}:
        raise ConfigurationError("sut.start_mode must be external, process, or compose.")
    if not config.sut.health_path.startswith("/"):
        raise ConfigurationError("sut.health_path must start with '/'.")
    if not safe_url(config.sut.base_url).startswith(("http://", "https://")):
        raise ConfigurationError("sut.base_url must be an absolute HTTP(S) URL.")
    if config.model.execution_mode not in {"deterministic", "live"}:
        raise ConfigurationError("model.execution_mode must be deterministic or live.")
    if config.model.provider not in {"openai", "deepseek"}:
        raise ConfigurationError("model.provider must be openai or deepseek.")
    if config.logging.level.upper() not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ConfigurationError("logging.level must be DEBUG, INFO, WARNING, ERROR, or CRITICAL.")
    if config.logging.format not in {"json", "text"}:
        raise ConfigurationError("logging.format must be json or text.")

    if config.model.execution_mode == "live":
        required_key = "DEEPSEEK_API_KEY" if config.model.provider == "deepseek" else "OPENAI_API_KEY"
        if not environment.get(required_key):
            raise ConfigurationError(
                f"Live model mode requires environment variable {required_key}; its value is never "
                "read into the Gate configuration or printed."
            )
