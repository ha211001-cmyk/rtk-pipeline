#!/usr/bin/env python3
"""report.py — Phase 4 実飛行試験のレポート組立・出力（標準ライブラリのみ）

飛行試験結果（記録 / RTK-FIXED 維持率・FLOAT 遷移 / EKF 整合性 / フェイルセーフ動作）を
束ね、人間可読な Markdown と JSON（GCS 統合用）を生成する。加えて次フェーズへの
課題整理（next_phase_issues の結果）をレポートに含める。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_SKIP = "SKIP"
STATUS_INFO = "INFO"

TITLE = "Phase 4 実飛行試験 レポート"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fmt(v: Any) -> str:
    if v is None:
        return "n/a"
    if isinstance(v, float):
        return "%.3f" % v
    return str(v)


class FlightReport:
    """実飛行試験レポート。sections は「名前・状態・要約・チェック・詳細」の dict 列。"""

    def __init__(self,
                 started_at: Optional[str] = None,
                 finished_at: Optional[str] = None,
                 spec: Optional[Dict[str, Any]] = None,
                 inputs: Optional[Dict[str, Any]] = None,
                 sections: Optional[List[Dict[str, Any]]] = None,
                 issues: Optional[List[Dict[str, Any]]] = None,
                 overall_status: str = STATUS_PASS,
                 summary: str = ""):
        self.started_at = started_at or utc_now_iso()
        self.finished_at = finished_at or utc_now_iso()
        self.spec = spec or {}
        self.inputs = inputs or {}
        self.sections = sections or []
        self.issues = issues or []
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
            "next_phase_issues": self.issues,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent,
                          default=str)

    # ------------------------------------------------------------------
    # 人間可読（テキスト）
    # ------------------------------------------------------------------
    def format_text(self) -> str:
        lines: List[str] = []
        bar = "=" * 70
        lines.append(bar)
        lines.append(TITLE)
        lines.append("  開始: %s" % self.started_at)
        lines.append("  終了: %s" % self.finished_at)
        lines.append(bar)

        for s in self.sections:
            status = s.get("status")
            if status == STATUS_PASS:
                mark = "[PASS]"
            elif status == STATUS_FAIL:
                mark = "[FAIL]"
            elif status == STATUS_SKIP:
                mark = "[SKIP]"
            else:
                mark = "[INFO]"
            lines.append("%s %s" % (mark, s.get("name", "")))
            if s.get("summary"):
                lines.append("   %s" % s["summary"])
            for c in s.get("checks", []):
                cm = "ok " if c["ok"] else "NG "
                exp = "" if c["expected"] is None else "（期待: %s）" % c["expected"]
                act = "" if c["actual"] is None else " = %s" % c["actual"]
                msg = (" / " + c["message"]) if c["message"] else ""
                lines.append("     [%s] %-26s%s%s%s" % (cm, c["name"], exp, act, msg))

        lines.append(bar)
        lines.append("総合判定: %s" % self.overall_status)
        if self.summary:
            lines.append("   %s" % self.summary)
        lines.append(bar)

        lines.append("【次フェーズへの課題整理】")
        if not self.issues:
            lines.append("   （特になし）")
        for it in self.issues:
            lines.append("   [%s][%s] %s" % (it["id"], it["severity"], it["title"]))
            lines.append("       %s" % it["detail"])
            lines.append("       対応: %s" % it["suggested_action"])
        lines.append(bar)
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Markdown（飛行試験結果レポートの主成果物）
    # ------------------------------------------------------------------
    def format_markdown(self) -> str:
        lines: List[str] = []
        lines.append("# %s" % TITLE)
        lines.append("")
        lines.append("- 開始: `%s`" % self.started_at)
        lines.append("- 終了: `%s`" % self.finished_at)
        lines.append("- 総合判定: **`%s`**" % self.overall_status)
        lines.append("")

        if self.inputs:
            lines.append("## 入力")
            lines.append("")
            lines.append("```")
            for k, v in self.inputs.items():
                lines.append("%s = %s" % (k, v))
            lines.append("```")
            lines.append("")

        if self.spec:
            lines.append("## 判定基準")
            lines.append("")
            lines.append("| 項目 | 値 |")
            lines.append("|---|---|")
            for k, v in self.spec.items():
                if k == "label":
                    continue
                lines.append("| `%s` | %s |" % (k, _fmt(v)))
            lines.append("")

        lines.append("## 評価結果")
        lines.append("")
        for s in self.sections:
            lines.append("### %s" % s.get("name", ""))
            lines.append("")
            lines.append("- **状態**: `%s`" % s.get("status"))
            if s.get("summary"):
                lines.append("- **要約**: %s" % s["summary"])
            if s.get("checks"):
                lines.append("")
                lines.append("| 判定 | 項目 | 期待 | 実測 | 備考 |")
                lines.append("|---|---|---|---|---|")
                for c in s["checks"]:
                    lines.append("| %s | `%s` | %s | %s | %s |" % (
                        "OK" if c["ok"] else "NG",
                        c["name"],
                        _fmt(c["expected"]),
                        _fmt(c["actual"]),
                        c.get("message", ""),
                    ))
            lines.append("")

        lines.append("## 次フェーズへの課題整理")
        lines.append("")
        if not self.issues:
            lines.append("（特になし）")
        else:
            lines.append("| ID | 深刻度 | カテゴリ | 課題 | 対応方針 |")
            lines.append("|---|---|---|---|---|")
            for it in self.issues:
                lines.append("| %s | %s | %s | %s | %s |" % (
                    it["id"], it["severity"], it["category"], it["title"],
                    it["suggested_action"]))
                if it.get("detail"):
                    lines.append("| | | | %s | |" % it["detail"])
            lines.append("")

        if self.summary:
            lines.append("## 総括")
            lines.append("")
            lines.append(self.summary)
            lines.append("")
        return "\n".join(lines)


__all__ = ["STATUS_PASS", "STATUS_FAIL", "STATUS_SKIP", "STATUS_INFO",
           "TITLE", "utc_now_iso", "FlightReport"]


