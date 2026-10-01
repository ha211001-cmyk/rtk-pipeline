"""gcs.rtk_tools.config_loader — 環境別 YAML の自動選択と DEFAULT_CONFIG 補完を統合したローダー。

Phase 0 統合計画（§4.4 / §7 Phase 4）に基づき、GCS-UmemotoLab の
``rtk_tools/config_loader.py``（優先順位解決）と EVK-F9P の
``gcs/config/loader.py``（DEFAULT_CONFIG の deep merge）を一本化する。

優先順位（高いほど優先）:
  1. CLI 明示パス（``resolve_config_path(path)`` / ``load_config(path)`` の引数）
  2. 環境変数 ``GCS_CONFIG_PATH``
  3. ``config/gcs.user.local.yml``（個人用上書き。gitignore 対象）
  4. ``config/gcs_local.yml``
  5. ``config/gcs.yml``

``load_config()`` は解決した YAML を ``DEFAULT_CONFIG`` に deep merge した結果を返す。
これにより接続設定（gcs.yml 系）と監視・判定基準（config.yaml 系）の既定値を
単一の dict で補完できる。
"""

from __future__ import annotations

import os
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Optional

# gcs/ ディレクトリ（本ファイル = gcs/rtk_tools/config_loader.py）
_GCS_DIR = Path(__file__).resolve().parents[1]
_CONFIG_DIR = _GCS_DIR / "config"
CONFIG_DIR = _CONFIG_DIR  # 公開エイリアス（gcs/config/）

# 環境別 YAML の自動選択順（末尾ほど優先度が低い）
_CONFIG_CANDIDATES = (
    "gcs.user.local.yml",
    "gcs_local.yml",
    "gcs.yml",
)


# ---------------------------------------------------------------------------
# 既定値（YAML が一部欠けていても補完される）
#   - MAVLink 接続（GCS-UmemotoLab gcs.yml 由来）
#   - 監視・判定（EVK-F9P gcs/config/config.yaml 由来）
# ---------------------------------------------------------------------------
DEFAULT_CONFIG: Dict[str, Any] = {
    # --- MAVLink 接続（MavlinkConnection が参照） ---
    "connection_type": "udp",          # "udp" または "serial"
    "udp_listen_port": 14550,
    "serial_port": None,               # serial 接続時（例: /dev/ttyACM0）
    "serial_baudrate": 115200,
    "drones": {},                      # {name: {system_id, endpoint, ...}}
    "ssh_tunnel": {},                  # UDP-over-SSH トンネル設定（任意）

    # --- 基地局 F9P ---
    "base_station": {
        "serial_port": None,
        "baudrate": 115200,
        "config_baudrate": 38400,
        "fixed_lat": 36.0751418,
        "fixed_lon": 136.2133477,
        "fixed_alt": 44.80,
        "save_to_flash": True,
        "setup": False,
    },
    # --- ローバー F9P ---
    "rover": {
        "serial_port": None,
        "baudrate": 115200,
        "mavlink_port": None,
        "mavlink_baud": 921600,
    },
    # --- ① コンフィグ自動診断の接続先 ---
    "forward": {
        "mode": "serial",
        "host": "127.0.0.1",
        "port": 5001,
        "baudrate": 115200,
    },
    # --- 観測パラメータ ---
    "monitor": {
        "duration_sec": 600.0,
        "sample_interval_sec": 1.0,
        "display_interval_sec": 5.0,
        "age_alert_threshold": 10.0,
        "age_warn_threshold": 5.0,
        "crc_alert_rate_pct": 5.0,
        "used_alert_ratio_pct": 50.0,
    },
    # --- PASS/FAIL 判定基準 ---
    "pass_criteria": {
        "fixed_rate_pct_min": 80.0,
        "max_float_transitions": 5,
        "ttff_sec_max": 120.0,
        "require_phase1": True,
    },
    # --- レポート出力 ---
    "report": {
        "output_dir": None,
        "json": True,
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


# ---------------------------------------------------------------------------
# メイン API
# ---------------------------------------------------------------------------
def resolve_config_path(explicit_path: Optional[str] = None) -> str:
    """設定ファイルのパスを解決する（環境別 YAML の自動選択）。

    Args:
        explicit_path: 明示的な YAML パス（相対パスは ``gcs/`` 基準）。

    Returns:
        解決した設定ファイルの絶対パス文字列。
    """
    if explicit_path:
        candidate = Path(explicit_path)
        if not candidate.is_absolute():
            candidate = _GCS_DIR / candidate
        if candidate.exists():
            return str(candidate)
        raise FileNotFoundError("設定ファイルが見つかりません: %s" % candidate)

    candidates = []
    env_path = os.environ.get("GCS_CONFIG_PATH")
    if env_path:
        candidates.append(Path(env_path))

    candidates.extend(_CONFIG_DIR / name for name in _CONFIG_CANDIDATES)

    for candidate in candidates:
        if candidate.exists():
            return str(candidate)

    raise FileNotFoundError(
        "利用可能な設定ファイルが見つかりません。config ディレクトリを確認してください。"
    )


def load_config(explicit_path: Optional[str] = None) -> Dict[str, Any]:
    """設定 YAML を解決して読み込み、DEFAULT_CONFIG で補完した dict を返す。

    Args:
        explicit_path: 明示的な YAML パス（省略時は自動解決）。

    Returns:
        DEFAULT_CONFIG に解決 YAML を deep merge した設定 dict。
    """
    path = resolve_config_path(explicit_path)
    config: Dict[str, Any] = deepcopy(DEFAULT_CONFIG)
    _deep_merge(config, _load_yaml(Path(path)))
    return config


# 後方互換エイリアス（旧 Um config_loader は resolve_config_path のみを提供）
def load(explicit_path: Optional[str] = None) -> Dict[str, Any]:
    """[deprecated] load_config() を使用してください。"""
    return load_config(explicit_path)


__all__ = [
    "DEFAULT_CONFIG",
    "CONFIG_DIR",
    "resolve_config_path",
    "load_config",
    "load",
]
