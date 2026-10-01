"""config/config.yml を読み込み、全ツール共通の設定を返す。

優先順位（高いほど優先）:
  1. CLI 明示パス
  2. GCS_CONFIG_PATH 環境変数
  3. config.local.yml（gitignore 対象、個人用上書き）
  4. config.win.yml または config.mac.yml（OS自動判定）
  5. config.yml（デフォルト）

各レイヤーは deep merge される。
"""

from pathlib import Path
import os
import platform
import sys


def load_config(explicit_path=None) -> dict:
    """config/config.yml を読み込み、全ツール共通の設定を返す。

    Args:
        explicit_path: 明示的なパス（省略時は自動検出）

    Returns:
        dict: {
            'connection': {...},
            'drones': {...},
            'f9p': {'serial_port': str, 'baudrate': int},
            'base_station': {...},
            'forward': {'host': str, 'port': int},
            'rtcm': {'enabled': bool, 'host': str, 'port': int},
            'log': {...},
            'retry': {...},
        }
    """
    try:
        import yaml
    except ImportError:
        raise ImportError(
            "PyYAML が必要です。 `uv add pyyaml` または "
            "`pip install pyyaml` でインストールしてください。"
        )

    repo_root = Path(__file__).resolve().parent.parent

    # 読み込む設定ファイルの優先順位リスト
    candidates = []

    # 1. 明示指定
    if explicit_path:
        p = Path(explicit_path)
        if not p.is_absolute():
            p = repo_root / p
        candidates.append(("explicit", p))
        # 明示指定の場合はその1ファイルのみ（戻り値は明示指定）
        for label, path in candidates:
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    return yaml.safe_load(f) or {}
        raise FileNotFoundError(f"設定ファイルが見つかりません: {explicit_path}")

    # 2. 環境変数 GCS_CONFIG_PATH
    env_path = os.environ.get("GCS_CONFIG_PATH")
    if env_path:
        p = Path(env_path)
        if not p.is_absolute():
            p = repo_root / p
        if p.exists():
            with open(p, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}

    # 3. デフォルト自動解決（マージ方式）
    merge_candidates = []

    # ベース
    merge_candidates.append(("default", repo_root / "config" / "config.yml"))

    # OS判定
    system = platform.system()
    if system == "Windows":
        merge_candidates.append(("os_override", repo_root / "config" / "config.win.yml"))
    elif system == "Darwin":
        merge_candidates.append(("os_override", repo_root / "config" / "config.mac.yml"))

    # 個人用上書き
    merge_candidates.append(("local", repo_root / "config" / "config.local.yml"))

    # マージ実行
    config: dict = {}
    for label, path in merge_candidates:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            if label == "default":
                config = data
            else:
                _deep_merge(config, data)

    if not config:
        raise FileNotFoundError(
            f"config/config.yml が見つかりません。"
            f" config/ ディレクトリを確認してください。"
        )

    return config


def _deep_merge(base: dict, override: dict) -> None:
    """override の値を base に深くマージする（破壊的）。"""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


# ============================================================================
# 後方互換エイリアス（旧関数名でも使えるようにする）
# ============================================================================
def resolve_config_path(explicit_path=None):
    """[deprecated] load_config() を使用してください。"""
    return load_config(explicit_path)


def load_hardware_config(path=None) -> dict:
    """[deprecated] load_config() を使用してください。"""
    return load_config(path)