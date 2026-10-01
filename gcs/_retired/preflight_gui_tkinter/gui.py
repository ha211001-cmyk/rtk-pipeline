#!/usr/bin/env python3
"""gui.py — Phase 3 飛行前セルフテスト GUI（Tkinter）

接続設定は **IP アドレス + TCP ポート**（DroneCAN Serial Forwarding の単一エンドポイント）
に統一し、シリアルポート選択は持たない。

- 「セルフテスト実行」で Item 2（静的照合）+ Item 1/3/基地局レート（動的健全性）を
  1 コマンドで走らせ、PASS/FAIL の飛行前チェックリストを表示する。
- 実行はバックグラウンドスレッドで行い、イベントキュー経由で UI を更新する。
- TCP 切断（Wi-Fi 瞬断等）は RTK age の stale 検知と連動して検出し、
  「再接続」ボタン（手動）と「自動再接続」チェックボックス（バックグラウンドの
  リトライループ）の両方を提供する（5100f のリーダーは自動再接続しない前提）。

起動:
    python3 gcs/preflight/gui.py
"""

from __future__ import annotations

import queue
import sys
import threading
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    import tkinter as tk
    from tkinter import messagebox, scrolledtext, ttk
except Exception as _e:  # noqa: BLE001
    print("Tkinter が利用できません: %s" % _e)
    raise SystemExit(1)

from gcs.preflight.runner import PreflightRunner  # noqa: E402
from gcs.preflight.checklist import STATUS_PASS  # noqa: E402

# 状態ごとの表示色
_STATE_COLORS = {
    "connected": "#1a7f37",
    "connecting": "#9a6700",
    "reconnecting": "#bc4c00",
    "disconnected": "#cf222e",
}


