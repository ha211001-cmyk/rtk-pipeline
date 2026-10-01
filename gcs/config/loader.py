#!/usr/bin/env python3
"""gcs/config/loader.py — Item 7 一元設定（gcs/config/）のローダー

統合テストランナー（gcs/integration/runner.py）が参照する一元設定を読み込む。

優先順位（高いほど優先）:
  1. CLI 明示パス（``load_config(path)`` の引数）
  2. 環境変数 ``GCS_CONFIG_PATH``
  3. ``config.local.yaml``（gitignore 対象・個人用上書き）
  4. ``config.yaml``（デフォルト）

各レイヤーは deep merge される。さらに ``DEFAULT_CONFIG`` を土台にするため、
``config.yaml`` にキーが存在しない場合も KeyError にならず既定値が返る。

既存の ``archive/base_station_verify/rtcm_compare/config_loader.py`` は改変せず、
本モジュールは gcs/config/ 専用のローダーとして新規実装する。
"""

from __future__ import annotations

import os
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Optional

_CONFIG_DIR = Path(__file__).resolve().parent


# ---------------------------------------------------------------------------
# 既定値（config.yaml / config.local.yaml が一部欠けていても補完される）
# ---------------------------------------------------------------------------
DEFAULT_CONFIG: Dict[str, Any] = {
    "base_station": {
        "serial_port": None,        # 省略時は自動検出（例: /dev/ttyACM2, /dev/cu.usbmodemXXXX）
        "baudrate": 115200,         # RTCM 読み取り用ボーレート
        "config_baudrate": 38400,   # 基地局設定（TMODE3 等）時のボーレート
        "fixed_lat": 36.0751418,    # 基準座標（福井大学）
        "fixed_lon": 136.2133477,
        "fixed_alt": 44.80,         # 楕円体高 HAE [m]
        "save_to_flash": True,      # Flash 保存（再起動後も維持）
        "setup": False,             # ランナー起動時に基地局を設定するか
    },
    "rover": {
        "serial_port": None,        # 省略時は自動検出
        "baudrate": 115200,
        "mavlink_port": None,       # Pixhawk 経由も併用する場合のみ（最小構成では不要）
        "mavlink_baud": 921600,
    },
    "forward": {                    # ① コンフィグ自動診断の接続先
        "mode": "serial",           # "serial" または "tcp"（DroneCAN Serial Forwarding）
        "host": "127.0.0.1",
        "port": 5001,
        "baudrate": 115200,
    },
    "monitor": {
        "duration_sec": 600.0,          # 観測時間 [秒]
        "sample_interval_sec": 1.0,     # fix_type サンプリング間隔 [秒]
        "display_interval_sec": 5.0,    # 進捗表示間隔 [秒]
        "age_alert_threshold": 10.0,    # RTK age アラート閾値 [秒]
        "age_warn_threshold": 5.0,      # RTK age 警告閾値 [秒]
        "crc_alert_rate_pct": 5.0,      # CRC エラー率アラート閾値 [%]
        "used_alert_ratio_pct": 50.0,   # msgUsed=使用済み 比率の下限 [%]
    },
    "pass_criteria": {
        "fixed_rate_pct_min": 80.0,     # FIXED 維持率の下限 [%]
        "max_float_transitions": 5,     # FLOAT 遷移回数の上限
        "ttff_sec_max": 120.0,          # TTFF の上限 [秒]
        "require_phase1": True,         # ① が FAIL なら全体も FAIL にするか
    },
    "report": {
        "output_dir": None,             # 省略時: gcs/integration/reports
        "json": True,                   # JSON レポートを出力するか
    },
}


# ---------------------------------------------------------------------------
# ユーティリティ
# ---------------------------------------------------------------------------
def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> None:
    """override の値を base に深くマージする（破壊的）。"""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


def _load_yaml(path: Path) -> Dict[str, Any]:
    try:
        import yaml  # noqa: PLC0415
    except ImportError as e:
        raise ImportError(
            "PyYAML が必要です。 `pip install pyyaml` でインストールしてください。"
        ) from e
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError("設定ファイルはマッピング（辞書）である必要があります: %s" % path)
    return data


def _resolve(path_text: str, base_dir: Path) -> Path:
    p = Path(path_text)
    return p if p.is_absolute() else base_dir / p


# ---------------------------------------------------------------------------
# メイン API
# ---------------------------------------------------------------------------
def load_config(explicit_path: Optional[str] = None) -> Dict[str, Any]:
    """Item 7 一元設定を読み込み、既定値で補完した dict を返す。

    Args:
        explicit_path: 明示的な YAML パス（省略時は自動解決）。

    Returns:
        dict: DEFAULT_CONFIG に config.yaml / config.local.yaml 等を
            deep merge した設定。
    """
    config: Dict[str, Any] = deepcopy(DEFAULT_CONFIG)

    # 1. CLI 明示パス
    if explicit_path:
        p = _resolve(explicit_path, _CONFIG_DIR)
        if not p.exists():
            raise FileNotFoundError("設定ファイルが見つかりません: %s" % p)
        _deep_merge(config, _load_yaml(p))
        return config

    # 2. 環境変数 GCS_CONFIG_PATH（既存 config_loader と同じ変数名）
    env_path = os.environ.get("GCS_CONFIG_PATH")
    if env_path:
        p = _resolve(env_path, _CONFIG_DIR)
        if p.exists():
            _deep_merge(config, _load_yaml(p))
            return config

    # 3. デフォルト + 個人用上書き
    default_path = _CONFIG_DIR / "config.yaml"
    if default_path.exists():
        _deep_merge(config, _load_yaml(default_path))
    local_path = _CONFIG_DIR / "config.local.yaml"
    if local_path.exists():
        _deep_merge(config, _load_yaml(local_path))

    return config


# 後方互換エイリアス
def load(explicit_path: Optional[str] = None) -> Dict[str, Any]:
    """[deprecated] load_config() を使用してください。"""
    return load_config(explicit_path)


__all__ = ["DEFAULT_CONFIG", "load_config", "load"]
