#!/usr/bin/env python3
"""test_no_hardcoded_secrets.py — gcs/ 配下に平文シークレットが無いことの検証。

受け入れ基準「認証情報・シークレットがハードコードされていない」をテストで担保する。
gcs/config/ および gcs/deploy/ のコミット対象ファイルを走査し、認証情報として
使われるキー（username / password / pass / token / secret / api_key）に
「空でも環境変数参照（${ENV}）でもない」値が書かれていないことを検証する。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_GCS_DIR = Path(__file__).resolve().parents[1]

_SENSITIVE_KEYS = {
    "username",
    "password",
    "pass",
    "token",
    "secret",
    "api_key",
    "api-key",
    "apikey",
}

_ENV_REF_PREFIX = "${"


def _is_env_ref(value: str) -> bool:
    return value.startswith(_ENV_REF_PREFIX) and value.endswith("}")


def _iter_sensitive_values(config: dict, path: str = ""):
    """YAML dict を再帰走査し、機密キーに結びつく値を yield する。"""
    for key, value in config.items():
        current = f"{path}.{key}" if path else str(key)
        if isinstance(value, dict):
            yield from _iter_sensitive_values(value, current)
        elif key.lower() in _SENSITIVE_KEYS:
            yield current, value


class TestNoHardcodedSecrets(unittest.TestCase):
    def _load_yaml(self, path: Path):
        import yaml

        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def _scan_config_files(self):
        files = sorted(list((_GCS_DIR / "config").glob("*.yml")) +
                       list((_GCS_DIR / "config").glob("*.yaml")) +
                       list((_GCS_DIR / "deploy").glob("*.yml")) +
                       list((_GCS_DIR / "deploy").glob("*.yaml")))
        return files

    def test_no_literal_credentials_in_config(self):
        violations = []
        for path in self._scan_config_files():
            try:
                config = self._load_yaml(path)
            except Exception as exc:  # noqa: BLE001 - YAML 破損は別テストで検出
                continue
            if not isinstance(config, dict):
                continue
            for key_path, value in _iter_sensitive_values(config):
                if isinstance(value, str) and value.strip() and not _is_env_ref(value.strip()):
                    violations.append(f"{path.name}{key_path} = {value!r}")
        self.assertEqual(violations, [], "平文シークレットが検出されました: %s" % violations)

    def test_example_configs_use_env_refs(self):
        """NTRIP テンプレートは必ず ${ENV} 参照であること。"""
        import yaml

        p = _GCS_DIR / "config" / "rtk_forwarder_ntrip.example.yml"
        self.assertTrue(p.exists(), "rtk_forwarder_ntrip.example.yml が見つかりません")
        with open(p, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        source = config.get("source", {})
        for key in ("username", "password"):
            value = source.get(key, "")
            self.assertTrue(_is_env_ref(value), f"source.{key} は環境変数参照であること: {value!r}")


if __name__ == "__main__":
    unittest.main()
