#!/usr/bin/env python3
"""
F9P Configurator - ZED-F9P 基地局モード設定モジュール

TMODE3固定座標設定、MSM7 RTCM3メッセージ出力有効化、設定検証を行う。

Usage:
    from f9p_configurator import F9pConfigurator

    configurator = F9pConfigurator("/dev/ttyACM2", baudrate=38400)
    result = configurator.configure(lat=36.0751418, lon=136.2133477, alt=44.80)
"""

import logging
import time
from typing import Optional

import serial
from pyubx2 import UBXMessage, UBXReader, UBX_PROTOCOL

LAYER_ALL = 7  # RAM + BBR + FLASH

# --- RTCM3 メッセージ有効化リスト ---
_RTCM3_ENABLE = [
    # USBポート向け (PCでのログ検証用 /dev/ttyACM*)
    'CFG-MSGOUT-RTCM_3X_TYPE1006_USB',   # Station XYZ with antenna height
    'CFG-MSGOUT-RTCM_3X_TYPE1077_USB',   # GPS MSM7
    'CFG-MSGOUT-RTCM_3X_TYPE1087_USB',   # GLO MSM7
    'CFG-MSGOUT-RTCM_3X_TYPE1097_USB',   # GAL MSM7
    'CFG-MSGOUT-RTCM_3X_TYPE1127_USB',   # BDS MSM7
    'CFG-MSGOUT-RTCM_3X_TYPE1230_USB',   # GLO Bias

    # UART1ポート向け (ドローン/Pixhawk通信用)
    'CFG-MSGOUT-RTCM_3X_TYPE1006_UART1', # Station XYZ with antenna height
    'CFG-MSGOUT-RTCM_3X_TYPE1077_UART1', # GPS MSM7
    'CFG-MSGOUT-RTCM_3X_TYPE1087_UART1', # GLO MSM7
    'CFG-MSGOUT-RTCM_3X_TYPE1097_UART1', # GAL MSM7
    'CFG-MSGOUT-RTCM_3X_TYPE1127_UART1', # BDS MSM7
    'CFG-MSGOUT-RTCM_3X_TYPE1230_UART1', # GLO Bias
]

# --- RTCM3 メッセージ無効化リスト ---
_RTCM3_DISABLE = [
    # USB向け: 4072独自メッセージ + Type 1005 (1006と競合) + Type 1074 (MSM4, MSM7と重複)
    'CFG-MSGOUT-RTCM_3X_TYPE4072_0_USB',
    'CFG-MSGOUT-RTCM_3X_TYPE4072_1_USB',
    'CFG-MSGOUT-RTCM_3X_TYPE1005_USB',
    'CFG-MSGOUT-RTCM_3X_TYPE1074_USB',   # GPS MSM4 (MSM7で十分なため無効化)
    # UART1向け: 同上
    'CFG-MSGOUT-RTCM_3X_TYPE4072_0_UART1',
    'CFG-MSGOUT-RTCM_3X_TYPE4072_1_UART1',
    'CFG-MSGOUT-RTCM_3X_TYPE1005_UART1',
    'CFG-MSGOUT-RTCM_3X_TYPE1074_UART1',  # GPS MSM4 (MSM7で十分なため無効化)
]

# --- プロトコル出力許可 ---
_PROTOCOL_ENABLE = [
    'CFG-USBOUTPROT-RTCM3X',    # USBからのRTCM3出力許可
    'CFG-UART1OUTPROT-RTCM3X',  # UART1からのRTCM3出力許可
]

# --- NMEA 無効化 (UART1) ---
_NMEA_DISABLE = [
    'CFG-MSGOUT-NMEA_ID_GGA_UART1', 'CFG-MSGOUT-NMEA_ID_GLL_UART1',
    'CFG-MSGOUT-NMEA_ID_GSA_UART1', 'CFG-MSGOUT-NMEA_ID_GSV_UART1',
    'CFG-MSGOUT-NMEA_ID_RMC_UART1', 'CFG-MSGOUT-NMEA_ID_VTG_UART1',
    'CFG-MSGOUT-NMEA_ID_ZDA_UART1',
]

