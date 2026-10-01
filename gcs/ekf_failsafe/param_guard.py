#!/usr/bin/env python3
"""param_guard.py — ArduPilot パラメータ Golden 値の退行監視・自動修正バックエンド

Phase 3（飛行試験準備）の成果物。RTK-FIXED を ArduPilot EKF へ取り込み、測位劣化時の
フェイルセーフを有効化するための **ArduPilot パラメータ**（``gcs/ekf_failsafe/golden.py``
の ``GOLDEN_PARAMS``）が、フライトコントローラの自動設定や GLONASS 実験などによって
意図せず退行していないかを、MAVLink 経由で「飛行前チェック」として確認・自動修正する。

``gcs/backend/f9p_configurator.py``（52eb5・F9pConfigGuard）と同じ思想・戻り値スキーマ
（status / summary / checked / fixed / fix_failed / messages / transport / timestamp）を
採用しており、F9P レジスタ golden（52eb5）と ArduPilot パラメータ golden（本タスク）の
「二層 golden 照合」を統一的に扱える。

ArduPilot は ``PARAM_SET`` 受信時に自動で Flash/EEPROM へ即時書き込みするため、
``MAV_CMD_PREFLIGHT_STORAGE`` は使用しない（既存知見: archive/dronecan_gps_rtk/gps_can_verify/README.md）。

Usage:
    from gcs.ekf_failsafe.param_guard import ArduPilotParamGuard

    guard = ArduPilotParamGuard(device="/dev/ttyAMA0", baud=921600)
    result = guard.run_check_and_fix(fix=False)   # 照合のみ
    result = guard.run_check_and_fix(fix=True)    # 照合 + 自動修正
"""

from __future__ import annotations

import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# 実行位置に依存しない import（gcs/ekf_failsafe/golden.py を参照）
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from gcs.ekf_failsafe.golden import (  # noqa: E402
    ALL_PARAM_NAMES,
    GOLDEN_PARAMS,
    LABELS,
    PARAM_TYPES,
    values_equal,
    param_value_repr,
    group_of,
)

# pymavlink は実機（MAVLink）接続時のみ必要。import できなくてもモジュールは読める。
try:
    from pymavlink import mavutil  # noqa: F401
except ImportError:  # pragma: no cover - 実機なし環境
    mavutil = None  # type: ignore[assignment]

# 型タグ → MAV_PARAM_TYPE 属性名
_TYPE_TAG_TO_MAV = {
    "int8": "MAV_PARAM_TYPE_INT8",
    "int16": "MAV_PARAM_TYPE_INT16",
    "int32": "MAV_PARAM_TYPE_INT32",
    "uint8": "MAV_PARAM_TYPE_UINT8",
    "uint16": "MAV_PARAM_TYPE_UINT16",
    "float": "MAV_PARAM_TYPE_REAL32",
}

# 結果 status 値（F9pConfigGuard と同一語彙）
STATUS_PASS = "PASS"
STATUS_FIXED = "FIXED"
STATUS_FAIL = "FAIL"

# 観測対象の MAVLink メッセージ ID（GPS_RAW_INT=24 / EKF_STATUS_REPORT=193）
_GPS_RAW_INT_ID = 24
_EKF_STATUS_REPORT_ID = 193


