#!/usr/bin/env python3
"""test_deploy.py — gcs/deploy の systemd テンプレート検証（実機・sudo 不要）。

インストールスクリプトが行うプレースホルダ置換（sed）を模した純関数で
テンプレートを展開し、生成されるユニットが有効な形になることを検証する。
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

_DEPLOY_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _DEPLOY_DIR.parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_PLACEHOLDER_RE = re.compile(r"@[A-Z_]+@")


def substitute(template: str, install_dir: str, gcs_user: str) -> str:
    """install スクリプトの sed 置換を模した純関数。"""
    return (
        template.replace("@INSTALL_DIR@", install_dir)
        .replace("@GCS_USER@", gcs_user)
    )


class TestServiceTemplates(unittest.TestCase):
    def test_templates_exist(self):
        for name in ("rtk-uart4-inject.service", "tcp2serial.service"):
            self.assertTrue((_DEPLOY_DIR / name).exists(), f"{name} が見つかりません")

    def test_templates_contain_placeholders(self):
        for name in ("rtk-uart4-inject.service", "tcp2serial.service"):
            text = (_DEPLOY_DIR / name).read_text(encoding="utf-8")
            self.assertIn("@INSTALL_DIR@", text, name)
            self.assertIn("@GCS_USER@", text, name)

    def test_substitution_removes_all_placeholders(self):
        for name in ("rtk-uart4-inject.service", "tcp2serial.service"):
            text = (_DEPLOY_DIR / name).read_text(encoding="utf-8")
            unit = substitute(text, "/opt/EVK-F9P", "pi")
            self.assertFalse(_PLACEHOLDER_RE.search(unit), f"{name} に未置換プレースホルダが残っています")

    def test_execstart_uses_module_form(self):
        unit = substitute(
            (_DEPLOY_DIR / "rtk-uart4-inject.service").read_text(encoding="utf-8"),
            "/opt/EVK-F9P", "pi",
        )
        self.assertIn("ExecStart=/opt/EVK-F9P/.venv/bin/python -m gcs.rtk_tools.rtk_forwarder_service", unit)
        self.assertIn("WorkingDirectory=/opt/EVK-F9P", unit)
        self.assertIn("User=pi", unit)

        unit2 = substitute(
            (_DEPLOY_DIR / "tcp2serial.service").read_text(encoding="utf-8"),
            "/opt/EVK-F9P", "pi",
        )
        self.assertIn("ExecStart=/opt/EVK-F9P/.venv/bin/python -m gcs.rtk_tools.tcp2serial", unit2)

    def test_unit_has_required_sections(self):
        for name in ("rtk-uart4-inject.service", "tcp2serial.service"):
            text = (_DEPLOY_DIR / name).read_text(encoding="utf-8")
            self.assertIn("[Unit]", text)
            self.assertIn("[Service]", text)
            self.assertIn("[Install]", text)
            self.assertIn("WantedBy=multi-user.target", text)


class TestInstallScripts(unittest.TestCase):
    def test_install_scripts_present(self):
        for name in (
            "install_rtk_uart4_service.sh",
            "install_tcp2serial_service.sh",
            "install_all_services.sh",
            "uninstall_rtk_uart4_service.sh",
            "uninstall_tcp2serial_service.sh",
            "setup_raspi.sh",
        ):
            self.assertTrue((_DEPLOY_DIR / name).exists(), f"{name} が見つかりません")

    def test_install_scripts_reference_correct_service(self):
        text = (_DEPLOY_DIR / "install_rtk_uart4_service.sh").read_text(encoding="utf-8")
        self.assertIn('SERVICE_NAME="rtk-uart4-inject.service"', text)
        text = (_DEPLOY_DIR / "install_tcp2serial_service.sh").read_text(encoding="utf-8")
        self.assertIn('SERVICE_NAME="tcp2serial.service"', text)


class TestNoSecretsInDeploy(unittest.TestCase):
    def test_no_literal_secrets(self):
        sensitive = re.compile(r"(password|passwd|secret|token|api[_-]?key)\s*[:=]\s*['\"]?[A-Za-z0-9]", re.IGNORECASE)
        for path in _DEPLOY_DIR.rglob("*"):
            if path.suffix not in (".service", ".conf", ".sh", ".yml", ".yaml", ".network", ".link"):
                continue
            if path.name in ("can0.network", "can0.link", "interfaces.d"):
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            self.assertIsNone(
                sensitive.search(text),
                f"{path.name} に平文シークレットらしき記述があります",
            )


if __name__ == "__main__":
    unittest.main()
