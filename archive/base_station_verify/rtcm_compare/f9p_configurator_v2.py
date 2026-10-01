#!/usr/bin/env python3
"""F9P Configurator v2 - MT 1005/1019/1020 有効化 + NMEA/UBX無効化 + 事後検証"""
import logging, time
from typing import Optional
import serial
from pyubx2 import UBXMessage, UBXReader, UBX_PROTOCOL
from pyubx2.ubxhelpers import cfgname2key

LAYER_ALL = 7  # RAM + BBR + FLASH

_RTCM3_ENABLE = [
    # 注: QZSS MSM7 (TYPE1117) は pyubx2 1.2.x にキーが無いため対象外
    # --- USBポート向け (PCでのログ検証用 /dev/ttyACM2) ---
    'CFG_MSGOUT_RTCM_3X_TYPE1006_USB',   # Station XYZ with antenna height
    'CFG_MSGOUT_RTCM_3X_TYPE1077_USB',   # GPS MSM7
    'CFG_MSGOUT_RTCM_3X_TYPE1087_USB',   # GLO MSM7
    'CFG_MSGOUT_RTCM_3X_TYPE1097_USB',   # GAL MSM7
    'CFG_MSGOUT_RTCM_3X_TYPE1127_USB',   # BDS MSM7
    'CFG_MSGOUT_RTCM_3X_TYPE1230_USB',   # GLO Bias

    # --- UART1ポート向け (ドローン/Pixhawk通信用) ---
    'CFG_MSGOUT_RTCM_3X_TYPE1006_UART1', # Station XYZ with antenna height
    'CFG_MSGOUT_RTCM_3X_TYPE1077_UART1', # GPS MSM7
    'CFG_MSGOUT_RTCM_3X_TYPE1087_UART1', # GLO MSM7
    'CFG_MSGOUT_RTCM_3X_TYPE1097_UART1', # GAL MSM7
    'CFG_MSGOUT_RTCM_3X_TYPE1127_UART1', # BDS MSM7
    'CFG_MSGOUT_RTCM_3X_TYPE1230_UART1', # GLO Bias
]

_RTCM3_DISABLE = [
    # USB向け: 4072独自メッセージ + Type 1005 (1006と競合) + Type 1074 (MSM4, MSM7と重複)
    'CFG_MSGOUT_RTCM_3X_TYPE4072_0_USB',
    'CFG_MSGOUT_RTCM_3X_TYPE4072_1_USB',
    'CFG_MSGOUT_RTCM_3X_TYPE1005_USB',
    'CFG_MSGOUT_RTCM_3X_TYPE1074_USB',   # GPS MSM4 (MSM7で十分なため無効化)
    # UART1向け: 同上
    'CFG_MSGOUT_RTCM_3X_TYPE4072_0_UART1',
    'CFG_MSGOUT_RTCM_3X_TYPE4072_1_UART1',
    'CFG_MSGOUT_RTCM_3X_TYPE1005_UART1',
    'CFG_MSGOUT_RTCM_3X_TYPE1074_UART1',  # GPS MSM4 (MSM7で十分なため無効化)
]

# プロトコル出力許可 (RTCM3出力を明示的に有効化)
_PROTOCOL_ENABLE = [
    'CFG_USBOUTPROT_RTCM3X',    # USBからのRTCM3出力許可
    'CFG_UART1OUTPROT_RTCM3X',  # UART1からのRTCM3出力許可
]

_NMEA_DISABLE = [
    'CFG_MSGOUT_NMEA_ID_GGA_UART1', 'CFG_MSGOUT_NMEA_ID_GLL_UART1',
    'CFG_MSGOUT_NMEA_ID_GSA_UART1', 'CFG_MSGOUT_NMEA_ID_GSV_UART1',
    'CFG_MSGOUT_NMEA_ID_RMC_UART1', 'CFG_MSGOUT_NMEA_ID_VTG_UART1',
    'CFG_MSGOUT_NMEA_ID_ZDA_UART1',
]

_UBX_DISABLE = [
    'CFG_MSGOUT_UBX_NAV_STATUS_UART1', 'CFG_MSGOUT_UBX_NAV_DOP_UART1',
    'CFG_MSGOUT_UBX_NAV_SAT_UART1', 'CFG_MSGOUT_UBX_NAV_SIG_UART1',
]

