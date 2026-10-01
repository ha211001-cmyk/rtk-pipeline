#!/usr/bin/env python3
"""F9P コンフィグ退行監視・自動修正バックエンド（ロードマップ Phase 1 スクリプト①）

RTK-FIXED 到達の必須条件である U-blox ZED-F9P のレジスタ設定（Golden 値）が、
フライトコントローラの自動設定などによって意図せず退行していないかを「飛行前チェック」として
ワンクリックで現状確認・自動修正（Flash 保存）するバックエンドクラス。

対象 Golden 値:
    CFG-NAVHPG-DGNSSMODE    = 3    (RTK Fixed)
    CFG-NAVSPG-DYNMODEL     = 7    (Airborne <2g)
    CFG-RATE-MEAS           = 200  (5 Hz / 測位間隔 200 ms)
    CFG-UART1INPROT-RTCM3X  = 1    (UART1 RTCM3 入力許可)

アーキテクチャ（ハイブリッド方式）:
    - Phase 1 (現在): GCS 集中型
        地上の GCS 用 PC 上で実行し、Wi-Fi 経由で機体（Raspberry Pi 5）の IP を指定して
        TCP 通信（DroneCAN Serial Forwarding）で F9P のシリアルに到達する。
    - Phase 3 (将来): エッジ分散型
        各機体の Raspberry Pi 5 内にデプロイし、host=127.0.0.1 で自己完結させる。
        本モジュールはトランスポートを抽象化しているため、host を差し替えるだけで
        シームレスに移行できる。

既存資産の再利用:
    本モジュールは archive/base_station_verify/rtcm_compare/f9p_configurator_v2.py を import して
    LAYER_ALL（RAM + BBR + Flash）等を再利用する。既存ファイルの改変は行わない。
    （NTRIP / イチミルの構成 A は使用しない）

Usage:
    from gcs.backend.f9p_configurator import F9pConfigGuard

    guard = F9pConfigGuard(host="192.168.1.100", port=5001)  # Phase 1: 機体の IP
    result = guard.run_check_and_fix()
    print(result["status"])   # PASS / FIXED / FAIL

注（Phase 0 統合計画 §4.2）:
    F9P 設定の「全キー write-verify」の正典は ``gcs/rtk_tools/f9p_config_all.py``
    （``F9pAllConfigurator``）である。本モジュールの ``F9pConfigGuard`` は、飛行前
    チェック用途の「Golden 4 キー退行監視・自動修正」という狭い役割を担う後方互換
    コンポーネントとして残置する（``preflight/``・``ekf_failsafe/`` が依存）。
"""

from __future__ import annotations

import argparse
import logging
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from pyubx2 import UBXMessage, UBXReader, UBX_PROTOCOL
from pyubx2.ubxhelpers import attsiz, bytes2val, cfgname2key

# ---------------------------------------------------------------------------
# 既存 f9p_configurator_v2.py の再利用（import・参照。既存ファイルは改変しない）
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[2]
_V2_DIR = _REPO_ROOT / "archive" / "base_station_verify" / "rtcm_compare"
if _V2_DIR.is_dir() and str(_V2_DIR) not in sys.path:
    sys.path.insert(0, str(_V2_DIR))

try:
    from f9p_configurator_v2 import LAYER_ALL, F9pConfiguratorV2  # noqa: F401
except Exception:  # noqa: BLE001  # 依存が無い環境でも import できるようフォールバック
    LAYER_ALL = 7  # RAM + BBR + Flash
    F9pConfiguratorV2 = None

# ---------------------------------------------------------------------------
# Golden 値（RTK-FIXED 到達の必須レジスタ正値）の辞書化
# ---------------------------------------------------------------------------
GOLDEN_VALUES: Dict[str, int] = {
    "CFG_NAVHPG_DGNSSMODE": 3,    # RTK Fixed
    "CFG_NAVSPG_DYNMODEL": 7,     # Airborne <2g
    "CFG_RATE_MEAS": 200,         # 5 Hz（測位間隔 200 ms）
    "CFG_UART1INPROT_RTCM3X": 1,  # UART1 に RTCM3 入力を許可
}

