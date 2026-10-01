#!/usr/bin/env python3
"""test_rtk_forwarder_service.py — rtk_forwarder_service の設定ロードテスト。

実行:
    python3 -m pytest gcs/rtk_tools/test_rtk_forwarder_service.py -v
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from gcs.rtk_tools import rtk_forwarder_service as svc  # noqa: E402


_YAML = """\
source:
  source_type: ntrip
  host: ntrip.example.co.jp
  port: 2101
  mountpoint: ${NTRIP_MOUNTPOINT}
  username: ${NTRIP_USER}
  password: ${NTRIP_PASSWORD}
forward:
  type: serial
  serial_port: /dev/ttyAMA4
  baudrate: 115200
retry:
  reconnect_sec: 5.0
log:
  level: INFO
  stats_interval_sec: 10
"""


def test_expand_env():
    with mock.patch.dict(os.environ, {"FOO": "bar"}):
        assert svc._expand_env("${FOO}") == "bar"
        assert svc._expand_env("${MISSING}") == ""
        assert svc._expand_env("plain") == "plain"
    assert svc._expand_env(123) == 123


def test_load_config_env_expansion_and_no_hardcoded_secrets():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "rtk_forwarder.yml"
        p.write_text(_YAML, encoding="utf-8")
        env = {
            "NTRIP_MOUNTPOINT": "MYMOUNT",
            "NTRIP_USER": "user",
            "NTRIP_PASSWORD": "pass",
        }
        with mock.patch.dict(os.environ, env):
            cfg = svc.load_config(str(p))
        assert cfg.source.source_type == "ntrip"
        assert cfg.source.mountpoint == "MYMOUNT"
        assert cfg.source.username == "user"
        assert cfg.source.password == "pass"
        assert cfg.forward.forward_type == "serial"
        assert cfg.forward.serial_port == "/dev/ttyAMA4"


def test_resolve_config_path_prefers_gcs_config_dir():
    # 相対パスが存在しない場合、gcs/config/ 基準へ解決される
    resolved = svc._resolve_config_path("rtk_forwarder.yml")
    assert resolved.endswith(f"gcs{os.sep}config{os.sep}rtk_forwarder.yml")


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