_ALL_VERIFY = [
    # USB
    'CFG_MSGOUT_RTCM_3X_TYPE1005_USB',
    'CFG_MSGOUT_RTCM_3X_TYPE1006_USB',
    'CFG_MSGOUT_RTCM_3X_TYPE1077_USB', 'CFG_MSGOUT_RTCM_3X_TYPE1087_USB',
    'CFG_MSGOUT_RTCM_3X_TYPE1097_USB',
    'CFG_MSGOUT_RTCM_3X_TYPE1127_USB', 'CFG_MSGOUT_RTCM_3X_TYPE1230_USB',
    'CFG_MSGOUT_RTCM_3X_TYPE4072_0_USB', 'CFG_MSGOUT_RTCM_3X_TYPE4072_1_USB',
    # UART1
    'CFG_MSGOUT_RTCM_3X_TYPE1005_UART1',
    'CFG_MSGOUT_RTCM_3X_TYPE1006_UART1',
    'CFG_MSGOUT_RTCM_3X_TYPE1077_UART1', 'CFG_MSGOUT_RTCM_3X_TYPE1087_UART1',
    'CFG_MSGOUT_RTCM_3X_TYPE1097_UART1',
    'CFG_MSGOUT_RTCM_3X_TYPE1127_UART1', 'CFG_MSGOUT_RTCM_3X_TYPE1230_UART1',
    'CFG_MSGOUT_RTCM_3X_TYPE4072_0_UART1', 'CFG_MSGOUT_RTCM_3X_TYPE4072_1_UART1',
]

_NAMES = {
    '1005':'Station ARP','1006':'Station XYZ+AH',
    '1077':'GPS MSM7','1087':'GLO MSM7','1097':'GAL MSM7',
    '1117':'QZSS MSM7','1127':'BDS MSM7','1230':'GLO Bias',
    '4072_0':'ublox Prop0','4072_1':'ublox Prop1',
}

