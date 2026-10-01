#!/usr/bin/env python3
"""runner.py — Phase 4 実飛行試験ランナー（CLI / 1 コマンド実行）

飛行中（移動局 F9P を機体に搭載）の fix_type 時系列・位置精度を記録し、RTK-FIXED 維持率・
FLOAT 遷移・EKF 整合性・測位劣化時のフェイルセーフ動作を評価して、レポート（JSON / Markdown）
と次フェーズへの課題を出力する。

使い方:
    python3 gcs/flight_test/runner.py --observe --device /dev/ttyAMA0 --duration 300
    python3 gcs/flight_test/runner.py --observe --mavlink tcp:192.168.1.100:5760
    python3 gcs/flight_test/runner.py --csv flight_*.csv --events flight_*.events.jsonl
    python3 gcs/flight_test/runner.py --self-test
"""

from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

# 実行位置に依存しない import（リポジトリルートを sys.path に追加）
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# 既存資産の再利用（既存ファイルは無改変）
from gcs.fix_metrics import compute_metrics  # noqa: E402
from gcs.ekf_failsafe.param_guard import ArduPilotParamGuard  # noqa: E402
from gcs.ekf_failsafe.checklist import evaluate_failsafe  # noqa: E402

from gcs.flight_test.metrics import (  # noqa: E402
    STATUS_PASS, STATUS_FAIL, STATUS_SKIP, STATUS_INFO,
    FlightSpec, compute_ekf_consistency, detect_degradations,
    confirm_failsafe, next_phase_issues,
)
from gcs.flight_test.recorder import (  # noqa: E402
    FlightRecorder, write_flight_csv, write_events_jsonl,
    load_flight_csv, load_events_jsonl,
)
from gcs.flight_test.report import FlightReport, utc_now_iso  # noqa: E402


DEFAULT_CONFIG: Dict[str, Any] = {
    "connection": {
        "device": None,
        "baud": 921600,
        "mavlink": None,
        "timeout": 3.0,
    },
    "observe": {"duration_sec": 300.0, "sample_interval_sec": 1.0},
    "failsafe": {"ok": True},  # 2e8a3 golden は gcs/ekf_failsafe で事前照合済みが前提
    "report": {"output_dir": None},
}

DEFAULT_REPORT_DIR = Path(__file__).resolve().parent / "reports"
DEFAULT_LOG_DIR = Path(__file__).resolve().parent / "logs"

_EKF_HEALTHY = 0x001 | 0x002 | 0x004 | 0x010 | 0x020  # 姿勢+速度+位置 健全


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> None:
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


def load_flight_config(path: Optional[str] = None) -> Dict[str, Any]:
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


def _check(name: str, ok: bool, expected: Any = None, actual: Any = None,
           message: str = "") -> Dict[str, Any]:
    return {"name": name, "ok": bool(ok), "expected": expected,
            "actual": actual, "message": message}

# ---------------------------------------------------------------------------
# セクション組立（評価 → PASS/FAIL/SKIP）
# ---------------------------------------------------------------------------
def _section_recording(series: List[Dict[str, Any]],
                       ekf: Dict[str, Any]) -> Dict[str, Any]:
    has_hdop = any(r.get("hdop") is not None for r in series)
    has_ekf_acc = any(r.get("ekf_pos_horiz_m") is not None for r in series)
    accuracy_captured = has_hdop or has_ekf_acc
    n = len(series)
    checks = [
        _check("samples", n > 0, expected="> 0", actual="%d 件" % n,
               message="fix_type 時系列サンプル"),
        _check("position_accuracy", accuracy_captured,
               expected="捕捉あり", actual="あり" if accuracy_captured else "なし",
               message="位置精度（HDOP / EKF 位置分散）の記録"),
    ]
    ok = all(c["ok"] for c in checks)
    summary = "n=%d 件 / 位置精度=%s" % (n, "捕捉" if accuracy_captured else "未捕捉")
    return {
        "name": "① fix_type 時系列・位置精度の記録",
        "status": STATUS_PASS if ok else STATUS_FAIL,
        "summary": summary,
        "checks": checks,
        "details": {"has_hdop": has_hdop, "has_ekf_accuracy": has_ekf_acc},
    }


