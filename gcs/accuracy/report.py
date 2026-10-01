#!/usr/bin/env python3
"""report.py — 相対測位精度実測のレポート組立・出力（標準ライブラリのみ）

Phase 2.5 の実測結果（既知距離比較 / RTK基線長 / PPKクロスチェック）を束ね、
人間可読なテキストと JSON（GCS 統合用）の両方を生成する。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_SKIP = "SKIP"

TITLE = "Phase 2.5 機体間相対測位精度 実測レポート"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AccuracyReport:
    """実測レポート。sections は「名前・状態・要約・チェック・詳細」の dict 列。"""

    def __init__(self,
                 started_at: Optional[str] = None,
                 finished_at: Optional[str] = None,
                 spec: Optional[Dict[str, Any]] = None,
                 inputs: Optional[Dict[str, Any]] = None,
                 sections: Optional[List[Dict[str, Any]]] = None,
                 overall_status: str = STATUS_PASS,
                 summary: str = ""):
        self.started_at = started_at or utc_now_iso()
        self.finished_at = finished_at or utc_now_iso()
        self.spec = spec or {}
        self.inputs = inputs or {}
        self.sections = sections or []
        self.overall_status = overall_status
        self.summary = summary

    def overall(self) -> str:
        return self.overall_status

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": TITLE,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "overall": {"status": self.overall_status, "summary": self.summary},
            "spec": self.spec,
            "inputs": self.inputs,
            "sections": self.sections,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent,
                          default=str)

    def format_text(self) -> str:
        lines: List[str] = []
        bar = "=" * 70
        lines.append(bar)
        lines.append(TITLE)
        lines.append("  開始: %s" % self.started_at)
        lines.append("  終了: %s" % self.finished_at)
        lines.append(bar)

        if self.spec:
            lines.append("【想定精度（仮・要定義）】")
            for k, v in self.spec.items():
                lines.append("  %-26s = %s" % (k, v))
            lines.append(bar)

        for s in self.sections:
            if s.get("status") == STATUS_PASS:
                mark = "✅"
            elif s.get("status") == STATUS_FAIL:
                mark = "❌"
            else:
                mark = "⚠"
            lines.append("%s %s: %s" % (mark, s.get("name", ""), s.get("status")))
            if s.get("summary"):
                lines.append("   %s" % s["summary"])
            for c in s.get("checks", []):
                cm = "✓" if c["ok"] else "✗"
                exp = "" if c["expected"] is None else " (期待: %s)" % c["expected"]
                act = "" if c["actual"] is None else " = %s" % c["actual"]
                msg = (" / " + c["message"]) if c["message"] else ""
                lines.append("     [%s] %-22s%s%s%s" % (cm, c["name"], exp, act, msg))

        lines.append(bar)
        note = "（全セクション合格）" if self.overall_status == STATUS_PASS \
            else "（不合格あり）"
        lines.append("総合判定: %s%s" % (self.overall_status, note))
        if self.summary:
            lines.append("   %s" % self.summary)
        lines.append(bar)
        return "\n".join(lines)


__all__ = ["STATUS_PASS", "STATUS_FAIL", "STATUS_SKIP", "TITLE",
           "utc_now_iso", "AccuracyReport"]
