#!/usr/bin/env python3
"""test_config_loader.py — gcs.rtk_tools.config_loader のユニットテスト（実機不要）。

実行:
    python3 -m unittest gcs.rtk_tools.test_config_loader -v
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from gcs.rtk_tools import config_loader  # noqa: E402
from gcs.rtk_tools.config_loader import (  # noqa: E402
    DEFAULT_CONFIG,
    load_config,
    resolve_config_path,
)


class TestResolveConfigPath(unittest.TestCase):
    def test_candidates_order(self):
        """環境別 YAML の自動選択順が期待どおりであること。"""
        self.assertEqual(
            config_loader._CONFIG_CANDIDATES,
            ("gcs.user.local.yml", "gcs_local.yml", "gcs.yml"),
        )

    def test_explicit_path(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "custom.yml"
            p.write_text("connection_type: serial\n", encoding="utf-8")
            self.assertEqual(resolve_config_path(str(p)), str(p))

    def test_explicit_path_missing_raises(self):
        with self.assertRaises(FileNotFoundError):
            resolve_config_path("definitely_missing.yml")

    def test_env_path_takes_priority(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "env.yml"
            p.write_text("connection_type: udp\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {"GCS_CONFIG_PATH": str(p)}):
                self.assertEqual(resolve_config_path(), str(p))

    def test_priority_user_local_over_local_over_default(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d)
            (cfg / "gcs.yml").write_text("connection_type: serial\n", encoding="utf-8")
            (cfg / "gcs_local.yml").write_text("connection_type: udp\n", encoding="utf-8")
            (cfg / "gcs.user.local.yml").write_text(
                "connection_type: serial\nudp_listen_port: 19999\n", encoding="utf-8")

            with mock.patch.object(config_loader, "_CONFIG_DIR", cfg):
                self.assertEqual(resolve_config_path(), str(cfg / "gcs.user.local.yml"))

            # user.local を消すと gcs_local.yml が選ばれる
            (cfg / "gcs.user.local.yml").unlink()
            with mock.patch.object(config_loader, "_CONFIG_DIR", cfg):
                self.assertEqual(resolve_config_path(), str(cfg / "gcs_local.yml"))

            # gcs_local.yml も消すと gcs.yml が選ばれる
            (cfg / "gcs_local.yml").unlink()
            with mock.patch.object(config_loader, "_CONFIG_DIR", cfg):
                self.assertEqual(resolve_config_path(), str(cfg / "gcs.yml"))

    def test_no_candidate_raises(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(config_loader, "_CONFIG_DIR", Path(d)):
                with self.assertRaises(FileNotFoundError):
                    resolve_config_path()


class TestLoadConfig(unittest.TestCase):
    def test_defaults_preserved(self):
        """解決した YAML が DEFAULT_CONFIG を破壊しないこと（deep merge 補完）。"""
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "gcs.yml"
            p.write_text("connection_type: serial\n", encoding="utf-8")
            cfg = load_config(str(p))
            # 接続設定（YAML 由来）
            self.assertEqual(cfg["connection_type"], "serial")
            # 監視・判定の既定値（DEFAULT_CONFIG 由来）が補完される
            self.assertEqual(cfg["monitor"]["duration_sec"], 600.0)
            self.assertEqual(cfg["pass_criteria"]["fixed_rate_pct_min"], 80.0)
            self.assertEqual(cfg["base_station"]["baudrate"], 115200)

    def test_nested_override_is_deep_merged(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "gcs.yml"
            p.write_text(
                "connection_type: udp\n"
                "monitor:\n"
                "  duration_sec: 30.0\n",
                encoding="utf-8",
            )
            cfg = load_config(str(p))
            self.assertEqual(cfg["monitor"]["duration_sec"], 30.0)
            # 同階層の他の既定値は維持される
            self.assertEqual(cfg["monitor"]["age_alert_threshold"], 10.0)

    def test_repo_local_yml(self):
        """実リポジトリの gcs_local.yml が優先解決されること。"""
        cfg = load_config()
        self.assertEqual(cfg["connection_type"], "udp")


class TestDefaultConfigShape(unittest.TestCase):
    def test_required_keys(self):
        for key in ("connection_type", "drones", "base_station", "rover",
                    "forward", "monitor", "pass_criteria", "report"):
            self.assertIn(key, DEFAULT_CONFIG)


if __name__ == "__main__":
    unittest.main(verbosity=2)