def _section_rtk(rtk: Dict[str, Any], spec: FlightSpec) -> Dict[str, Any]:
    reached = bool(rtk.get("reached_fixed"))
    fixed_rate = float(rtk.get("fixed_rate_after_first_pct", 0.0) or 0.0)
    float_cnt = int(rtk.get("float_transition_count", 0) or 0)
    ttff = rtk.get("ttff_sec")
    checks = [
        _check("reached_fixed", reached, expected=True, actual=reached,
               message="RTK_FIXED 到達"),
        _check("fixed_rate_min",
               reached and fixed_rate >= spec.fixed_rate_pct_min,
               expected=">= %.1f %%" % spec.fixed_rate_pct_min,
               actual="%.1f %%" % fixed_rate,
               message="FIXED 維持率（初回 FIXED 以降）"),
        _check("float_transition_max", float_cnt <= spec.max_float_transitions,
               expected="<= %d 回" % spec.max_float_transitions,
               actual="%d 回" % float_cnt,
               message="FLOAT 遷移回数"),
    ]
    ok = all(c["ok"] for c in checks)
    summary = ("維持率 %.1f %% / FLOAT 遷移 %d 回 / TTFF %s"
               % (fixed_rate, float_cnt,
                  "%.1f 秒" % float(ttff) if ttff is not None else "n/a"))
    return {
        "name": "② RTK-FIXED 維持率・FLOAT 遷移",
        "status": STATUS_PASS if ok else STATUS_FAIL,
        "summary": summary,
        "checks": checks,
        "details": rtk,
    }


def _section_ekf(ekf: Dict[str, Any], spec: FlightSpec) -> Dict[str, Any]:
    if not ekf.get("has_ekf_flags"):
        return {
            "name": "③ EKF との整合性",
            "status": STATUS_SKIP,
            "summary": "EKF フラグが観測されなかったためスキップ",
            "checks": [],
            "details": ekf,
        }
    consistency = ekf.get("fixed_ekf_consistency_pct")
    horiz_max = ekf.get("fixed_horiz_err_max_m")
    checks = [
        _check("ekf_consistency",
               consistency is not None and consistency >= spec.ekf_consistency_pct_min,
               expected=">= %.1f %%" % spec.ekf_consistency_pct_min,
               actual=("n/a" if consistency is None else "%.1f %%" % consistency),
               message="FIXED 時に EKF 位置健全である割合"),
    ]
    if ekf.get("has_accuracy"):
        checks.append(_check(
            "ekf_horiz_err",
            horiz_max is not None and horiz_max <= spec.ekf_horiz_err_max_m,
            expected="<= %.3f m" % spec.ekf_horiz_err_max_m,
            actual=("n/a" if horiz_max is None else "%.3f m" % horiz_max),
            message="FIXED 時の EKF 水平位置誤差(1σ) 最大値"))
    ok = all(c["ok"] for c in checks)
    summary = ("整合性 %s / 水平誤差(最大) %s"
               % ("n/a" if consistency is None else "%.1f %%" % consistency,
                  "n/a" if horiz_max is None else "%.3f m" % horiz_max))
    return {
        "name": "③ EKF との整合性",
        "status": STATUS_PASS if ok else STATUS_FAIL,
        "summary": summary,
        "checks": checks,
        "details": ekf,
    }


def _section_failsafe(failsafe: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "name": "④ 測位劣化時のフェイルセーフ動作",
        "status": STATUS_PASS if failsafe.get("ok") else STATUS_FAIL,
        "summary": failsafe.get("summary", ""),
        "checks": failsafe.get("checks", []),
        "details": failsafe,
    }