GOLDEN_LABELS: Dict[str, str] = {
    "CFG_NAVHPG_DGNSSMODE": "DGNSSモード (RTK Fixed)",
    "CFG_NAVSPG_DYNMODEL": "動的モデル (Airborne <2g)",
    "CFG_RATE_MEAS": "測位レート (5 Hz)",
    "CFG_UART1INPROT_RTCM3X": "UART1 RTCM3 入力許可",
}

# run_check_and_fix() が返す status 値
STATUS_PASS = "PASS"
STATUS_FIXED = "FIXED"
STATUS_FAIL = "FAIL"

# CFG キー ID の上位ニブル（bits 28-31）から値のバイト数を引く（UBX_CONFIG_STORSIZE 相当）
_CFG_SIZE_BYTES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8}


class F9pConfigError(Exception):
    """F9P コンフィグ操作（接続・読取・書込）のエラー。"""


class TcpTransport:
    """DroneCAN Serial Forwarding の TCP ストリームを pyserial 風インターフェースで包む。

    pyubx2 の UBXReader は ``read(size)`` が正確に size バイト（または空）を返すことを
    期待するため、ここでは ``read(size)`` を「size バイト到達 or タイムアウトまで貯める」
    セマンティクスで実装する。
    """

    def __init__(self, host: str, port: int, timeout: float = 3.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._sock: Optional[socket.socket] = None

    def connect(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect((self.host, self.port))
        self._sock = sock

    def write(self, data: bytes) -> None:
        if self._sock is None:
            raise F9pConfigError("TCP 接続が確立されていません")
        self._sock.sendall(data)

    def flush(self) -> None:
        # TCP は sendall() で送信済みのため no-op
        pass

    def read(self, size: int) -> bytes:
        if self._sock is None:
            return b""
        if size <= 0:
            return b""
        deadline = time.monotonic() + self.timeout
        buf = bytearray()
        while len(buf) < size:
            try:
                chunk = self._sock.recv(size - len(buf))
            except socket.timeout:
                break
            except OSError:
                break
            if not chunk:
                break
            buf.extend(chunk)
            if time.monotonic() >= deadline:
                break
        return bytes(buf)

    def reset_input_buffer(self) -> None:
        """受信バッファに溜まった残りデータを破棄する。"""
        if self._sock is None:
            return
        try:
            self._sock.setblocking(False)
            while True:
                chunk = self._sock.recv(4096)
                if not chunk:
                    break
        except OSError:
            pass
        finally:
            self._sock.setblocking(True)
            self._sock.settimeout(self.timeout)

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None


class F9pConfigGuard:
    """RTK-FIXED 必須レジスタ（Golden 値）の退行監視・自動修正バックエンド。

    Args:
        host: DroneCAN Serial Forwarding のホスト。Phase 1 は機体（Raspberry Pi 5）の IP、
            Phase 3 は 127.0.0.1。
        port: 同 TCP ポート。
        serial_port: （オプション）TCP を使わず直接シリアル接続する場合のデバイスパス。
        baudrate: serial_port 使用時のボーレート。
        golden: 監視する Golden 値の辞書（省略時は GOLDEN_VALUES）。
        labels: キーごとの表示名（省略時は GOLDEN_LABELS）。
        logger: ロガー（省略時は新規作成）。
        timeout: UBX 応答待ちタイムアウト（秒）。
        flash_wait_seconds: Flash 書込み後の再起動待ち時間（秒）。
    """

    DEFAULT_HOST = "127.0.0.1"
    DEFAULT_PORT = 5001
    DEFAULT_BAUDRATE = 115200

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        serial_port: Optional[str] = None,
        baudrate: int = DEFAULT_BAUDRATE,
        golden: Optional[Dict[str, int]] = None,
        labels: Optional[Dict[str, str]] = None,
        logger: Optional[logging.Logger] = None,
        timeout: float = 3.0,
        flash_wait_seconds: float = 3.0,
    ):
        self.host = host or self.DEFAULT_HOST
        self.port = int(port if port is not None else self.DEFAULT_PORT)
        self.serial_port = serial_port
        self.baudrate = baudrate
        self.timeout = timeout
        self.flash_wait_seconds = flash_wait_seconds
        self.log = logger or logging.getLogger("F9pConfigGuard")

        self.golden: Dict[str, int] = dict(golden or GOLDEN_VALUES)
        self.labels: Dict[str, str] = dict(labels or GOLDEN_LABELS)

        # キー名 → キーID / 型 / バイト数を事前解決
        self._key_ids: Dict[int, str] = {}
        self._key_sizes: Dict[int, int] = {}
        self._key_types: Dict[str, str] = {}
        for name in self.golden:
            kid, typ = cfgname2key(name)
            self._key_ids[kid] = name
            self._key_sizes[kid] = attsiz(typ)
            self._key_types[name] = typ

        self._stream = None

    # ------------------------------------------------------------------
    # トランスポート
    # ------------------------------------------------------------------
    def _open(self) -> None:
        if self.serial_port:
            import serial  # 直接シリアル使用時のみ遅延 import

            self._stream = serial.Serial(self.serial_port, self.baudrate, timeout=self.timeout)
            time.sleep(0.3)
            self._stream.reset_input_buffer()
        else:
            tcp = TcpTransport(self.host, self.port, timeout=self.timeout)
            tcp.connect()
            self._stream = tcp

    def _close(self) -> None:
        if self._stream is not None:
            try:
                self._stream.close()
            except Exception:
                pass
            self._stream = None

    def _send(self, msg: bytes) -> None:
        self._stream.write(msg)
        self._stream.flush()

    def _read_ubx(self, cls: int, mid: int, timeout: Optional[float] = None) -> Optional[bytes]:
        """指定クラス・ID の UBX メッセージを待ち受けて生バイト列を返す。"""
        timeout = self.timeout if timeout is None else timeout
        # pyubx2 では msg_cls / msg_id は bytes（例: b'\\x06'）で比較する
        cls_b = cls.to_bytes(1, "big") if isinstance(cls, int) else cls
        mid_b = mid.to_bytes(1, "big") if isinstance(mid, int) else mid
        ubr = UBXReader(self._stream, protfilter=UBX_PROTOCOL)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                raw, parsed = ubr.read()
                if parsed is not None and parsed.msg_cls == cls_b and parsed.msg_id == mid_b:
                    return raw
            except Exception:
                time.sleep(0.02)
        return None


    # ------------------------------------------------------------------
    # 現状確認（UBX-CFG-VALGET）
    # ------------------------------------------------------------------
    def _poll_golden(self) -> Dict[str, int]:
        self._stream.reset_input_buffer()
        keys = list(self.golden.keys())
        self._send(UBXMessage.config_poll(0, 0, keys).serialize())
        raw = self._read_ubx(0x06, 0x8B)  # CFG-VALGET
        if not raw or len(raw) < 10:
            raise F9pConfigError("CFG-VALGET の応答を受信できませんでした（タイムアウト）")
        return self._parse_valget(raw)

    def _parse_valget(self, raw: bytes) -> Dict[str, int]:
        """CFG-VALGET 応答（raw UBX フレーム）を {キー名: 値} に変換する。"""
        payload = raw[6:-2]  # ヘッダ 6 バイト + チェックサム 2 バイトを除く
        pos = 4  # version(1) + layer(1) + position(2)
        result: Dict[str, int] = {}
        while pos + 4 <= len(payload):
            kid = int.from_bytes(payload[pos:pos + 4], "little")
            pos += 4
            name = self._key_ids.get(kid)
            if name is None:
                # 想定外キーはサイズ分だけ読み飛ばす
                size = _CFG_SIZE_BYTES.get((kid >> 28) & 0x0F, 1)
                pos += size
                continue
            size = self._key_sizes[kid]
            if pos + size > len(payload):
                break
            result[name] = bytes2val(payload[pos:pos + size], self._key_types[name])
            pos += size
        return result

    # ------------------------------------------------------------------
    # 自動修正（UBX-CFG-VALSET / layer=7）
    # ------------------------------------------------------------------
    def _apply_fix(self, mismatches: Sequence[str]) -> None:
        cfg = [(name, self.golden[name]) for name in mismatches]
        # 確実な Flash 永続化: layer=7（RAM + BBR + Flash）
        self._send(UBXMessage.config_set(LAYER_ALL, 0, cfg).serialize())

    def _reverify(self, attempts: int = 3):
        """修正後の再ポーリング。失敗時は最大 attempts 回リトライする。"""
        last_err: Optional[Exception] = None
        for i in range(attempts):
            try:
                return self._poll_golden(), None
            except Exception as e:  # noqa: BLE001
                last_err = e
                if i < attempts - 1:
                    self.log.warning("再検証 %d/%d 失敗: %s", i + 1, attempts, e)
                    time.sleep(1.0)
                    # Flash 書込みで F9P / Serial Forwarding が再起動した場合に備えて再接続
                    try:
                        self._close()
                        self._open()
                    except Exception as reconnect_err:  # noqa: BLE001
                        self.log.warning("再接続に失敗: %s", reconnect_err)
        return None, last_err


    # ------------------------------------------------------------------
    # メイン API
    # ------------------------------------------------------------------
    def run_check_and_fix(
        self,
        fix: bool = True,
        host: Optional[str] = None,
        port: Optional[int] = None,
    ) -> Dict[str, Any]:
        """ワンクリック飛行前チェック: 現状確認 → 退行検知時は自動修正（Flash 保存）。

        Returns:
            dict: 少なくとも status（PASS / FIXED / FAIL）と UI 表示用メッセージを含む。
        """
        if host is not None:
            self.host = host
        if port is not None:
            self.port = int(port)

        result: Dict[str, Any] = {
            "status": STATUS_FAIL,
            "checked": {},
            "fixed": [],
            "fix_failed": [],
            "messages": [],
            "summary": "",
            "layer": LAYER_ALL,
            "transport": self._transport_info(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        try:
            self._open()
        except Exception as e:  # noqa: BLE001
            msg = f"接続に失敗しました: {e}"
            result["messages"].append(msg)
            result["summary"] = msg
            self._close()
            self._emit(result)
            return result

        try:
            # 1) 現状確認
            try:
                current = self._poll_golden()
            except Exception as e:  # noqa: BLE001
                msg = f"レジスタの読取に失敗しました: {e}"
                result["messages"].append(msg)
                result["summary"] = msg
                self._emit(result)
                return result

            mismatches: List[str] = []
            for name in self.golden:
                expected = self.golden[name]
                actual = current.get(name)
                ok = actual is not None and actual == expected
                label = self.labels.get(name, name)
                result["checked"][name] = {
                    "key": name,
                    "key_display": self._display_key(name),
                    "label": label,
                    "expected": expected,
                    "actual": actual,
                    "ok": ok,
                }
                if ok:
                    result["messages"].append(
                        f"  OK   {self._display_key(name):26s} = {actual}（{label}）")
                else:
                    mismatches.append(name)
                    result["messages"].append(
                        f"  NG   {self._display_key(name):26s} = {actual}"
                        f"（期待値 {expected} / {label}）")

            # 2) 退行なし
            if not mismatches:
                result["status"] = STATUS_PASS
                result["summary"] = "すべての Golden 値が正常です（修正不要）"
                self._emit(result)
                return result

            # 3) 自動修正（チェックのみの場合はここで終了）
            if not fix:
                result["status"] = STATUS_FAIL
                result["summary"] = f"{len(mismatches)} 件の退行を検出（自動修正は無効）"
                self._emit(result)
                return result

            self.log.info("退行 %d 件を検出。layer=%d で自動修正します: %s",
                          len(mismatches), LAYER_ALL, ", ".join(mismatches))
            try:
                self._apply_fix(mismatches)
            except Exception as e:  # noqa: BLE001
                msg = f"自動修正（UBX-CFG-VALSET）に失敗しました: {e}"
                result["messages"].append(msg)
                result["summary"] = msg
                result["fix_failed"] = list(mismatches)
                self._emit(result)
                return result

            # Flash 書込み後は F9P のコンフィグサブシステムが再起動するため待機
            time.sleep(self.flash_wait_seconds)

            # 4) 再検証
            current, err = self._reverify()
            if current is None:
                msg = f"自動修正後の再検証に失敗しました: {err}"
                result["messages"].append(msg)
                result["summary"] = msg
                result["fix_failed"] = list(mismatches)
                self._emit(result)
                return result

            still_bad = [n for n in self.golden if current.get(n) != self.golden[n]]
            fixed = [n for n in mismatches if n not in still_bad]

            if not still_bad:
                result["status"] = STATUS_FIXED
                result["fixed"] = list(mismatches)
                result["summary"] = (
                    f"{len(mismatches)} 件の退行を自動修正し、"
                    f"Flash（layer={LAYER_ALL}）に保存しました")
            else:
                result["status"] = STATUS_FAIL
                result["fixed"] = fixed
                result["fix_failed"] = still_bad
                result["summary"] = (
                    f"修正後も {len(still_bad)} 件が正常化しませんでした: "
                    f"{', '.join(self._display_key(n) for n in still_bad)}")

            # 再検証後の実測値を checked に反映
            for name in self.golden:
                actual = current.get(name)
                result["checked"][name]["actual"] = actual
                result["checked"][name]["ok"] = (
                    actual is not None and actual == self.golden[name])

            self._emit(result)
            return result
        finally:
            self._close()

    def check(self, host: Optional[str] = None, port: Optional[int] = None) -> Dict[str, Any]:
        """現状確認のみ行う（自動修正なし）。"""
        return self.run_check_and_fix(fix=False, host=host, port=port)


    # ------------------------------------------------------------------
    # ユーティリティ
    # ------------------------------------------------------------------
    @staticmethod
    def _display_key(name: str) -> str:
        """pyubx2 内部のアンダースコア表記を、u-blox 標準のハイフン表記に変換する。"""
        return name.replace("_", "-")

    def _transport_info(self) -> Dict[str, Any]:
        if self.serial_port:
            return {"mode": "serial", "port": self.serial_port, "baudrate": self.baudrate}
        return {"mode": "tcp", "host": self.host, "port": self.port}

    def _emit(self, result: Dict[str, Any]) -> None:
        """結果を標準出力へ表示する（GCS GUI は戻り値の dict を利用する）。"""
        print("=" * 62)
        print("F9P コンフィグ退行監視・自動修正（飛行前チェック）")
        t = result["transport"]
        if t.get("mode") == "tcp":
            print(f"  トランスポート: TCP {t['host']}:{t['port']} (DroneCAN Serial Forwarding)")
        else:
            print(f"  トランスポート: Serial {t['port']} @ {t['baudrate']} bps")
        print("-" * 62)
        for line in result["messages"]:
            print(line)
        print("-" * 62)
        print(f"  結果: {result['status']} — {result['summary']}")
        if result.get("fixed"):
            print(f"  自動修正: {', '.join(self._display_key(n) for n in result['fixed'])}")
        if result.get("fix_failed"):
            print(f"  修正失敗: {', '.join(self._display_key(n) for n in result['fix_failed'])}")
        print("=" * 62)


# ---------------------------------------------------------------------------
# コマンドライン（ワンクリック実行用）
# ---------------------------------------------------------------------------
def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="F9P コンフィグ退行監視・自動修正（飛行前チェック）",
    )
    p.add_argument("--host", default=F9pConfigGuard.DEFAULT_HOST,
                   help="DroneCAN Serial Forwarding のホスト"
                        "（Phase 1: 機体の IP / Phase 3: 127.0.0.1）")
    p.add_argument("--port", type=int, default=F9pConfigGuard.DEFAULT_PORT,
                   help="同 TCP ポート")
    p.add_argument("--serial", default=None,
                   help="直接シリアル接続する場合のデバイスパス（例: /dev/ttyACM2, COM8）")
    p.add_argument("--baud", type=int, default=F9pConfigGuard.DEFAULT_BAUDRATE,
                   help="シリアル接続時のボーレート")
    p.add_argument("--no-fix", action="store_true",
                   help="現状確認のみ（自動修正を行わない）")
    p.add_argument("--timeout", type=float, default=3.0,
                   help="UBX 応答待ちタイムアウト（秒）")
    p.add_argument("--flash-wait", type=float, default=3.0,
                   help="Flash 書込み後の再起動待ち時間（秒）")
    p.add_argument("--log-level", default="INFO",
                   help="ログレベル（DEBUG / INFO / WARNING / ERROR）")
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _build_arg_parser().parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    guard = F9pConfigGuard(
        host=args.host,
        port=args.port,
        serial_port=args.serial,
        baudrate=args.baud,
        timeout=args.timeout,
        flash_wait_seconds=args.flash_wait,
    )
    result = guard.run_check_and_fix(fix=not args.no_fix)
    return 0 if result["status"] in (STATUS_PASS, STATUS_FIXED) else 1


if __name__ == "__main__":
    sys.exit(main())