class PreflightApp:
    """飛行前セルフテスト GUI アプリケーション。"""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("飛行前セルフテスト（Phase 3 / DroneCAN Serial Forwarding）")
        self.root.geometry("760x640")

        self.event_queue = queue.Queue()
        self.runner = PreflightRunner()
        self.running = False

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(100, self._poll_queue)

    # ------------------------------------------------------------------
    # UI 構築
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        pad = {"padx": 6, "pady": 4}

        # --- 接続設定 -----------------------------------------------------
        conn = ttk.LabelFrame(self.root, text="接続設定（DroneCAN Serial Forwarding / 単一エンドポイント）")
        conn.pack(fill="x", padx=10, pady=(10, 4))

        row = ttk.Frame(conn)
        row.pack(fill="x", **pad)
        ttk.Label(row, text="IP アドレス:").pack(side="left")
        self.host_var = tk.StringVar(value="192.168.1.100")
        ttk.Entry(row, textvariable=self.host_var, width=18).pack(side="left", padx=(4, 12))
        ttk.Label(row, text="TCP ポート:").pack(side="left")
        self.port_var = tk.StringVar(value="5001")
        ttk.Entry(row, textvariable=self.port_var, width=8).pack(side="left", padx=4)

        self.auto_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(conn, text="自動再接続（バックグラウンドのリトライループ）",
                        variable=self.auto_var).pack(anchor="w", **pad)
        self.auto_fix_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(conn, text="Item 2 で golden 退行を検知したら自動修正する",
                        variable=self.auto_fix_var).pack(anchor="w", **pad)

        # --- 実行ボタン ---------------------------------------------------
        btns = ttk.Frame(self.root)
        btns.pack(fill="x", padx=10, pady=4)
        self.run_btn = ttk.Button(btns, text="セルフテスト実行", command=self.on_run)
        self.run_btn.pack(side="left")
        self.reconnect_btn = ttk.Button(btns, text="再接続", command=self.on_reconnect,
                                        state="disabled")
        self.reconnect_btn.pack(side="left", padx=6)
        self.stop_btn = ttk.Button(btns, text="停止", command=self.on_stop, state="disabled")
        self.stop_btn.pack(side="left")

        # --- ステータス ---------------------------------------------------
        status = ttk.LabelFrame(self.root, text="ステータス")
        status.pack(fill="x", padx=10, pady=4)
        self.status_var = tk.StringVar(value="待機中（IP + ポートを確認して実行してください）")
        self.status_lbl = ttk.Label(status, textvariable=self.status_var, foreground="#333333")
        self.status_lbl.pack(anchor="w", **pad)

        grid = ttk.Frame(status)
        grid.pack(fill="x", **pad)
        self.conn_var = tk.StringVar(value="接続状態: -")
        self.fix_var = tk.StringVar(value="fix: -")
        self.age_var = tk.StringVar(value="RTK age: -")
        self.rtcm_var = tk.StringVar(value="RTCM: -")
        ttk.Label(grid, textvariable=self.conn_var).grid(row=0, column=0, sticky="w", padx=6)
        ttk.Label(grid, textvariable=self.fix_var).grid(row=0, column=1, sticky="w", padx=6)
        ttk.Label(grid, textvariable=self.age_var).grid(row=0, column=2, sticky="w", padx=6)
        ttk.Label(grid, textvariable=self.rtcm_var).grid(row=0, column=3, sticky="w", padx=6)

        # --- チェックリスト ---------------------------------------------
        result = ttk.LabelFrame(self.root, text="飛行前チェックリスト（PASS / FAIL）")
        result.pack(fill="both", expand=True, padx=10, pady=(4, 10))
        self.text = scrolledtext.ScrolledText(result, wrap="none", font=("Menlo", 11),
                                              state="disabled")
        self.text.pack(fill="both", expand=True, padx=4, pady=4)
        self.text.tag_config("PASS", foreground="#1a7f37")
        self.text.tag_config("FAIL", foreground="#cf222e")


    # ------------------------------------------------------------------
    # ボタンハンドラ
    # ------------------------------------------------------------------
    def _read_endpoint(self):
        host = self.host_var.get().strip()
        port_text = self.port_var.get().strip()
        try:
            port = int(port_text)
        except ValueError:
            messagebox.showerror("入力エラー", "TCP ポートは数値で入力してください。")
            return None, None
        return host, port

    def on_run(self) -> None:
        if self.running:
            return
        host, port = self._read_endpoint()
        if host is None:
            return
        if not host:
            messagebox.showerror("入力エラー", "IP アドレスを入力してください。")
            return

        self.running = True
        self._set_running_buttons(True)
        self._clear_checklist()
        self._set_status("セルフテストを開始します…", "connecting")

        config = {
            "reconnect": {"auto": self.auto_var.get()},
            "item2": {"auto_fix": self.auto_fix_var.get()},
        }
        self.runner = PreflightRunner(config)
        t = threading.Thread(target=self._worker, args=(host, port), daemon=True)
        t.start()

    def _worker(self, host: str, port: int) -> None:
        try:
            report = self.runner.run(host=host, port=port, auto_fix=self.auto_fix_var.get(),
                                     on_event=lambda ev: self.event_queue.put(ev))
            self.event_queue.put({"type": "done", "report": report})
        except Exception as e:  # noqa: BLE001
            self.event_queue.put({"type": "error", "message": str(e)})

    def on_reconnect(self) -> None:
        if self.runner is not None and self.runner.session is not None:
            self._set_status("再接続を試みます…", "reconnecting")
            t = threading.Thread(target=self._do_reconnect, daemon=True)
            t.start()

    def _do_reconnect(self) -> None:
        try:
            ok = self.runner.session.reconnect()
            self.event_queue.put({"type": "reconnected", "ok": ok})
        except Exception as e:  # noqa: BLE001
            self.event_queue.put({"type": "reconnected", "ok": False, "message": str(e)})

    def on_stop(self) -> None:
        self._set_status("停止を要求しました…", "disconnected")
        self.runner.request_stop()

    def on_close(self) -> None:
        self.runner.request_stop()
        self.root.destroy()

    # ------------------------------------------------------------------
    # イベント処理
    # ------------------------------------------------------------------
    def _poll_queue(self) -> None:
        try:
            while True:
                ev = self.event_queue.get_nowait()
                self._handle_event(ev)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    def _handle_event(self, ev: dict) -> None:
        etype = ev.get("type")
        if etype == "progress":
            self._update_progress(ev)
        elif etype == "state":
            self._update_state(ev)
        elif etype == "done":
            self._on_done(ev.get("report"))
        elif etype == "reconnected":
            if ev.get("ok"):
                self._set_status("再接続に成功しました", "connected")
            else:
                self._set_status("再接続に失敗: %s" % ev.get("message", ""), "disconnected")
        elif etype == "error":
            self._set_status("エラー: %s" % ev.get("message", ""), "disconnected")
            self._on_finish()


    def _update_progress(self, ev: dict) -> None:
        elapsed = ev.get("elapsed_sec", 0.0)
        duration = ev.get("duration_sec", 0.0)
        fix = ev.get("fix", "-")
        age_state = ev.get("rtk_age_state", "-")
        age_sec = ev.get("rtk_age_sec")
        rtcm = ev.get("rtcm_total", 0)
        conn = ev.get("connection", {})
        self.fix_var.set("fix: %s" % fix)
        age_txt = age_state if age_sec is None else "%.1fs [%s]" % (age_sec, age_state)
        self.age_var.set("RTK age: %s" % age_txt)
        self.rtcm_var.set("RTCM: %d msg" % rtcm)
        self.conn_var.set("接続状態: %s" % conn.get("state", "-"))
        self._set_status("観測中 %.1f/%.1f 秒（fix=%s / RTK age=%s / RTCM=%d）"
                         % (elapsed, duration, fix, age_state, rtcm), conn.get("state", "connected"))

    def _update_state(self, ev: dict) -> None:
        state = ev.get("state", "disconnected")
        self._set_status(ev.get("message", state), state)
        self.conn_var.set("接続状態: %s" % state)
        # 切断検知（RTK age stale / TCP 断）時は再接続ボタンを有効化して強調
        if state in ("disconnected", "reconnecting"):
            self.reconnect_btn.configure(state="normal")
        else:
            self.reconnect_btn.configure(state="normal" if self.running else "disabled")

    def _on_done(self, report) -> None:
        if report is not None:
            self._set_checklist(report.format_checklist(), report.overall_status())
            if report.overall_status() == STATUS_PASS:
                self._set_status("完了: GO（飛行可）", "connected")
            else:
                self._set_status("完了: NO-GO（飛行不可）", "disconnected")
        self._on_finish()

    def _on_finish(self) -> None:
        self.running = False
        self._set_running_buttons(False)

    # ------------------------------------------------------------------
    # UI 更新ヘルパー
    # ------------------------------------------------------------------
    def _set_running_buttons(self, running: bool) -> None:
        self.run_btn.configure(state="disabled" if running else "normal")
        self.reconnect_btn.configure(state="normal" if running else "disabled")
        self.stop_btn.configure(state="normal" if running else "disabled")

    def _set_status(self, text: str, state: str = "connected") -> None:
        self.status_var.set(text)
        self.status_lbl.configure(foreground=_STATE_COLORS.get(state, "#333333"))

    def _clear_checklist(self) -> None:
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")

    def _set_checklist(self, checklist: str, overall: str) -> None:
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", checklist)
        self.text.configure(state="disabled")


def main(argv=None) -> int:
    root = tk.Tk()
    PreflightApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())