# ---------------------------------------------------------------------------
# 一括評価 → FlightReport
# ---------------------------------------------------------------------------
def evaluate_flight(series: List[Dict[str, Any]],
                    failsafe_ok: bool = True,
                    failsafe_events: Optional[List[Dict[str, Any]]] = None,
                    mode_events: Optional[List[Dict[str, Any]]] = None,
                    spec: Optional[FlightSpec] = None,
                    inputs: Optional[Dict[str, Any]] = None) -> FlightReport:
    """fix_type 時系列から 4 要件を評価し、FlightReport を組み立てる。"""
    spec = spec or FlightSpec()
    rtk = compute_metrics(series)
    ekf = compute_ekf_consistency(series)
    degrad = detect_degradations(series, spec)
    failsafe = confirm_failsafe(series, failsafe_ok, failsafe_events, mode_events, spec)

    sections = [
        _section_recording(series, ekf),
        _section_rtk(rtk, spec),
        _section_ekf(ekf, spec),
        _section_failsafe(failsafe),
    ]
    statuses = [s["status"] for s in sections]
    overall = STATUS_FAIL if STATUS_FAIL in statuses else STATUS_PASS
    issues = next_phase_issues(series, rtk, ekf, degrad, failsafe, spec)

    summary = ("RTK-FIXED を飛行中も維持できました" if overall == STATUS_PASS
               else "基準を満たさない項目があります（次フェーズ課題を参照）")
    return FlightReport(spec=spec.to_dict(), inputs=inputs or {},
                        sections=sections, issues=issues,
                        overall_status=overall, summary=summary)


