"""gcs.app.operations.util — 操作ハンドラが使うヘルパー。

- プロジェクトルート解決
- シリアルポート自動検出（macOS / Linux の一般的なデバイス glob）
- gcs/config/ 一元設定の読み込み（``gcs.config.loader.load_config`` を再利用）
- 相対パス解決（gcs/ 基準）
"""

from __future__ import annotations

import glob
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

_GCS_DIR = Path(__file__).resolve().parents[2]  # gcs/app/operations/ -> gcs/


def project_root() -> Path:
    """リポジトリルート（gcs/ の親）を返す。"""
    return _GCS_DIR.parent


def gcs_dir() -> Path:
    return _GCS_DIR


def resolve_gcs_path(path_text: str) -> str:
    """gcs/ 基準で相対パスを解決する（絶対パスはそのまま）。"""
    p = Path(path_text)
    if p.is_absolute():
        return str(p)
    return str(_GCS_DIR / p)


def detect_serial_port() -> Optional[str]:
    """F9P のシリアルポートを自動検出する（複数候補時は先頭を採用）。"""
    candidates: List[str] = []
    candidates += sorted(glob.glob("/dev/cu.usbmodem*"))    # macOS (cu.*)
    candidates += sorted(glob.glob("/dev/tty.usbmodem*"))   # macOS (tty.*)
    candidates += sorted(glob.glob("/dev/ttyACM*"))         # Linux USB CDC
    candidates += sorted(glob.glob("/dev/ttyUSB*"))         # Linux USB-serial
    if not candidates:
        return None
    return candidates[0]


def load_gcs_config() -> Dict[str, Any]:
    """gcs/config/ の一元設定（DEFAULT_CONFIG 補完済み）を読み込む。"""
    from gcs.config.loader import load_config  # noqa: PLC0415

    return load_config()


def load_yaml_file(path_text: str) -> Dict[str, Any]:
    """gcs/ 基準の YAML を読み込んで dict を返す。"""
    import yaml  # noqa: PLC0415

    path = resolve_gcs_path(path_text)
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError("YAML はマッピングである必要があります: %s" % path)
    return data


def load_json_file(path_text: str) -> Dict[str, Any]:
    """gcs/ 基準の JSON を読み込んで dict を返す。"""
    import json  # noqa: PLC0415

    path = resolve_gcs_path(path_text)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("JSON はマッピングである必要があります: %s" % path)
    return data


def ensure_log_dir(subdir: str = "logs") -> Path:
    """gcs/ 配下のログ出力ディレクトリを作成して返す。"""
    d = _GCS_DIR / subdir
    d.mkdir(parents=True, exist_ok=True)
    return d


__all__ = [
    "project_root",
    "gcs_dir",
    "resolve_gcs_path",
    "detect_serial_port",
    "load_gcs_config",
    "load_yaml_file",
    "load_json_file",
    "ensure_log_dir",
]
