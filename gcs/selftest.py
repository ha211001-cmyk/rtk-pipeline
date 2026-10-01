#!/usr/bin/env python3
"""gcs.selftest — 実機不要の自己検証（合成データ・同梱設定検証）。

ハードウェアや外部接続に依存せず、統合後の gcs/ の中核ロジックが正しく
動くことを 1 コマンドで確認するためのセルフチェックです。

    python3 -m gcs.selftest

検証項目:
  1. 合成 RTCM3 フレーム生成 → Rtcm3StreamParser がフレーム抽出 + CRC 検証できる
  2. 合成 fix_type 時系列（FLOAT → FIXED）→ fix_metrics が指標を正しく集計できる
  3. 同梱設定（gcs/config/*.yml）がスキーマ検証を通過する

戻り値: 全項目成功で 0、1 つでも失敗なら 1。
"""

from __future__ import annotations

import json
import sys
from typing import Any, Dict, List

# 合成 RTCM3 メッセージ番号（GPS MSM7 = 1077）
SYNTH_MSG_TYPE = 1077
RTCM3_PREAMBLE = 0xD3
RTCM3_HEADER_LEN = 3
RTCM3_CRC_LEN = 3


def build_rtcm3_frame(msg_type: int, payload_size: int = 8) -> bytes:
    """有効な RTCM3 フレーム（CRC-24Q 付き）を合成する。

    ペイロード先頭 12bit にメッセージ番号を埋め、残りを 0 で埋める。
    """
    from gcs.rtcm_monitor import rtcm3_crc24q  # noqa: PLC0415 - 正典ロジック再利用

    # ペイロード先頭 12bit = msg_type（frame[3] << 4 | frame[4] >> 4）
    b0 = (msg_type >> 4) & 0xFF
    b1 = (msg_type & 0x0F) << 4
    payload = bytes([b0, b1]) + bytes(max(0, payload_size - 2))

    header = bytes([
        RTCM3_PREAMBLE,
        (len(payload) >> 8) & 0x03,  # reserved 6bit=0 + 10bit 長の上位
        len(payload) & 0xFF,
    ])
    frame_without_crc = header + payload
    crc = rtcm3_crc24q(frame_without_crc)
    crc_bytes = bytes([(crc >> 16) & 0xFF, (crc >> 8) & 0xFF, crc & 0xFF])
    return frame_without_crc + crc_bytes


def check_rtcm3_parser() -> Dict[str, Any]:
    """合成 RTCM3 フレームを Rtcm3StreamParser に投入して検証する。"""
    from gcs.rtcm_monitor import Rtcm3StreamParser, rtcm3_frame_msg_type  # noqa: PLC0415

    parser = Rtcm3StreamParser(verify_crc=True)
    frames: List[bytes] = []
    for _ in range(5):
        frames.extend(parser.feed(build_rtcm3_frame(SYNTH_MSG_TYPE)))

    stats = parser.stats
    ok = (
        len(frames) == 5
        and stats["frames_received"] == 5
        and stats["crc_failed"] == 0
        and stats["crc_ok"] == 5
        and all(rtcm3_frame_msg_type(f) == SYNTH_MSG_TYPE for f in frames)
    )
    return {
        "name": "rtcm3_parser",
        "ok": bool(ok),
        "frames": len(frames),
        "crc_ok": stats["crc_ok"],
        "crc_failed": stats["crc_failed"],
        "msg_type": SYNTH_MSG_TYPE,
    }


def check_fix_metrics() -> Dict[str, Any]:
    """合成 fix_type 時系列（FLOAT → FIXED）から指標を集計する。"""
    from gcs.fix_metrics import FIXED, FLOAT, compute_metrics  # noqa: PLC0415

    series = []
    for t in range(0, 10):
        series.append({"t": float(t), "fix_type": FLOAT})
    for t in range(10, 30):
        series.append({"t": float(t), "fix_type": FIXED})

    metrics = compute_metrics(series)
    ok = (
        metrics["reached_fixed"] is True
        and metrics["total_samples"] == 30
        and metrics["ttff_sec"] is not None
        and metrics["ttff_sec"] > 0
        and metrics["fixed_rate_pct"] > 50.0
        and metrics["transition_count"] >= 1
    )
    return {
        "name": "fix_metrics",
        "ok": bool(ok),
        "reached_fixed": metrics["reached_fixed"],
        "ttff_sec": metrics["ttff_sec"],
        "fixed_rate_pct": metrics["fixed_rate_pct"],
        "total_samples": metrics["total_samples"],
    }


def check_config_schema() -> Dict[str, Any]:
    """同梱設定ファイルがスキーマ検証を通過するか検証する。"""
    from gcs.config.schema import validate_bundled_configs  # noqa: PLC0415

    results = validate_bundled_configs()
    failed = {name: r["errors"] for name, r in results.items() if r["errors"]}
    return {
        "name": "config_schema",
        "ok": len(failed) == 0,
        "files_checked": len(results),
        "failed": failed,
    }


def run_selfcheck() -> Dict[str, Any]:
    """全セルフチェックを実行してサマリーを返す。"""
    checks = [check_rtcm3_parser(), check_fix_metrics(), check_config_schema()]
    all_ok = all(c["ok"] for c in checks)
    return {
        "ok": all_ok,
        "checks": checks,
    }


def main(argv=None) -> int:
    summary = run_selfcheck()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