# --- UBX 無効化 (UART1) ---
_UBX_DISABLE = [
    'CFG-MSGOUT-UBX_NAV_STATUS_UART1', 'CFG-MSGOUT-UBX_NAV_DOP_UART1',
    'CFG-MSGOUT-UBX_NAV_SAT_UART1', 'CFG-MSGOUT-UBX_NAV_SIG_UART1',
]

# --- 検証用キーリスト ---
_ALL_VERIFY = [
    # USB
    'CFG-MSGOUT-RTCM_3X_TYPE1005_USB',
    'CFG-MSGOUT-RTCM_3X_TYPE1006_USB',
    'CFG-MSGOUT-RTCM_3X_TYPE1077_USB', 'CFG-MSGOUT-RTCM_3X_TYPE1087_USB',
    'CFG-MSGOUT-RTCM_3X_TYPE1097_USB',
    'CFG-MSGOUT-RTCM_3X_TYPE1127_USB', 'CFG-MSGOUT-RTCM_3X_TYPE1230_USB',
    'CFG-MSGOUT-RTCM_3X_TYPE4072_0_USB', 'CFG-MSGOUT-RTCM_3X_TYPE4072_1_USB',
    # UART1
    'CFG-MSGOUT-RTCM_3X_TYPE1005_UART1',
    'CFG-MSGOUT-RTCM_3X_TYPE1006_UART1',
    'CFG-MSGOUT-RTCM_3X_TYPE1077_UART1', 'CFG-MSGOUT-RTCM_3X_TYPE1087_UART1',
    'CFG-MSGOUT-RTCM_3X_TYPE1097_UART1',
    'CFG-MSGOUT-RTCM_3X_TYPE1127_UART1', 'CFG-MSGOUT-RTCM_3X_TYPE1230_UART1',
    'CFG-MSGOUT-RTCM_3X_TYPE4072_0_UART1', 'CFG-MSGOUT-RTCM_3X_TYPE4072_1_UART1',
]

_NAMES = {
    '1005': 'Station ARP', '1006': 'Station XYZ+AH',
    '1077': 'GPS MSM7', '1087': 'GLO MSM7', '1097': 'GAL MSM7',
    '1127': 'BDS MSM7', '1230': 'GLO Bias',
    '4072_0': 'ublox Prop0', '4072_1': 'ublox Prop1',
}


