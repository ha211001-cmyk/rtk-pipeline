#!/usr/bin/env python3
"""runner.py — Phase 3 飛行前セルフテスト ランナー（1 コマンド実行 / CLI）

静的照合（Item 2 golden 差分）と動的健全性（Item 1 FIXED 率・Item 3 RTCM CRC/age・
基地局レート）を 1 コマンドで走らせ、PASS/FAIL の一括レポート（飛行前チェックリスト）
を出力する。

接続は 5100f で TCP 化済みのため、シリアルポートではなく **Wi-Fi の IP アドレス + TCP
ポート**（DroneCAN Serial Forwarding の単一エンドポイント）に統一する。

使い方:
    # 実機（機体 Wi-Fi IP + ポートへ接続）
    python3 gcs/preflight/runner.py --host 192.168.1.100 --port 5001

    # 実機なしの自己検証（合成データでフルパイプラインを検証）
    python3 gcs/preflight/runner.py --self-test
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
import threading
import time
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# 実行位置に依存しない import
_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT,):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from gcs.backend.f9p_configurator import F9pConfigGuard  # noqa: E402
from gcs.fix_metrics import compute_metrics, fix_name  # noqa: E402
from gcs.rtcm_monitor import CorrectionMonitor  # noqa: E402
from gcs.integration.sources import (  # noqa: E402
    run_phase1_offline,
    SyntheticRoverSource,
)

from gcs.preflight.checklist import (  # noqa: E402
    STATUS_PASS,
    PreflightReport,
    evaluate_item1,
    evaluate_item2,
    evaluate_item3,
    evaluate_base_rate,
    utc_now_iso,
)
from gcs.preflight.session import TcpSession  # noqa: E402


DEFAULT_CONFIG: Dict[str, Any] = {
    "connection": {"host": "192.168.1.100", "port": 5001, "timeout": 3.0},
    "item2": {"auto_fix": False},
    "monitor": {
        "duration_sec": 60.0,
        "sample_interval_sec": 1.0,
        "age_alert_threshold": 10.0,
        "age_warn_threshold": 5.0,
        "crc_alert_rate_pct": 5.0,
        "used_alert_ratio_pct": 50.0,
    },
    "criteria": {
        "fixed_rate_pct_min": 80.0,
        "max_float_transitions": 5,
        "ttff_sec_max": 120.0,
        "base_rate_min_fps": 1.0,
    },
    "reconnect": {
        "auto": True,
        "check_interval_sec": 2.0,
        "retry_interval_sec": 3.0,
        "max_attempts": 0,
    },
    "report": {"output_dir": None, "json": True},
}

# 自己検証（--self-test）用の合成シナリオ。短時間で FLOAT → FIXED を再現する。
SELF_TEST_DURATION = 4.0
SELF_TEST_INTERVAL = 0.1
SELF_TEST_FIX_SCRIPT = [(0.0, 5), (0.3, 6)]  # (経過秒, fix_type): FLOAT → FIXED

DEFAULT_REPORT_DIR = Path(__file__).resolve().parent / "reports"


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> None:
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


def load_preflight_config(path: Optional[str] = None) -> Dict[str, Any]:
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


class PreflightRunner:
    """Item 2（静的照合）→ Item 1 / Item 3 / 基地局レート（動的健全性）を実行する。"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = deepcopy(DEFAULT_CONFIG)
        if config:
            _deep_merge(self.config, config)
        # GUI の「再接続」ボタンから操作するためのセッション参照
        self.session: Optional[TcpSession] = None
        # GUI の「停止」ボタン用の停止フラグ
        self._stop_event = threading.Event()

    # ------------------------------------------------------------------
    # ヘルパー
    # ------------------------------------------------------------------
    def _build_monitor(self) -> CorrectionMonitor:
        m = self.config["monitor"]
        return CorrectionMonitor(
            age_alert_threshold=float(m.get("age_alert_threshold", 10.0)),
            age_warn_threshold=float(m.get("age_warn_threshold", 5.0)),
            crc_alert_rate_pct=float(m.get("crc_alert_rate_pct", 5.0)),
            used_alert_ratio_pct=float(m.get("used_alert_ratio_pct", 50.0)),
        )

    def _progress_event(self, session: Any, elapsed: float, duration: float) -> Dict[str, Any]:
        snap = session.snapshot()
        age = snap.get("rtk_age", {})
        return {
            "type": "progress",
            "elapsed_sec": elapsed,
            "duration_sec": duration,
            "fix": fix_name(session.sample() or 0),
            "rtk_age_state": age.get("state", "no_data"),
            "rtk_age_sec": age.get("age_sec"),
            "rtcm_total": int((snap.get("rxm_rtcm") or {}).get("total", 0) or 0),
            "connection": snap.get("connection", {}),
        }

    # ------------------------------------------------------------------
    # Item 2（静的照合: golden 差分）
    # ------------------------------------------------------------------
    def run_item2(self, host: str, port: int) -> Any:
        cfg = self.config["connection"]
        timeout = float(cfg.get("timeout", 3.0))
        auto_fix = bool(self.config["item2"].get("auto_fix", False))
        guard = F9pConfigGuard(host=host, port=port, timeout=timeout,
                               flash_wait_seconds=0)
        # F9pConfigGuard は内部で標準出力に表示するため抑制（結果は戻り値の dict で受け取る）
        with contextlib.redirect_stdout(io.StringIO()):
            result = guard.run_check_and_fix(fix=auto_fix)
        return evaluate_item2(result)

    # ------------------------------------------------------------------
    # 動的観測（Item 1 / Item 3 / 基地局レート）
    # ------------------------------------------------------------------
    def _observe(self, session: TcpSession, duration: float, interval: float,
                 on_event: Optional[Callable[[Dict[str, Any]], None]] = None
                 ) -> List[Dict[str, Any]]:
        series: List[Dict[str, Any]] = []
        start = time.monotonic()
        last_sample = 0.0
        last_progress = 0.0
        while time.monotonic() - start < duration and not self._stop_event.is_set():
            now = time.monotonic()
            ft = session.sample()
            if ft is not None and now - last_sample >= interval:
                last_sample = now
                t = now - start
                ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                series.append({"t": t, "ts": ts, "fix_type": ft})
            if on_event is not None and now - last_progress >= 1.0:
                last_progress = now
                on_event(self._progress_event(session, now - start, duration))
            time.sleep(min(0.05, interval))
        return series

    def _observe_synthetic(self, rover: SyntheticRoverSource, duration: float,
                           interval: float,
                           on_event: Optional[Callable[[Dict[str, Any]], None]] = None
                           ) -> List[Dict[str, Any]]:
        series: List[Dict[str, Any]] = []
        start = time.monotonic()
        while time.monotonic() - start < duration and not self._stop_event.is_set():
            rover.tick()
            ft = rover.sample()
            now = time.monotonic()
            if ft is not None:
                t = now - start
                ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                if not series or (t - series[-1]["t"]) >= interval:
                    series.append({"t": t, "ts": ts, "fix_type": ft})
            time.sleep(min(0.05, interval))
        return series

    # ------------------------------------------------------------------
    # メイン API
    # ------------------------------------------------------------------
    def run(self, host: Optional[str] = None, port: Optional[int] = None,
            duration: Optional[float] = None, auto_fix: Optional[bool] = None,
            on_event: Optional[Callable[[Dict[str, Any]], None]] = None,
            offline: bool = False,
            fix_script: Optional[List[tuple]] = None) -> PreflightReport:
        conn = self.config["connection"]
        host = str(host or conn.get("host", "192.168.1.100"))
        port = int(port if port is not None else conn.get("port", 5001))
        if auto_fix is not None:
            self.config["item2"]["auto_fix"] = bool(auto_fix)

        mon_cfg = self.config["monitor"]
        duration = float(duration if duration is not None else mon_cfg.get("duration_sec", 60.0))
        interval = float(mon_cfg.get("sample_interval_sec", 1.0))
        criteria = self.config["criteria"]

        started_at = utc_now_iso()
        self._stop_event.clear()

        # Item 2（静的照合）
        if offline:
            guard = F9pConfigGuard(flash_wait_seconds=0)
            item2 = evaluate_item2(run_phase1_offline(guard))
        else:
            item2 = self.run_item2(host, port)

        # 動的観測
        mon = self._build_monitor()
        self.session = None
        session: Optional[TcpSession] = None
        if offline:
            # 合成ソースは約 5 msg/s（interval=0.2）で UBX-RXM-RTCM を供給し、
            # 基地局レート（既定 >= 1.0 msg/s）を満たすようにする。
            rover = SyntheticRoverSource(monitor=mon, fix_script=fix_script, interval=0.2)
            series = self._observe_synthetic(rover, duration, interval, on_event)
        else:
            session = TcpSession(host, port, mon, poll_interval=interval,
                                 timeout=float(conn.get("timeout", 3.0)),
                                 on_state=on_event)
            self.session = session
            session.connect()
            if self.config["reconnect"].get("auto", True):
                session.start_auto_reconnect(
                    check_interval=float(self.config["reconnect"].get("check_interval_sec", 2.0)),
                    retry_interval=float(self.config["reconnect"].get("retry_interval_sec", 3.0)),
                    max_attempts=int(self.config["reconnect"].get("max_attempts", 0)),
                )
            try:
                series = self._observe(session, duration, interval, on_event)
            finally:
                session.close()

        snapshot = mon.snapshot()
        metrics = compute_metrics(series)

        item1 = evaluate_item1(metrics, criteria)
        item3 = evaluate_item3(snapshot, criteria)
        base = evaluate_base_rate(snapshot, duration, criteria)

        report = PreflightReport(
            [item2, item1, item3, base],
            connection={"host": host, "port": port},
            started_at=started_at,
            finished_at=utc_now_iso(),
        )
        self._save_report(report, series, snapshot)
        return report

    def request_stop(self) -> None:
        """動的観測ループを途中停止する（GUI の「停止」ボタン用）。"""
        self._stop_event.set()
        if self.session is not None:
            try:
                self.session.close()
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------------
    # 成果物保存
    # ------------------------------------------------------------------
    def _save_report(self, report: PreflightReport, series: List[Dict[str, Any]],
                     snapshot: Dict[str, Any]) -> None:
        rep_cfg = self.config.get("report", {})
        if not rep_cfg.get("json", True):
            return
        out_dir = Path(rep_cfg.get("output_dir")) if rep_cfg.get("output_dir") else DEFAULT_REPORT_DIR
        out_dir = out_dir.resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        payload = report.to_dict()
        payload["fix_type_series"] = series
        payload["rtcm_snapshot"] = snapshot
        path = out_dir / ("preflight_report_%s.json" % ts)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2, default=str)