class FlightTestRunner:
    """観測 or 既存 CSV から飛行試験を評価し、レポートを出力する。"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = deepcopy(DEFAULT_CONFIG)
        if config:
            _deep_merge(self.config, config)

    def observe(self, duration: Optional[float] = None,
                on_event: Optional[Callable[[Dict[str, Any]], None]] = None
                ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
        conn = self.config["connection"]
        obs = self.config["observe"]
        duration = float(duration if duration is not None else obs.get("duration_sec", 300.0))
        interval = float(obs.get("sample_interval_sec", 1.0))
        rec = FlightRecorder(
            device=conn.get("device"),
            baud=int(conn.get("baud", 921600)),
            connection_string=conn.get("mavlink"),
            timeout=float(conn.get("timeout", 3.0)),
        )
        return rec.observe(duration, interval, on_event)

    def run(self, series: List[Dict[str, Any]],
            failsafe_events: Optional[List[Dict[str, Any]]] = None,
            mode_events: Optional[List[Dict[str, Any]]] = None,
            failsafe_ok: Optional[bool] = None,
            spec: Optional[FlightSpec] = None,
            inputs: Optional[Dict[str, Any]] = None) -> FlightReport:
        if failsafe_ok is None:
            failsafe_ok = bool(self.config.get("failsafe", {}).get("ok", True))
        return evaluate_flight(series, failsafe_ok=failsafe_ok,
                               failsafe_events=failsafe_events,
                               mode_events=mode_events,
                               spec=spec, inputs=inputs)

    def save_report(self, report: FlightReport,
                    series: Optional[List[Dict[str, Any]]] = None,
                    output_dir: Optional[str] = None) -> Tuple[Path, Path]:
        rep_cfg = self.config.get("report", {})
        out_dir = Path(output_dir or rep_cfg.get("output_dir") or DEFAULT_REPORT_DIR)
        out_dir = out_dir.resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        json_path = out_dir / ("flight_report_%s.json" % ts)
        md_path = out_dir / ("flight_report_%s.md" % ts)
        payload = report.to_dict()
        if series is not None:
            payload["fix_series"] = series
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2,
                                        default=str), encoding="utf-8")
        md_path.write_text(report.format_markdown(), encoding="utf-8")
        return json_path, md_path

# ---------------------------------------------------------------------------
# 自己検証用の合成データ生成
# ---------------------------------------------------------------------------
def _synthetic_series(fix_script: List[Tuple[float, int]],
                      duration: float = 10.0, step: float = 0.5,
                      ekf_flags: int = _EKF_HEALTHY,
                      horiz_m: float = 0.02, vert_m: float = 0.04,
                      hdop: float = 0.8, sats: int = 22,
                      fail_ekf_at: Optional[float] = None) -> List[Dict[str, Any]]:
    """自己検証用の合成時系列を生成する（fix_script = [(経過秒, fix_type), ...]）。"""
    series: List[Dict[str, Any]] = []
    t = 0.0
    cur = 0
    idx = 0
    while t <= duration:
        while idx < len(fix_script) and t >= fix_script[idx][0]:
            cur = fix_script[idx][1]
            idx += 1
        flags = ekf_flags
        if fail_ekf_at is not None and t >= fail_ekf_at:
            flags = 0x000
        series.append({
            "t": t, "ts": "",
            "fix_type": cur,
            "hdop": hdop, "vdop": hdop * 1.5, "sats": sats,
            "ekf_flags": flags,
            "ekf_pos_horiz_m": horiz_m, "ekf_pos_vert_m": vert_m,
            "ekf_vel_var": 0.01,
        })
        t += step
    return series


def self_test() -> int:
    """合成データでフルパイプライン（PASS と FAIL の両方）を検証する。"""
    clean = _synthetic_series([(0.0, 5), (1.0, 6)])       # FLOAT → FIXED 維持
    degr = _synthetic_series([(0.0, 5), (1.0, 6), (4.0, 0), (6.0, 5), (6.5, 6)],
                             fail_ekf_at=5.0)              # GPS 喪失 + EKF 不健全

    rep_ok = evaluate_flight(clean, failsafe_ok=True)
    rep_ng = evaluate_flight(degr, failsafe_ok=True)       # 重度劣化あり・FS 証跡なし

    ok = rep_ok.overall() == STATUS_PASS
    ng = rep_ng.overall() == STATUS_FAIL
    print("runner self-test: %s" % ("OK" if (ok and ng) else "FAILED"))
    if not ok:
        print("  [FAIL] 正常系フライトが PASS になりませんでした")
    if not ng:
        print("  [FAIL] 劣化系フライト（FS 証跡なし）が FAIL になりませんでした")
    return 0 if (ok and ng) else 1

# ---------------------------------------------------------------------------
# コマンドライン
# ---------------------------------------------------------------------------
def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Phase 4 実飛行試験（RTK-FIXED 飛行中維持・EKF/FS 検証）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--observe", action="store_true",
                   help="MAVLink を観測して記録＋評価する")
    p.add_argument("--device", default=None, help="MAVLink シリアルデバイス（例: /dev/ttyAMA0）")
    p.add_argument("--baud", type=int, default=None, help="MAVLink シリアルボーレート")
    p.add_argument("--mavlink", default=None, help="MAVLink 接続文字列（tcp:host:port / udpin:...）")
    p.add_argument("--duration", type=float, default=None, help="観測時間[秒]（既定: 300.0）")
    p.add_argument("--interval", type=float, default=None, help="サンプリング間隔[秒]")
    p.add_argument("--csv", default=None, help="記録済み CSV（後処理評価）")
    p.add_argument("--events", default=None, help="記録済みイベント JSONL（--csv と併用）")
    p.add_argument("--check-failsafe", action="store_true",
                   help="2e8a3（EKF/FS golden）を MAVLink で照合して FS 有効性を確認")
    p.add_argument("--failsafe-ok", action="store_true",
                   help="2e8a3 golden が有効であると明示（既定も True）")
    p.add_argument("--failsafe-ng", action="store_true",
                   help="2e8a3 golden が無効であると明示（負の検証用）")
    p.add_argument("--config", default=None, help="上書き設定の YAML パス")
    p.add_argument("--report-dir", default=None, help="レポート出力先")
    p.add_argument("--self-test", action="store_true",
                   help="実機なしの自己検証（合成データでフルパイプラインを検証）")
    p.add_argument("--json", action="store_true", help="レポート JSON も標準出力する")
    return p


def _check_failsafe_golden(config: Dict[str, Any]) -> bool:
    """ArduPilotParamGuard（2e8a3）で EKF/FS golden を照合し、failsafe 群の合否を返す。"""
    conn = config["connection"]
    guard = ArduPilotParamGuard(
        device=conn.get("device"),
        baud=int(conn.get("baud", 921600)),
        connection_string=conn.get("mavlink"),
        timeout=float(conn.get("timeout", 3.0)),
    )
    result = guard.run_check_and_fix(fix=False)
    item = evaluate_failsafe(result)
    print("[check-failsafe] FS golden（2e8a3）: %s" % item.status)
    return item.is_pass()


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    config = load_flight_config(args.config)
    conn = config["connection"]
    if args.device:
        conn["device"] = args.device
    if args.baud is not None:
        conn["baud"] = args.baud
    if args.mavlink:
        conn["mavlink"] = args.mavlink
    if args.duration is not None:
        config["observe"]["duration_sec"] = args.duration
    if args.interval is not None:
        config["observe"]["sample_interval_sec"] = args.interval
    if args.report_dir:
        config["report"]["output_dir"] = args.report_dir

    if args.self_test:
        return self_test()

    runner = FlightTestRunner(config)

    failsafe_ok: Optional[bool] = None
    if args.failsafe_ng:
        failsafe_ok = False
    elif args.failsafe_ok:
        failsafe_ok = True
    elif args.check_failsafe:
        failsafe_ok = _check_failsafe_golden(config)

    if args.observe:
        def _progress(ev: Dict[str, Any]) -> None:
            if ev.get("type") == "progress":
                print("[観測 %.1f/%.1f 秒] fix_type=%s | EKF flags=%s"
                      % (ev.get("elapsed_sec", 0.0), ev.get("duration_sec", 0.0),
                         ev.get("fix_type", "-"),
                         hex(ev.get("ekf_flags") or 0)))
        series, fs_events, mode_events = runner.observe(on_event=_progress)
        DEFAULT_LOG_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_path = DEFAULT_LOG_DIR / ("flight_%s.csv" % ts)
        ev_path = DEFAULT_LOG_DIR / ("flight_%s.events.jsonl" % ts)
        write_flight_csv(series, str(csv_path))
        write_events_jsonl(fs_events, mode_events, str(ev_path))
        print("[LOG] CSV   : %s" % csv_path)
        print("[LOG] EVENT : %s" % ev_path)
        inputs = {"csv": str(csv_path), "events": str(ev_path)}
        report = runner.run(series, fs_events, mode_events, failsafe_ok=failsafe_ok,
                            inputs=inputs)
    elif args.csv:
        series = load_flight_csv(args.csv)
        fs_events, mode_events = ([], [])
        if args.events:
            fs_events, mode_events = load_events_jsonl(args.events)
        inputs = {"csv": args.csv, "events": args.events}
        report = runner.run(series, fs_events, mode_events, failsafe_ok=failsafe_ok,
                            inputs=inputs)
    else:
        print("[ERROR] --observe / --csv / --self-test のいずれかを指定してください")
        return 2

    print()
    print(report.format_text())
    json_path, md_path = runner.save_report(report, series, args.report_dir)
    print("\n[LOG] JSON: %s" % json_path)
    print("[LOG] MD  : %s" % md_path)
    if args.json:
        print(report.to_json())
    return 0 if report.overall() == STATUS_PASS else 1


if __name__ == "__main__":
    sys.exit(main())