class F9pConfiguratorV2:
    def __init__(self, serial_port, baudrate=38400, logger=None):
        self.serial_port = serial_port
        self.baudrate = baudrate
        self.log = logger or logging.getLogger("F9pV2")
        self._ser = None

    def _open(self):
        self._ser = serial.Serial(self.serial_port, self.baudrate, timeout=1.0)
        time.sleep(0.3)
        self._ser.reset_input_buffer()

    def _close(self):
        if self._ser and self._ser.is_open:
            self._ser.close()
            self._ser = None

    def _send(self, msg):
        self._ser.write(msg)
        self._ser.flush()

    def _read_ubx(self, cls, mid, timeout=3.0):
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

    def step1_tmode3(self, lat, lon, alt, save=True):
        self._open()
        try:
            cfg = [
                ('CFG_TMODE_MODE', 2), ('CFG_TMODE_POS_TYPE', 1),  # 1 = LAT/LON/HEIGHT（0=ECEFだとLLHが無視される）
                ('CFG_TMODE_LAT', int(lat*1e7)), ('CFG_TMODE_LON', int(lon*1e7)),
                ('CFG_TMODE_HEIGHT', int(alt*100)),
            ]
            layers = LAYER_ALL if save else 1
            self._send(UBXMessage.config_set(layers, 0, cfg).serialize())
            self.log.info(f"STEP1 OK: TMODE3 FIXED {lat:.7f},{lon:.7f},{alt:.1f}")
            if save: time.sleep(0.5)
            return True
        except Exception as e:
            self.log.error(f"STEP1 FAIL: {e}")
            return False
        finally:
            self._close()

    def step2_messages(self, save=True):
        self._open()
        try:
            layers = LAYER_ALL if save else 1
            ok_count = 0
            fail_count = 0
            for label, keys in [("RTCM3 +ON", _RTCM3_ENABLE),
                                ("RTCM3 4072/1005 -OFF", _RTCM3_DISABLE),
                                ("PROTOCOL +ON", _PROTOCOL_ENABLE),
                                ("NMEA -OFF", _NMEA_DISABLE),
                                ("UBX -OFF", _UBX_DISABLE)]:
                val = 1 if '+ON' in label else 0
                for k in keys:
                    try:
                        self._send(UBXMessage.config_set(layers, 0, [(k, val)]).serialize())
                        ok_count += 1
                    except Exception as e:
                        self.log.warning(f"STEP2: {k} FAIL: {e}")
                        fail_count += 1
                    time.sleep(0.05)
            self.log.info(f"STEP2: {ok_count} keys OK, {fail_count} keys FAIL")
            if save: time.sleep(1.0)
            return fail_count == 0
        except Exception as e:
            self.log.error(f"STEP2 FAIL: {e}")
            return False
        finally:
            self._close()

    def step3_verify(self):
        """全RTCM MSGOUTキーをポーリングして実際のON/OFF状態を確認

        MT 4072 系は意図的に無効化(0)しているので、0 なら ✅ と表示する。
        必須キー(1005, 1074)が 0 の場合は fatal 扱い。
        """
        # 各キーの期待値を事前に決める (1=ON期待, 0=OFF期待)
        expected = {}
        for k in _RTCM3_ENABLE:
            expected[k] = 1
        for k in _RTCM3_DISABLE:
            expected[k] = 0
        # リスト外のキーは「don't care」→ None

        self._open()
        result = {'verified': {}, 'all_ok': True, 'summary': []}
        try:
            self._send(UBXMessage.config_poll(0, 0, _ALL_VERIFY).serialize())
            raw = self._read_ubx(0x06, 0x8B, timeout=3.0)
            if raw and len(raw) >= 10:
                payload = raw[6:-2]
                pos = 4
                while pos + 4 <= len(payload):
                    kid = int.from_bytes(payload[pos:pos+4], 'little')
                    pos += 4
                    # key の上位 3bit から値サイズを取得 (U1=1, U2=2, U4=4, U8=8)
                    size_enc = (kid >> 28) & 0x07
                    val_size = {0x1: 1, 0x2: 1, 0x3: 2, 0x4: 4, 0x5: 8}.get(size_enc, 1)
                    if pos + val_size > len(payload):
                        break
                    val = int.from_bytes(payload[pos:pos+val_size], 'little')
                    pos += val_size
                    for k in _ALL_VERIFY:
                        try:
                            if cfgname2key(k)[0] == kid:
                                tag = k.replace('CFG_MSGOUT_RTCM_3X_TYPE','').replace('_UART1','').replace('_USB','')
                                desc = _NAMES.get(tag, tag)
                                result['verified'][tag] = val
                                exp = expected.get(k)  # None → don't care
                                if exp is not None:
                                    ok = (val == exp)
                                    # 必須キーが期待値と違う → fatal
                                    if not ok and tag in ('1006', '1077'):
                                        result['all_ok'] = False
                                        mark = f'❌*** expected={exp}'
                                    elif not ok:
                                        mark = f'⚠️  expected={exp}'
                                    else:
                                        mark = '✅'
                                else:
                                    ok = True  # don't care
                                    mark = '✅' if val == 1 else '❌'
                                result['summary'].append(
                                    f"  {tag:8s} {desc:<20s} = {val}  {mark}")
                                break
                        except Exception:
                            continue
            else:
                self.log.warning("STEP3: No CFG-VALGET response")
                result['all_ok'] = False
        except Exception as e:
            self.log.error(f"STEP3 FAIL: {e}")
            result['all_ok'] = False
        finally:
            self._close()
        return result

    def configure(self, lat, lon, alt, save=True):
        r = {'step1': False, 'step2': False, 'step3': {}, 'all_ok': False}
        self.log.info("="*55)
        self.log.info("F9P V2 Configuration (Standard RTCM + Verification)")
        self.log.info("="*55)
        r['step1'] = self.step1_tmode3(lat, lon, alt, save)
        if r['step1']:
            r['step2'] = self.step2_messages(save)
        else:
            self.log.error("Aborting after STEP1 failure")
        r['step3'] = self.step3_verify()
        r['all_ok'] = r['step1'] and r['step2'] and r['step3'].get('all_ok', False)
        self.log.info("--- RTCM MSGOUT Verification ---")
        for line in r['step3'].get('summary', []):
            self.log.info(line)
        self.log.info(f"Overall: {'ALL OK' if r['all_ok'] else 'ISSUES FOUND'} " + "="*15)
        return r