# ---------------------------------------------------------------------------
# コマンドライン
# ---------------------------------------------------------------------------
def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Phase 3 飛行前セルフテスト（Item 2 照合 + Item 1/3/基地局レート 動的健全性）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--host", default=None,
                   help="DroneCAN Serial Forwarding のホスト（機体 Wi-Fi IP。既定: 192.168.1.100）")
    p.add_argument("--port", type=int, default=None, help="TCP ポート（既定: 5001）")
    p.add_argument("--duration", type=float, default=None,
                   help="動的観測時間[秒]（既定: 60.0）")
    p.add_argument("--auto-fix", action="store_true",
                   help="Item 2 で golden 退行を検知したら自動修正する（既定は照合のみ）")
    p.add_argument("--no-auto-reconnect", action="store_true",
                   help="バックグラウンド自動再接続を無効化する")
    p.add_argument("--config", default=None, help="上書き設定の YAML パス")
    p.add_argument("--report-dir", default=None, help="JSON レポート出力先")
    p.add_argument("--self-test", action="store_true",
                   help="実機なしの自己検証（合成データでフルパイプラインを検証）")
    p.add_argument("--json", action="store_true", help="チェックリストの JSON も標準出力する")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    config = load_preflight_config(args.config)
    if args.no_auto_reconnect:
        config["reconnect"]["auto"] = False
    if args.report_dir:
        config["report"]["output_dir"] = args.report_dir

    duration_override = args.duration
    fix_script = None
    if args.self_test:
        duration_override = args.duration if args.duration is not None else SELF_TEST_DURATION
        fix_script = SELF_TEST_FIX_SCRIPT
        # 自己検証では観測間隔を短縮して高速に PASS を確認する
        config["monitor"]["sample_interval_sec"] = SELF_TEST_INTERVAL

    runner = PreflightRunner(config)

    def _print_progress(ev: Dict[str, Any]) -> None:
        if ev.get("type") == "progress":
            print("[観測 %.1f/%.1f 秒] fix=%s | RTK age=%s | RTCM=%d msg"
                  % (ev.get("elapsed_sec", 0.0), ev.get("duration_sec", 0.0),
                     ev.get("fix", "-"), ev.get("rtk_age_state", "-"),
                     ev.get("rtcm_total", 0)))

    report = runner.run(
        host=args.host, port=args.port, duration=duration_override,
        auto_fix=args.auto_fix, on_event=_print_progress,
        offline=args.self_test, fix_script=fix_script,
    )

    print()
    print(report.format_checklist())
    if args.json:
        print(report.to_json())
    return 0 if report.overall_status() == STATUS_PASS else 1


if __name__ == "__main__":
    sys.exit(main())