class F9pConfigurator:
    """ZED-F9P 基地局モード設定クラス

    TMODE3固定座標設定、MSM7 RTCM3メッセージ出力有効化、設定検証を行う。

    Args:
        serial_port: F9Pのシリアルポートパス (例: /dev/ttyACM2)
        baudrate: 設定用ボーレート (デフォルト: 38400)
        logger: ロガーインスタンス (省略時は新規作成)
    """

    def __init__(self, serial_port: str, baudrate: int = 38400,
                 logger: Optional[logging.Logger] = None):
        self.serial_port = serial_port
        self.baudrate = baudrate
        self.log = logger or logging.getLogger("F9pConfigurator")
        self._ser = None

    def _open(self) -> None:
        """シリアルポートを開く"""
        self._ser = serial.Serial(self.serial_port, self.baudrate, timeout=1.0)
        time.sleep(0.3)
        self._ser.reset_input_buffer()

    def _close(self) -> None:
        """シリアルポートを閉じる"""
        if self._ser and self._ser.is_open:
            self._ser.close()
            self._ser = None

    def _send(self, msg: bytes) -> None:
        """UBXメッセージを送信"""
        self._ser.write(msg)
        self._ser.flush()

    def _read_ubx(self, cls: int, mid: int, timeout: float = 3.0) -> Optional[bytes]:
        """指定クラス・IDのUBXメッセージを待ち受ける"""
        ubr = UBXReader(self._ser, protfilter=UBX_PROTOCOL)
        dl = time.time() + timeout
        while time.time() < dl:
            try:
                raw, parsed = ubr.read()
                if parsed and parsed.msg_cls == cls and parsed.msg_id == mid:
                    return raw
            except Exception:
                time.sleep(0.05)
        return None

    def reset_tmode3(self, save: bool = True) -> bool:
        """TMODE3固定モードをリセットする（無効化）

        単独測位（動的モード）で実際のGNSS位置を取得する前に、
        以前に保存された固定座標が出力されないようにする。

        Args:
            save: Trueの場合、RAM+BBR+Flashに保存

        Returns:
            設定成功ならTrue
        """
        self._open()
        try:
            cfg = [
                ('CFG-TMODE-MODE', 0),           # Disabled
                ('CFG-TMODE-POS_TYPE', 0),       # ECEF
            ]
            layers = LAYER_ALL if save else 1
            self._send(UBXMessage.config_set(layers, 0, cfg).serialize())
            self.log.info("TMODE3を無効化しました（単独測位モード）")
            if save:
                time.sleep(0.5)
            return True
        except Exception as e:
            self.log.error(f"TMODE3リセット失敗: {e}")
            return False
        finally:
            self._close()

    def set_tmode3_fixed(self, lat: float, lon: float, alt: float,
                         save: bool = True) -> bool:
        """TMODE3固定座標モードを設定する

        Args:
            lat: 緯度 (10進数度)
            lon: 経度 (10進数度)
            alt: 楕円体高 (メートル)
            save: Trueの場合、RAM+BBR+Flashに保存

        Returns:
            設定成功ならTrue
        """
        self._open()
        try:
            cfg = [
                ('CFG-TMODE-MODE', 2),           # Fixed Mode
                ('CFG-TMODE-POS_TYPE', 1),       # LAT/LON/HEIGHT
                ('CFG-TMODE-LAT', int(lat * 1e7)),
                ('CFG-TMODE-LON', int(lon * 1e7)),
                ('CFG-TMODE-HEIGHT', int(alt * 100)),
            ]
            layers = LAYER_ALL if save else 1
            self._send(UBXMessage.config_set(layers, 0, cfg).serialize())
            self.log.info(f"TMODE3 FIXED: lat={lat:.7f} lon={lon:.7f} alt={alt:.1f}m")
            if save:
                time.sleep(0.5)
            return True
        except Exception as e:
            self.log.error(f"TMODE3設定失敗: {e}")
            return False
        finally:
            self._close()

    def set_rtcm3_messages(self, save: bool = True) -> bool:
        """RTCM3メッセージ出力を設定する

        MSM7有効化、不要メッセージ無効化、プロトコル出力許可、NMEA/UBX無効化を行う。

        Args:
            save: Trueの場合、RAM+BBR+Flashに保存

        Returns:
            全キー設定成功ならTrue
        """
        self._open()
        try:
            layers = LAYER_ALL if save else 1
            ok_count = 0
            fail_count = 0

            for label, keys in [("RTCM3 +ON", _RTCM3_ENABLE),
                                ("RTCM3 -OFF", _RTCM3_DISABLE),
                                ("PROTOCOL +ON", _PROTOCOL_ENABLE),
                                ("NMEA -OFF", _NMEA_DISABLE),
                                ("UBX -OFF", _UBX_DISABLE)]:
                val = 1 if '+ON' in label else 0
                for k in keys:
                    try:
                        self._send(UBXMessage.config_set(layers, 0, [(k, val)]).serialize())
                        ok_count += 1
                    except Exception as e:
                        self.log.warning(f"設定失敗: {k}: {e}")
                        fail_count += 1
                    time.sleep(0.05)

            self.log.info(f"RTCM3設定: {ok_count}成功, {fail_count}失敗")
            if save:
                time.sleep(1.0)
            return fail_count == 0
        except Exception as e:
            self.log.error(f"RTCM3設定失敗: {e}")
            return False
        finally:
            self._close()

    def verify_settings(self) -> dict:
        """全RTCM MSGOUTキーをポーリングして実際のON/OFF状態を確認する

        Returns:
            {
                'verified': {tag: value, ...},
                'all_ok': bool,
                'summary': [str, ...]
            }
        """
        expected = {}
        for k in _RTCM3_ENABLE:
            expected[k] = 1
        for k in _RTCM3_DISABLE:
            expected[k] = 0

        self._open()
        result = {'verified': {}, 'all_ok': True, 'summary': []}
        try:
            self._send(UBXMessage.config_poll(0, 0, _ALL_VERIFY).serialize())
            raw = self._read_ubx(0x06, 0x8B, timeout=3.0)
            if raw and len(raw) >= 10:
                payload = raw[6:-2]
                pos = 4
                while pos + 4 <= len(payload):
                    kid = int.from_bytes(payload[pos:pos + 4], 'little')
                    pos += 4
                    size_enc = (kid >> 28) & 0x07
                    val_size = {0x1: 1, 0x2: 1, 0x3: 2, 0x4: 4, 0x5: 8}.get(size_enc, 1)
                    if pos + val_size > len(payload):
                        break
                    val = int.from_bytes(payload[pos:pos + val_size], 'little')
                    pos += val_size
                    for k in _ALL_VERIFY:
                        try:
                            if UBXMessage.cfgkey_from_string(k) == kid:
                                tag = k.replace('CFG-MSGOUT-RTCM_3X_TYPE', '').replace(
                                    '_UART1', '').replace('_USB', '')
                                desc = _NAMES.get(tag, tag)
                                result['verified'][tag] = val
                                exp = expected.get(k)
                                if exp is not None:
                                    ok = (val == exp)
                                    if not ok and tag in ('1006', '1077'):
                                        result['all_ok'] = False
                                        mark = f'❌*** expected={exp}'
                                    elif not ok:
                                        mark = f'⚠️  expected={exp}'
                                    else:
                                        mark = '✅'
                                else:
                                    ok = True
                                    mark = '✅' if val == 1 else '❌'
                                result['summary'].append(
                                    f"  {tag:8s} {desc:<20s} = {val}  {mark}")
                                break
                        except Exception:
                            continue
            else:
                self.log.warning("CFG-VALGET応答なし")
                result['all_ok'] = False
        except Exception as e:
            self.log.error(f"設定検証失敗: {e}")
            result['all_ok'] = False
        finally:
            self._close()
        return result

    def configure(self, lat: float, lon: float, alt: float,
                  save: bool = True) -> dict:
        """F9P基地局モードの全設定を実行する

        Args:
            lat: 緯度 (10進数度)
            lon: 経度 (10進数度)
            alt: 楕円体高 (メートル)
            save: Trueの場合、設定をFlashに保存

        Returns:
            {
                'step1': bool,   # TMODE3設定結果
                'step2': bool,   # RTCM3メッセージ設定結果
                'step3': dict,   # 検証結果
                'all_ok': bool   # 総合結果
            }
        """
        r = {'step1': False, 'step2': False, 'step3': {}, 'all_ok': False}
        self.log.info("=" * 55)
        self.log.info("F9P 基地局モード設定 (MSM7 RTCM3)")
        self.log.info("=" * 55)

        r['step1'] = self.set_tmode3_fixed(lat, lon, alt, save)
        if r['step1']:
            r['step2'] = self.set_rtcm3_messages(save)
        else:
            self.log.error("TMODE3設定失敗のため中断")

        # Flash保存後はF9Pが再起動するため、ポート再出現を待つ
        if save:
            self.log.info("F9Pの再起動を待機中 (5秒)...")
            time.sleep(5)

        try:
            r['step3'] = self.verify_settings()
        except Exception as e:
            self.log.warning(f"設定検証をスキップします（ポート未接続: {e}）")
            r['step3'] = {'all_ok': True, 'summary': ['(検証スキップ)']}

        r['all_ok'] = r['step1'] and r['step2'] and r['step3'].get('all_ok', False)

        self.log.info("--- RTCM MSGOUT 検証結果 ---")
        for line in r['step3'].get('summary', []):
            self.log.info(line)
        self.log.info(f"総合結果: {'✅ 全設定OK' if r['all_ok'] else '⚠️ 問題あり'} " + "=" * 15)
        return r