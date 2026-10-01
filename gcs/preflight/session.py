#!/usr/bin/env python3
"""session.py — 飛行前セルフテスト用の TCP セッション管理（単一エンドポイント）

DroneCAN Serial Forwarding の単一 TCP エンドポイント（Wi-Fi の IP + ポート）へ接続し、
② RTK ステータス（NAV-PVT）と ③ RTCM リンク監視（UBX-RXM-RTCM）のデータを
``CorrectionMonitor`` へ供給する接続層。

5100f（②③ の TCP 化）の ``RoverUbxReader`` は**自動再接続しない前提**のため、
本クラスが「切断検知 → 再接続」を担う。

切断検知は以下の 2 系統:
  1. リーダーのスレッド死亡（TCP 接続の完全断絶）
  2. RTK age の stale 検知（Wi-Fi 瞬断等で補正データが途切れた＝データ断絶）
    ※ 一度も受信していない ``no_data`` は「未受信」であり、切断とは区別する。

再接続は ``reconnect()``（GUI の再接続ボタン用）と
``start_auto_reconnect()``（バックグラウンドのリトライループ）を提供する。
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

# 実行位置に依存しない import
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from gcs.rtcm_monitor import CorrectionMonitor  # noqa: E402
from gcs.integration.sources import RoverUbxReader  # noqa: E402

# 接続状態
STATE_CONNECTING = "connecting"
STATE_CONNECTED = "connected"
STATE_DISCONNECTED = "disconnected"
STATE_RECONNECTING = "reconnecting"


class TcpSession:
    """単一 TCP エンドポイントへの接続管理（5100f リーダーをラップ）。"""

    def __init__(self, host: str, port: int, monitor: Optional[CorrectionMonitor] = None,
                 poll_interval: float = 1.0, timeout: float = 3.0,
                 on_state: Optional[Callable[[Dict[str, Any]], None]] = None):
        self.host = str(host)
        self.port = int(port)
        self.monitor = monitor or CorrectionMonitor()
        self.poll_interval = poll_interval
        self.timeout = timeout
        self.on_state = on_state

        self._reader: Optional[RoverUbxReader] = None
        self._lock = threading.Lock()
        self._state = STATE_DISCONNECTED
        self._last_error = ""

        # 自動再接続（バックグラウンドリトライループ）の状態
        self._auto_running = False
        self._auto_thread: Optional[threading.Thread] = None
        self._auto_check_interval = 2.0
        self._auto_retry_interval = 3.0
        self._auto_max_attempts = 0  # 0 = 無制限

    # ------------------------------------------------------------------
    # 状態
    # ------------------------------------------------------------------
    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    @property
    def last_error(self) -> str:
        with self._lock:
            return self._last_error

    def is_connected(self) -> bool:
        with self._lock:
            r = self._reader
        return r is not None and r._thread is not None and r._thread.is_alive()

    def rtk_age_state(self) -> str:
        return self.monitor.age_monitor.status()["state"]

    def is_stale(self) -> bool:
        """RTK age が stale（一度受信後に補正データが途切れた）かどうか。"""
        return self.monitor.age_monitor.status()["state"] == "stale"

    def is_disconnected(self) -> bool:
        """切断検知（リーダー死亡 or RTK age stale と連動）。"""
        with self._lock:
            r = self._reader
        if r is None:
            return True
        if r._thread is not None and not r._thread.is_alive():
            return True
        # RTK age の stale 検知（Wi-Fi 瞬断等によるデータ途切れ）と連動
        return self.is_stale()

    # ------------------------------------------------------------------
    # 接続 / 切断 / 再接続
    # ------------------------------------------------------------------
    def _emit(self, state: str, message: str = "", extra: Optional[Dict[str, Any]] = None) -> None:
        with self._lock:
            self._state = state
            if message and state in (STATE_DISCONNECTED, STATE_RECONNECTING):
                self._last_error = message
        if self.on_state is not None:
            ev = {"type": "state", "state": state, "message": message}
            if extra:
                ev.update(extra)
            try:
                self.on_state(ev)
            except Exception:  # noqa: BLE001
                pass

    def connect(self) -> bool:
        """5100f の RoverUbxReader を新規生成して接続する。"""
        self._emit(STATE_CONNECTING, "接続を開始します: TCP %s:%s" % (self.host, self.port))
        reader = RoverUbxReader(host=self.host, port=self.port,
                                monitor=self.monitor,
                                poll_interval=self.poll_interval,
                                timeout=self.timeout)
        ok = reader.start()
        with self._lock:
            self._reader = reader if ok else None
            if not ok:
                self._last_error = "TCP 接続に失敗: %s:%s" % (self.host, self.port)
        if ok:
            self._emit(STATE_CONNECTED, "接続済み: TCP %s:%s (DroneCAN Serial Forwarding)"
                       % (self.host, self.port))
        else:
            self._emit(STATE_DISCONNECTED, self.last_error)
        return ok

    def disconnect(self) -> None:
        with self._lock:
            r = self._reader
            self._reader = None
        if r is not None:
            r.close()
        self._emit(STATE_DISCONNECTED, "切断しました")

    def reconnect(self) -> bool:
        """古いリーダーを破棄し、新規リーダーで再接続する（再接続ボタン用）。"""
        self.disconnect()
        return self.connect()

    def close(self) -> None:
        self.stop_auto_reconnect()
        self.disconnect()

    # ------------------------------------------------------------------
    # バックグラウンド自動再接続（リトライループ）
    # ------------------------------------------------------------------
    def start_auto_reconnect(self, check_interval: float = 2.0,
                             retry_interval: float = 3.0,
                             max_attempts: int = 0) -> None:
        """切断を検知したらバックグラウンドで自動再接続を試みる。"""
        self._auto_check_interval = check_interval
        self._auto_retry_interval = retry_interval
        self._auto_max_attempts = max_attempts
        if self._auto_running:
            return
        self._auto_running = True
        self._auto_thread = threading.Thread(target=self._auto_loop, daemon=True)
        self._auto_thread.start()

    def stop_auto_reconnect(self) -> None:
        self._auto_running = False
        if self._auto_thread is not None:
            self._auto_thread.join(timeout=2)
            self._auto_thread = None

    def _auto_loop(self) -> None:
        while self._auto_running:
            if self.is_disconnected():
                self._emit(STATE_RECONNECTING,
                           "切断を検知しました（RTK age stale / TCP 断）。再接続します…")
                self._reconnect_until_ok()
            time.sleep(self._auto_check_interval)

    def _reconnect_until_ok(self) -> bool:
        attempts = 0
        while self._auto_running and self.is_disconnected():
            attempts += 1
            if self.reconnect():
                self._emit(STATE_CONNECTED, "再接続に成功しました（%d 回目）" % attempts,
                           {"attempt": attempts})
                return True
            if self._auto_max_attempts and attempts >= self._auto_max_attempts:
                self._emit(STATE_DISCONNECTED,
                           "再接続を %d 回試行しましたが失敗しました" % attempts,
                           {"attempt": attempts})
                return False
            time.sleep(self._auto_retry_interval)
        return False

    # ------------------------------------------------------------------
    # データ取得（GUI / ランナー用）
    # ------------------------------------------------------------------
    def sample(self) -> Optional[int]:
        with self._lock:
            r = self._reader
        return r.sample() if r is not None else None

    def snapshot(self) -> Dict[str, Any]:
        """監視スナップショットに接続状態を付加して返す。"""
        snap = self.monitor.snapshot()
        snap["connection"] = {
            "host": self.host,
            "port": self.port,
            "state": self.state,
            "connected": self.is_connected(),
            "stale": self.is_stale(),
        }
        return snap


__all__ = [
    "STATE_CONNECTING", "STATE_CONNECTED", "STATE_DISCONNECTED", "STATE_RECONNECTING",
    "TcpSession",
]
