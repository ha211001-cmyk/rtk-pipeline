#!/usr/bin/env python3
"""runner.py — Phase 3（RTK→EKF 取り込み・フェイルセーフ）ランナー（1 コマンド実行 / CLI）

F9P レジスタ golden（52eb5・F9pConfigGuard）と ArduPilot パラメータ golden
（本モジュール・ArduPilotParamGuard）を 1 コマンドで照合し、さらに RTK 喪失時挙動
（fix_type / EKF フラグの観測）を評価して PASS/FAIL の一括レポートを出力する。

接続:
  - F9P golden（52eb5）: DroneCAN Serial Forwarding の TCP（host + port）。
  - ArduPilot golden / RTK 観測: MAVLink（シリアル device または tcp:/udp:）。

使い方:
    # 実機（F9P は DroneCAN Serial Forwarding / FC は MAVLink シリアル）
    python3 gcs/ekf_failsafe/runner.py \
        --f9p-host 192.168.1.100 --f9p-port 5001 \
        --device /dev/ttyAMA0 --baud 921600

    # 実機なしの自己検証（合成データでフルパイプラインを検証 / 約4秒）
    python3 gcs/ekf_failsafe/runner.py --self-test
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# 実行位置に依存しない import
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from gcs.backend.f9p_configurator import F9pConfigGuard  # noqa: E402
from gcs.integration.sources import run_phase1_offline  # noqa: E402

from gcs.ekf_failsafe.param_guard import ArduPilotParamGuard  # noqa: E402
from gcs.ekf_failsafe.golden import synthetic_guard_result  # noqa: E402
from gcs.ekf_failsafe.checklist import (  # noqa: E402
    STATUS_PASS,
    Phase3Report,
    evaluate_f9p_golden,
    evaluate_ekf_sources,
    evaluate_failsafe,
    evaluate_rtk_loss_behavior,
)


DEFAULT_CONFIG: Dict[str, Any] = {
    "connection": {
        "device": None,             # MAVLink シリアルデバイス（例: /dev/ttyAMA0）
        "baud": 921600,             # MAVLink シリアルボーレート
        "mavlink": None,            # mavutil 接続文字列（tcp:/udp:）。device より優先
        "f9p_host": "192.168.1.100",  # F9P golden（DroneCAN Serial Forwarding）ホスト
        "f9p_port": 5001,           # F9P golden ポート
        "timeout": 3.0,
    },
    "auto_fix": False,
    "monitor": {
        "duration_sec": 30.0,       # RTK 喪失挙動の観測時間
        "sample_interval_sec": 1.0,
    },
    "criteria": {
        "max_rtk_dropouts": 2,
        "max_dropout_sec": 30.0,
    },
    "report": {"output_dir": None, "json": True},
}

# 自己検証（--self-test）用の合成シナリオ。FLOAT → FIXED → 一時喪失 → 復帰を再現する。
SELF_TEST_DURATION = 4.0
SELF_TEST_INTERVAL = 0.1
SELF_TEST_FIX_SCRIPT = [(0.0, 5), (0.3, 6), (1.0, 3), (1.5, 5), (1.7, 6)]
# EKF フラグ（位置・速度・姿勢すべて健全 = 0x037）
SELF_TEST_EKF_FLAGS = 0x001 | 0x002 | 0x004 | 0x010 | 0x020

DEFAULT_REPORT_DIR = Path(__file__).resolve().parent / "reports"


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> None:
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


def load_phase3_config(path: Optional[str] = None) -> Dict[str, Any]:
    """既定値 + 任意の YAML 上書きを読み込む（既存 gcs/config は改変しない）。"""
    config: Dict[str, Any] = deepcopy(DEFAULT_CONFIG)
    if path:
        try:
            import yaml  # noqa: PLC0415
        except ImportError as e:
            raise ImportError("PyYAML が必要です: pip install pyyaml") from e
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError("設定ファイルが見つかりません: %s" % p)
        with open(p, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        _deep_merge(config, data)
    return config


def _synthetic_fix_series(fix_script: List[tuple], duration: float,
                          ekf_flags: int = SELF_TEST_EKF_FLAGS) -> List[Dict[str, Any]]:
    """自己検証用の合成 fix_type 時系列（+ EKF フラグ）を生成する。"""
    series: List[Dict[str, Any]] = []
    t = 0.0
    step = 0.1
    cur = 0
    idx = 0
    while t <= duration:
        while idx < len(fix_script) and t >= fix_script[idx][0]:
            cur = fix_script[idx][1]
            idx += 1
        series.append({"t": t, "ts": "", "fix_type": cur, "ekf_flags": ekf_flags})
        t += step
    return series


class Phase3Runner:
    """F9P golden（52eb5）→ ArduPilot golden（EKF/FS）→ RTK 喪失挙動 を一括実行する。"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = deepcopy(DEFAULT_CONFIG)
        if config:
            _deep_merge(self.config, config)

    def _run_f9p_golden(self, auto_fix: bool) -> Any:
        conn = self.config["connection"]
        host = str(conn.get("f9p_host", "192.168.1.100"))
        port = int(conn.get("f9p_port", 5001))
        timeout = float(conn.get("timeout", 3.0))
        guard = F9pConfigGuard(host=host, port=port, timeout=timeout,
                               flash_wait_seconds=0)
        with contextlib.redirect_stdout(io.StringIO()):
            return evaluate_f9p_golden(guard.run_check_and_fix(fix=auto_fix))

    def _run_f9p_golden_offline(self) -> Any:
        guard = F9pConfigGuard(flash_wait_seconds=0)
        with contextlib.redirect_stdout(io.StringIO()):
            return evaluate_f9p_golden(run_phase1_offline(guard))

    def _run_ardupilot_golden(self, auto_fix: bool) -> Dict[str, Any]:
        conn = self.config["connection"]
        guard = ArduPilotParamGuard(
            device=conn.get("device"),
            baud=int(conn.get("baud", 921600)),
            connection_string=conn.get("mavlink"),
            timeout=float(conn.get("timeout", 3.0)),
        )
        with contextlib.redirect_stdout(io.StringIO()):
            return guard.run_check_and_fix(fix=auto_fix)

    def run(self, auto_fix: Optional[bool] = None,
            duration: Optional[float] = None,
            on_event: Optional[Callable[[Dict[str, Any]], None]] = None,
            offline: bool = False,
            fix_script: Optional[List[tuple]] = None) -> Phase3Report:
        if auto_fix is not None:
            self.config["auto_fix"] = bool(auto_fix)
        auto_fix = bool(self.config.get("auto_fix", False))

        conn = self.config["connection"]
        mon_cfg = self.config["monitor"]
        duration = float(duration if duration is not None else mon_cfg.get("duration_sec", 30.0))
        interval = float(mon_cfg.get("sample_interval_sec", 1.0))
        criteria = self.config["criteria"]

        # 1) F9P golden（52eb5）
        item_f9p = self._run_f9p_golden_offline() if offline else self._run_f9p_golden(auto_fix)

        # 2) ArduPilot golden（EKF ソース / フェイルセーフ）
        if offline:
            guard_result = synthetic_guard_result()
        else:
            guard_result = self._run_ardupilot_golden(auto_fix)
        item_ekf = evaluate_ekf_sources(guard_result)
        item_fs = evaluate_failsafe(guard_result)

        # 3) RTK 喪失時挙動
        if offline:
            series = _synthetic_fix_series(
                list(fix_script or SELF_TEST_FIX_SCRIPT), duration)
        else:
            guard = ArduPilotParamGuard(
                device=conn.get("device"),
                baud=int(conn.get("baud", 921600)),
                connection_string=conn.get("mavlink"),
                timeout=float(conn.get("timeout", 3.0)),
            )
            series = guard.observe(duration, interval, on_event)

        item_loss = evaluate_rtk_loss_behavior(series, item_fs.is_pass(), criteria)

        report = Phase3Report(
            [item_f9p, item_ekf, item_fs, item_loss],
            connection={"connection": conn.get("mavlink") or (
                "%s @ %d bps" % (conn.get("device"), conn.get("baud", 921600)))},
        )
        self._save_report(report, series, guard_result)
        return report

    def _save_report(self, report: Phase3Report, series: List[Dict[str, Any]],
                     guard_result: Dict[str, Any]) -> None:
        rep_cfg = self.config.get("report", {})
        if not rep_cfg.get("json", True):
            return
        out_dir = Path(rep_cfg.get("output_dir")) if rep_cfg.get("output_dir") else DEFAULT_REPORT_DIR
        out_dir = out_dir.resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        payload = report.to_dict()
        payload["fix_series"] = series
        payload["ardupilot_guard"] = guard_result
        path = out_dir / ("phase3_report_%s.json" % ts)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2, default=str)