class ArduPilotParamGuard:
    """ArduPilot パラメータ golden の退行監視・自動修正バックエンド（MAVLink）。

    Args:
        device: シリアルデバイスパス（例: /dev/ttyAMA0, COM8）。None で connection_string を使用。
        baud: シリアルボーレート（既定 921600 = Pixhawk6C TELEM1）。
        connection_string: ``mavutil.mavlink_connection()`` に渡す接続文字列
            （例: "tcp:192.168.1.100:5760", "udpin:0.0.0.0:14550"）。device より優先。
        golden: 監視対象 golden（省略時 GOLDEN_PARAMS）。
        labels: キーごとの表示名（省略時 LABELS）。
        timeout: MAVLink 応答待ちタイムアウト（秒）。
        logger: ロガー（省略時は新規作成）。
    """

    DEFAULT_BAUD = 921600

    def __init__(
        self,
        device: Optional[str] = None,
        baud: int = DEFAULT_BAUD,
        connection_string: Optional[str] = None,
        golden: Optional[Dict[str, float]] = None,
        labels: Optional[Dict[str, str]] = None,
        timeout: float = 3.0,
        logger: Optional[logging.Logger] = None,
    ):
        self.device = device
        self.baud = baud
        self.connection_string = connection_string
        self.timeout = timeout
        self.log = logger or logging.getLogger("ArduPilotParamGuard")

        self.golden: Dict[str, float] = dict(golden or GOLDEN_PARAMS)
        self.labels: Dict[str, str] = dict(labels or LABELS)
        # 表示順（golden に含まれるものだけ）
        self.order: List[str] = [n for n in ALL_PARAM_NAMES if n in self.golden]

        self._master = None

    # ------------------------------------------------------------------
    # トランスポート
    # ------------------------------------------------------------------
    def _connection_desc(self) -> str:
        if self.connection_string:
            return self.connection_string
        return "%s @ %d bps" % (self.device or "(auto)", self.baud)

    def _connect(self) -> None:
        if mavutil is None:
            raise RuntimeError(
                "pymavlink が必要です: pip install pymavlink（または ~/Mavlink_venv を有効化）")
        if self.connection_string:
            self._master = mavutil.mavlink_connection(self.connection_string, baud=self.baud)
        elif self.device:
            self._master = mavutil.mavlink_connection(self.device, baud=self.baud)
        else:
            raise RuntimeError("接続先を指定してください（--device または --tcp/--udp）")
        # heartbeat 待ち（target_system / target_component が確定する）
        self._master.wait_heartbeat(timeout=self.timeout)

    def _close(self) -> None:
        if self._master is not None:
            try:
                self._master.close()
            except Exception:  # noqa: BLE001
                pass
            self._master = None

    def _clear_buffer(self, timeout: float = 0.05) -> int:
        """受信バッファの残メッセージを破棄し、破棄件数を返す。"""
        count = 0
        while True:
            msg = self._master.recv_match(blocking=False, timeout=timeout)
            if msg is None:
                break
            count += 1
        return count

    # ------------------------------------------------------------------
    # 型変換・値比較
    # ------------------------------------------------------------------
    def _mav_param_type(self, name: str) -> int:
        tag = PARAM_TYPES.get(name, "float")
        attr = _TYPE_TAG_TO_MAV.get(tag, "MAV_PARAM_TYPE_REAL32")
        return getattr(mavutil.mavlink, attr)

    def _values_equal(self, expected: float, actual: Optional[float], name: str) -> bool:
        return values_equal(expected, actual, name)

    # ------------------------------------------------------------------
    # 読取 / 書込
    # ------------------------------------------------------------------
    def _read_param(self, name: str, timeout: Optional[float] = None) -> Optional[float]:
        """PARAM_REQUEST_READ → PARAM_VALUE で 1 パラメータを読む。未受信なら None。"""
        timeout = self.timeout if timeout is None else timeout
        self._clear_buffer()
        self._master.mav.param_request_read_send(
            self._master.target_system, self._master.target_component, name.encode(), -1)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            msg = self._master.recv_match(type="PARAM_VALUE", blocking=False, timeout=0.05)
            if msg is None:
                continue
            pname = getattr(msg, "param_id", "")
            if isinstance(pname, bytes):
                pname = pname.decode("utf-8", "replace")
            pname = pname.rstrip("\x00")
            if pname == name:
                return float(msg.param_value)
        return None

    def _read_param_aliased(self, name: str) -> Optional[float]:
        """読取（GPS_TYPE は GPS1_TYPE にフォールバック）。"""
        value = self._read_param(name)
        if value is None and name == "GPS_TYPE":
            value = self._read_param("GPS1_TYPE")
        return value

    def _read_all(self) -> Dict[str, Optional[float]]:
        """golden の全パラメータを読み取る。"""
        current: Dict[str, Optional[float]] = {}
        for name in self.order:
            current[name] = self._read_param_aliased(name)
        return current

    def _set_param(self, name: str, value: float) -> bool:
        """PARAM_SET 後、読み戻して反映を確認する（ArduPilot は自動で EEPROM 保存）。"""
        self._master.mav.param_set_send(
            self._master.target_system, self._master.target_component,
            name.encode(), float(value), self._mav_param_type(name))
        time.sleep(0.15)
        actual = self._read_param(name, timeout=1.5)
        return self._values_equal(value, actual, name)

    # ------------------------------------------------------------------
    # メイン API
    # ------------------------------------------------------------------
    def run_check_and_fix(self, fix: bool = True) -> Dict[str, Any]:
        """ワンクリック飛行前チェック: 現状確認 → 退行検知時は自動修正。

        Returns:
            dict: status（PASS / FIXED / FAIL）と UI 表示用メッセージを含む
                （F9pConfigGuard.run_check_and_fix() と同じスキーマ）。
        """
        result: Dict[str, Any] = {
            "status": STATUS_FAIL,
            "checked": {},
            "fixed": [],
            "fix_failed": [],
            "messages": [],
            "summary": "",
            "transport": {"mode": "mavlink", "connection": self._connection_desc()},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        try:
            self._connect()
        except Exception as e:  # noqa: BLE001
            msg = "接続に失敗しました: %s" % e
            result["messages"].append(msg)
            result["summary"] = msg
            self._close()
            return result

        try:
            try:
                current = self._read_all()
            except Exception as e:  # noqa: BLE001
                msg = "パラメータの読取に失敗しました: %s" % e
                result["messages"].append(msg)
                result["summary"] = msg
                return result

            mismatches: List[str] = []
            for name in self.order:
                expected = self.golden[name]
                actual = current.get(name)
                ok = self._values_equal(expected, actual, name)
                result["checked"][name] = {
                    "key": name,
                    "key_display": name,
                    "label": self.labels.get(name, name),
                    "group": group_of(name),
                    "expected": expected,
                    "actual": actual,
                    "ok": ok,
                }
                if ok:
                    result["messages"].append(
                        "  OK   %-20s = %s（%s）"
                        % (name, param_value_repr(name, actual), self.labels.get(name, name)))
                else:
                    mismatches.append(name)
                    result["messages"].append(
                        "  NG   %-20s = %s（期待値 %s / %s）"
                        % (name, param_value_repr(name, actual),
                           param_value_repr(name, expected), self.labels.get(name, name)))

            # 退行なし
            if not mismatches:
                result["status"] = STATUS_PASS
                result["summary"] = "すべての ArduPilot パラメータが正常です（修正不要）"
                return result

            # 照合のみ
            if not fix:
                result["status"] = STATUS_FAIL
                result["summary"] = "%d 件の退行を検出（自動修正は無効）" % len(mismatches)
                return result

            # 自動修正
            fixed: List[str] = []
            failed: List[str] = []
            for name in mismatches:
                try:
                    if self._set_param(name, self.golden[name]):
                        fixed.append(name)
                    else:
                        failed.append(name)
                except Exception as e:  # noqa: BLE001
                    self.log.warning("修正失敗 %s: %s", name, e)
                    failed.append(name)

            # 再検証（実測値を checked に反映）
            current2 = self._read_all()
            for name in self.order:
                actual = current2.get(name)
                result["checked"][name]["actual"] = actual
                result["checked"][name]["ok"] = self._values_equal(
                    self.golden[name], actual, name)

            still_bad = [n for n in mismatches
                         if not self._values_equal(self.golden[n], current2.get(n), n)]
            if not still_bad:
                result["status"] = STATUS_FIXED
                result["fixed"] = list(mismatches)
                result["summary"] = ("%d 件の退行を自動修正しました（EEPROM 保存済み）"
                                     % len(mismatches))
            else:
                result["status"] = STATUS_FAIL
                result["fixed"] = fixed
                result["fix_failed"] = still_bad
                result["summary"] = ("修正後も %d 件が正常化しませんでした: %s"
                                     % (len(still_bad), ", ".join(still_bad)))
            return result
        finally:
            self._close()

    def check(self) -> Dict[str, Any]:
        """現状確認のみ行う（自動修正なし）。"""
        return self.run_check_and_fix(fix=False)

    # ------------------------------------------------------------------
    # RTK 喪失時挙動の観測（要件 (2) の動的検証用）
    # ------------------------------------------------------------------
    def enable_streams(self, interval_hz: float = 5.0) -> None:
        """GPS_RAW_INT / EKF_STATUS_REPORT の MAVLink ストリームを要求する（ベストエフォート）。"""
        if mavutil is None or self._master is None:
            return
        interval_us = int(1e6 / max(1.0, interval_hz))
        for msg_id in (_GPS_RAW_INT_ID, _EKF_STATUS_REPORT_ID):
            try:
                self._master.mav.command_long_send(
                    self._master.target_system, self._master.target_component,
                    mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL, 0,
                    float(msg_id), float(interval_us), 0.0, 0.0, 0.0, 0.0, 0.0)
            except Exception:  # noqa: BLE001
                pass

    def sample(self) -> Dict[str, Optional[int]]:
        """最新の RTK fix_type と EKF フラグを 1 回読む（受信できなければ None）。"""
        if self._master is None:
            return {"fix_type": None, "ekf_flags": None}
        fix_type: Optional[int] = None
        ekf_flags: Optional[int] = None
        msg = self._master.recv_match(type="GPS_RAW_INT", blocking=False, timeout=0.05)
        if msg is not None:
            fix_type = int(getattr(msg, "fix_type", -1))
            if fix_type < 0:
                fix_type = None
        msg = self._master.recv_match(type="EKF_STATUS_REPORT", blocking=False, timeout=0.05)
        if msg is not None:
            ekf_flags = int(getattr(msg, "flags", 0))
        return {"fix_type": fix_type, "ekf_flags": ekf_flags}

    def observe_fix_series(
        self,
        duration: float,
        interval: float = 1.0,
        on_event: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> List[Dict[str, Any]]:
        """RTK fix_type / EKF フラグの時系列を duration 秒間観測する。"""
        series: List[Dict[str, Any]] = []
        start = time.monotonic()
        last = 0.0
        last_progress = 0.0
        self.enable_streams()
        while time.monotonic() - start < duration:
            s = self.sample()
            now = time.monotonic()
            if s["fix_type"] is not None and now - last >= interval:
                last = now
                series.append({
                    "t": now - start,
                    "ts": datetime.now().strftime("%H:%M:%S.%f")[:-3],
                    "fix_type": s["fix_type"],
                    "ekf_flags": s["ekf_flags"],
                })
            if on_event is not None and now - last_progress >= 1.0:
                last_progress = now
                on_event({
                    "type": "progress",
                    "elapsed_sec": now - start,
                    "duration_sec": duration,
                    "fix_type": s["fix_type"],
                    "ekf_flags": s["ekf_flags"],
                })
            time.sleep(min(0.05, interval))
        return series

    def observe(self, duration: float, interval: float = 1.0,
                on_event: Optional[Callable[[Dict[str, Any]], None]] = None
                ) -> List[Dict[str, Any]]:
        """接続 → RTK fix_type / EKF フラグ観測 → 切断 を一括実行する。"""
        if self._master is None:
            self._connect()
        try:
            return self.observe_fix_series(duration, interval, on_event)
        finally:
            self._close()


__all__ = [
    "ArduPilotParamGuard",
    "STATUS_PASS", "STATUS_FIXED", "STATUS_FAIL",
]
