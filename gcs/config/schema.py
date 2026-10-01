#!/usr/bin/env python3
"""gcs/config/schema.py — 環境別 YAML 設定のスキーマ検証。

統合後の gcs/ が読み込む 3 種類の設定（接続設定・RTCM 転送設定・TCP→シリアル
橋渡し設定）に対して、型・必須キー・値域を検証し、人間が読めるエラー文字列の
リストを返します。エラーが 1 件も無ければ「有効」です。

使い方（実機不要・単体テスト可能）:

    from gcs.config.schema import validate_gcs_config

    errors = validate_gcs_config({"connection_type": "udp", "udp_listen_port": 14550})
    if errors:
        for e in errors:
            print(e)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_CONFIG_DIR = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# 定数
# ---------------------------------------------------------------------------
_CONNECTION_TYPES = ("udp", "serial")
_FORWARD_MODES = ("serial", "tcp")
_FORWARDER_SOURCE_TYPES = ("tcp", "ntrip", "serial")
_FORWARDER_FORWARD_TYPES = ("udp", "serial")

_INT_MAX = 65535


# ---------------------------------------------------------------------------
# ユーティリティ
# ---------------------------------------------------------------------------
def _err(errors: List[str], path: str, message: str) -> None:
    errors.append(f"{path}: {message}")


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_float(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_env_ref(value: Any) -> bool:
    """${ENV_VAR} 形式の環境変数参照か（認証情報・実行時解決を許可）。"""
    import re as _re

    return isinstance(value, str) and bool(_re.fullmatch(r"\$\{[A-Za-z_][A-Za-z0-9_]*\}", value))


def _check_port(errors: List[str], path: str, value: Any, required: bool = False) -> None:
    if value is None:
        if required:
            _err(errors, path, "must be an integer port (1..65535)")
        return
    if _is_env_ref(value):
        return
    if not _is_int(value) or not (1 <= value <= _INT_MAX):
        _err(errors, path, f"must be an integer port (1..65535), got {value!r}")


def _check_number(
    errors: List[str],
    path: str,
    value: Any,
    *,
    minimum: Optional[float] = None,
    required: bool = False,
) -> None:
    if value is None:
        if required:
            _err(errors, path, "is required")
        return
    if _is_env_ref(value):
        return
    if not _is_float(value):
        _err(errors, path, f"must be a number, got {value!r}")
        return
    if minimum is not None and value < minimum:
        _err(errors, path, f"must be >= {minimum}, got {value!r}")


def _check_bool(errors: List[str], path: str, value: Any, required: bool = False) -> None:
    if value is None:
        if required:
            _err(errors, path, "is required")
        return
    if not isinstance(value, bool):
        _err(errors, path, f"must be a boolean, got {value!r}")


def _check_str(errors: List[str], path: str, value: Any, *, required: bool = False) -> None:
    if value is None:
        if required:
            _err(errors, path, "is required")
        return
    if not isinstance(value, str):
        _err(errors, path, f"must be a string, got {value!r}")


def _check_choice(
    errors: List[str],
    path: str,
    value: Any,
    choices: Tuple[str, ...],
    required: bool = True,
) -> None:
    if value is None:
        if required:
            _err(errors, path, f"is required (one of {list(choices)})")
        return
    if value not in choices:
        _err(errors, path, f"must be one of {list(choices)}, got {value!r}")


def _check_mapping(
    errors: List[str],
    path: str,
    value: Any,
    required: bool = False,
) -> bool:
    if value is None:
        if required:
            _err(errors, path, "is required")
        return False
    if not isinstance(value, dict):
        _err(errors, path, f"must be a mapping, got {value!r}")
        return False
    return True


# ---------------------------------------------------------------------------
# 接続設定（gcs.yml 系 / gcs.rtk_tools.config_loader）
# ---------------------------------------------------------------------------
def validate_gcs_config(config: Any) -> List[str]:
    """MAVLink 接続 + 監視・判定の統合設定（gcs.yml 系）を検証する。

    Returns:
        list[str]: エラーメッセージ一覧（空なら有効）。
    """
    errors: List[str] = []
    if not _check_mapping(errors, "config", config, required=True):
        return errors

    _check_choice(errors, "connection_type", config.get("connection_type"), _CONNECTION_TYPES)
    _check_port(errors, "udp_listen_port", config.get("udp_listen_port"))
    _check_str(errors, "serial_port", config.get("serial_port"))
    _check_number(errors, "serial_baudrate", config.get("serial_baudrate"), minimum=1)

    drones = config.get("drones")
    if drones is not None:
        if not isinstance(drones, dict):
            _err(errors, "drones", f"must be a mapping, got {drones!r}")
        else:
            for drone_name, drone_cfg in drones.items():
                if not _check_mapping(errors, f"drones.{drone_name}", drone_cfg, required=True):
                    continue
                _check_number(errors, f"drones.{drone_name}.system_id", drone_cfg.get("system_id"), minimum=1)
                _check_str(errors, f"drones.{drone_name}.endpoint", drone_cfg.get("endpoint"))
                _check_str(errors, f"drones.{drone_name}.name", drone_cfg.get("name"))

    _validate_serial_node(errors, "base_station", config.get("base_station"))
    _validate_rover(errors, "rover", config.get("rover"))

    forward = config.get("forward")
    if forward is not None and _check_mapping(errors, "forward", forward):
        _check_choice(errors, "forward.mode", forward.get("mode"), _FORWARD_MODES)
        _check_str(errors, "forward.host", forward.get("host"))
        _check_port(errors, "forward.port", forward.get("port"))
        _check_number(errors, "forward.baudrate", forward.get("baudrate"), minimum=1)

    _validate_monitor(errors, "monitor", config.get("monitor"))
    _validate_pass_criteria(errors, "pass_criteria", config.get("pass_criteria"))

    report = config.get("report")
    if report is not None and _check_mapping(errors, "report", report):
        _check_str(errors, "report.output_dir", report.get("output_dir"))
        _check_bool(errors, "report.json", report.get("json"))

    return errors


def _validate_serial_node(errors: List[str], path: str, node: Any) -> None:
    if node is None:
        return
    if not _check_mapping(errors, path, node):
        return
    _check_str(errors, f"{path}.serial_port", node.get("serial_port"))
    _check_number(errors, f"{path}.baudrate", node.get("baudrate"), minimum=1)
    _check_number(errors, f"{path}.config_baudrate", node.get("config_baudrate"), minimum=1)
    _check_number(errors, f"{path}.fixed_lat", node.get("fixed_lat"), minimum=-90)
    _check_number(errors, f"{path}.fixed_lon", node.get("fixed_lon"), minimum=-180)
    _check_number(errors, f"{path}.fixed_alt", node.get("fixed_alt"))
    _check_bool(errors, f"{path}.save_to_flash", node.get("save_to_flash"))
    _check_bool(errors, f"{path}.setup", node.get("setup"))


def _validate_rover(errors: List[str], path: str, node: Any) -> None:
    if node is None:
        return
    if not _check_mapping(errors, path, node):
        return
    _check_str(errors, f"{path}.serial_port", node.get("serial_port"))
    _check_number(errors, f"{path}.baudrate", node.get("baudrate"), minimum=1)
    _check_str(errors, f"{path}.mavlink_port", node.get("mavlink_port"))
    _check_number(errors, f"{path}.mavlink_baud", node.get("mavlink_baud"), minimum=1)


def _validate_monitor(errors: List[str], path: str, node: Any) -> None:
    if node is None:
        return
    if not _check_mapping(errors, path, node):
        return
    _check_number(errors, f"{path}.duration_sec", node.get("duration_sec"), minimum=0)
    _check_number(errors, f"{path}.sample_interval_sec", node.get("sample_interval_sec"), minimum=0)
    _check_number(errors, f"{path}.display_interval_sec", node.get("display_interval_sec"), minimum=0)
    _check_number(errors, f"{path}.age_alert_threshold", node.get("age_alert_threshold"), minimum=0)
    _check_number(errors, f"{path}.age_warn_threshold", node.get("age_warn_threshold"), minimum=0)
    _check_number(errors, f"{path}.crc_alert_rate_pct", node.get("crc_alert_rate_pct"), minimum=0)
    _check_number(errors, f"{path}.used_alert_ratio_pct", node.get("used_alert_ratio_pct"), minimum=0)


def _validate_pass_criteria(errors: List[str], path: str, node: Any) -> None:
    if node is None:
        return
    if not _check_mapping(errors, path, node):
        return
    _check_number(errors, f"{path}.fixed_rate_pct_min", node.get("fixed_rate_pct_min"), minimum=0)
    _check_number(errors, f"{path}.max_float_transitions", node.get("max_float_transitions"), minimum=0)
    _check_number(errors, f"{path}.ttff_sec_max", node.get("ttff_sec_max"), minimum=0)
    _check_bool(errors, f"{path}.require_phase1", node.get("require_phase1"))


# ---------------------------------------------------------------------------
# RTCM 転送設定（rtk_forwarder.yml）
# ---------------------------------------------------------------------------
def validate_rtk_forwarder_config(config: Any) -> List[str]:
    """RTCM 転送サービス（rtk_forwarder_service）の設定を検証する。"""
    errors: List[str] = []
    if not _check_mapping(errors, "config", config, required=True):
        return errors

    source = config.get("source")
    if _check_mapping(errors, "source", source, required=True):
        _check_choice(errors, "source.source_type", source.get("source_type"), _FORWARDER_SOURCE_TYPES)
        _check_str(errors, "source.host", source.get("host"))
        _check_port(errors, "source.port", source.get("port"))
        _check_str(errors, "source.mountpoint", source.get("mountpoint"))
        _check_str(errors, "source.user_agent", source.get("user_agent"))
        _check_str(errors, "source.username", source.get("username"))
        _check_str(errors, "source.password", source.get("password"))
        _check_str(errors, "source.serial_port", source.get("serial_port"))
        _check_number(errors, "source.baudrate", source.get("baudrate"), minimum=1)
        _check_number(errors, "source.timeout_sec", source.get("timeout_sec"), minimum=0)

    forward = config.get("forward")
    if _check_mapping(errors, "forward", forward, required=True):
        _check_choice(errors, "forward.type", forward.get("type"), _FORWARDER_FORWARD_TYPES)
        _check_str(errors, "forward.host", forward.get("host"))
        _check_port(errors, "forward.port", forward.get("port"))
        _check_str(errors, "forward.serial_port", forward.get("serial_port"))
        _check_number(errors, "forward.baudrate", forward.get("baudrate"), minimum=1)

    retry = config.get("retry")
    if retry is not None and _check_mapping(errors, "retry", retry):
        _check_number(errors, "retry.reconnect_sec", retry.get("reconnect_sec"), minimum=0)

    log = config.get("log")
    if log is not None and _check_mapping(errors, "log", log):
        _check_str(errors, "log.level", log.get("level"))
        _check_number(errors, "log.stats_interval_sec", log.get("stats_interval_sec"), minimum=1)

    return errors


# ---------------------------------------------------------------------------
# TCP→シリアル橋渡し設定（tcp2serial.yml）
# ---------------------------------------------------------------------------
def validate_tcp2serial_config(config: Any) -> List[str]:
    """TCP→シリアル橋渡し（tcp2serial）の設定を検証する。"""
    errors: List[str] = []
    if not _check_mapping(errors, "config", config, required=True):
        return errors

    _check_str(errors, "bind_host", config.get("bind_host"), required=True)
    _check_port(errors, "bind_port", config.get("bind_port"), required=True)
    _check_str(errors, "serial_device", config.get("serial_device"), required=True)
    _check_number(errors, "baudrate", config.get("baudrate"), minimum=1)
    _check_number(errors, "health_timeout_sec", config.get("health_timeout_sec"), minimum=0)
    _check_number(errors, "tcp_timeout_sec", config.get("tcp_timeout_sec"), minimum=0)
    _check_number(errors, "serial_timeout_sec", config.get("serial_timeout_sec"), minimum=0)
    _check_number(errors, "stats_interval_sec", config.get("stats_interval_sec"), minimum=0)

    return errors


# ---------------------------------------------------------------------------
# ファイル読み込み + 検証
# ---------------------------------------------------------------------------
def load_yaml(path: Path) -> Dict[str, Any]:
    try:
        import yaml  # noqa: PLC0415
    except ImportError as e:
        raise ImportError("PyYAML が必要です。 `pip install pyyaml` でインストールしてください。") from e
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"設定ファイルはマッピング（辞書）である必要があります: {path}")
    return data


_VALIDATORS = {
    "gcs": validate_gcs_config,
    "rtk_forwarder": validate_rtk_forwarder_config,
    "tcp2serial": validate_tcp2serial_config,
}


def validate_config_file(path: str, kind: str) -> Tuple[Dict[str, Any], List[str]]:
    """YAML ファイルを読み込み、種類に応じて検証する。

    Args:
        path: YAML ファイルパス。
        kind: "gcs" / "rtk_forwarder" / "tcp2serial"。

    Returns:
        (読み込んだ設定 dict, エラー文字列のリスト)。
    """
    if kind not in _VALIDATORS:
        raise ValueError(f"unknown kind: {kind} (one of {list(_VALIDATORS)})")
    config = load_yaml(Path(path))
    return config, _VALIDATORS[kind](config)


def validate_bundled_configs() -> Dict[str, Dict[str, Any]]:
    """リポジトリ同梱の設定（例・デフォルト）を一括検証する（セルフチェック用）。

    Returns:
        {filename: {"errors": [...], "path": str}}。検証に失敗したファイルのみ
        非空の errors を持つ。
    """
    results: Dict[str, Dict[str, Any]] = {}
    targets = [
        ("gcs.yml", "gcs"),
        ("gcs_local.yml", "gcs"),
        ("gcs_multidrone_example.yml", "gcs"),
        ("rtk_forwarder.yml", "rtk_forwarder"),
        ("rtk_forwarder_ntrip.example.yml", "rtk_forwarder"),
        ("tcp2serial.yml", "tcp2serial"),
    ]
    for filename, kind in targets:
        path = _CONFIG_DIR / filename
        if not path.exists():
            continue
        try:
            _, errors = validate_config_file(str(path), kind)
        except Exception as exc:  # noqa: BLE001 - 検証失敗を集約して返す
            errors = [f"failed to load/validate: {exc}"]
        results[filename] = {"errors": errors, "path": str(path)}
    return results


__all__ = [
    "validate_gcs_config",
    "validate_rtk_forwarder_config",
    "validate_tcp2serial_config",
    "validate_config_file",
    "validate_bundled_configs",
    "load_yaml",
]