# ---------------------------------------------------------------------------
# コマンドライン
# ---------------------------------------------------------------------------
def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Phase 3 飛行試験準備（RTK→EKF 取り込み・フェイルセーフ）の 1 コマンド照合",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--f9p-host", default=None, help="F9P golden 照合の TCP ホスト（既定: 192.168.1.100）")
    p.add_argument("--f9p-port", type=int, default=None, help="F9P golden 照合の TCP ポート（既定: 5001）")
    p.add_argument("--device", default=None, help="MAVLink シリアルデバイス（例: /dev/ttyAMA0）")
    p.add_argument("--baud", type=int, default=None, help="MAVLink シリアルボーレート（既定: 921600）")
    p.add_argument("--mavlink", default=None, help="MAVLink 接続文字列（tcp:host:port / udpin:...）")
    p.add_argument("--duration", type=float, default=None,
                   help="RTK 喪失挙動の観測時間[秒]（既定: 30.0）")
    p.add_argument("--auto-fix", action="store_true",
                   help="退行検知時に自動修正する（既定は照合のみ）")
    p.add_argument("--config", default=None, help="上書き設定の YAML パス")
    p.add_argument("--report-dir", default=None, help="JSON レポート出力先")
    p.add_argument("--self-test", action="store_true",
                   help="実機なしの自己検証（合成データでフルパイプラインを検証）")
    p.add_argument("--json", action="store_true", help="チェックリストの JSON も標準出力する")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    config = load_phase3_config(args.config)
    conn = config["connection"]
    if args.f9p_host:
        conn["f9p_host"] = args.f9p_host
    if args.f9p_port is not None:
        conn["f9p_port"] = args.f9p_port
    if args.device:
        conn["device"] = args.device
    if args.baud is not None:
        conn["baud"] = args.baud
    if args.mavlink:
        conn["mavlink"] = args.mavlink
    if args.report_dir:
        config["report"]["output_dir"] = args.report_dir

    duration_override = args.duration
    fix_script = None
    offline = bool(args.self_test)
    if offline:
        duration_override = args.duration if args.duration is not None else SELF_TEST_DURATION
        config["monitor"]["sample_interval_sec"] = SELF_TEST_INTERVAL
        fix_script = SELF_TEST_FIX_SCRIPT

    runner = Phase3Runner(config)

    def _print_progress(ev: Dict[str, Any]) -> None:
        if ev.get("type") == "progress":
            print("[観測 %.1f/%.1f 秒] fix_type=%s | EKF flags=%s"
                  % (ev.get("elapsed_sec", 0.0), ev.get("duration_sec", 0.0),
                     ev.get("fix_type", "-"), hex(ev.get("ekf_flags") or 0)))

    report = runner.run(
        auto_fix=args.auto_fix, duration=duration_override,
        on_event=_print_progress, offline=offline, fix_script=fix_script,
    )

    print()
    print(report.format_checklist())
    if args.json:
        print(report.to_json())
    return 0 if report.overall_status() == STATUS_PASS else 1


if __name__ == "__main__":
    sys.exit(main())
