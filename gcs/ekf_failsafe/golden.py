#!/usr/bin/env python3
"""golden.py — Phase 3（RTK→EKF 取り込み・フェイルセーフ）ArduPilot パラメータ Golden 値

Phase 3（飛行試験準備）では、ローバー（DroneCAN H-RTK F9P）の RTK-FIXED を
ArduPilot の EKF に正しく取り込み、飛行中も測位精度を維持しつつ、測位劣化時に
フェイルセーフ（FS）が正しく働くよう、**ArduPilot パラメータの Golden 値**を
一元管理する。

Golden 値は 2 グループに分ける（要件 (1) / (2) に対応）:

  - ``ekf_sources`` … RTK 測位を EKF に取り込むためのソース指定（要件 (1)）
      AHRS_EKF_TYPE / EK3_ENABLE / EK3_SRC1_POSXY / EK3_SRC1_POSZ /
      EK3_SRC1_VELXY / EK3_SRC1_VELZ / EK3_SRC1_YAW /
      GPS_TYPE / GPS_AUTO_CONFIG / GPS_PRIMARY / GPS_AUTO_SWITCH

  - ``failsafe`` … RTK FLOAT/FIXED 喪失時のフェイルセーフと GPS 品質ゲート（要件 (2)）
      FS_GCS_ENABLE / FS_EKF_ACTION / FS_EKF_THRESH / FS_GPS_ENABLE /
      GPS_HDOP_GOOD / GPS_HDOP_MAX / GPS_GNSS_MODE

本モジュールは標準ライブラリのみで動作する（pymavlink / pyserial 非依存）。
実際の MAVLink 通信は ``gcs/ekf_failsafe/param_guard.py``（ArduPilotParamGuard）が担う。

参考（ArduPilot ソース実測値）:
  - GPS_TYPE = 9 は ``AP_GPS.h`` の ``GPS_TYPE_UAVCAN``（DroneCAN）に対応。
  - EKF3 ソース値: 0=NONE / 1=BARO(高度のみ) / 3=GPS / 4=BEACON / 5=OPTFLOW /
    6=EXTNAV / 7=WHEELENCODER。YAW は 1=コンパス / 2=GPS(移動基線)。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# グループ定義（照合・レポートの表示順）
# ---------------------------------------------------------------------------
GROUP_EKF_SOURCES = "ekf_sources"   # 要件 (1): RTK→EKF 取り込み
GROUP_FAILSAFE = "failsafe"         # 要件 (2): フェイルセーフ / GPS 品質ゲート
GROUP_ORDER = (GROUP_EKF_SOURCES, GROUP_FAILSAFE)

PARAM_GROUPS: Dict[str, List[str]] = {
    GROUP_EKF_SOURCES: [
        "AHRS_EKF_TYPE",
        "EK3_ENABLE",
        "EK3_SRC1_POSXY",
        "EK3_SRC1_POSZ",
        "EK3_SRC1_VELXY",
        "EK3_SRC1_VELZ",
        "EK3_SRC1_YAW",
        "GPS_TYPE",
        "GPS_AUTO_CONFIG",
        "GPS_PRIMARY",
        "GPS_AUTO_SWITCH",
    ],
    GROUP_FAILSAFE: [
        "FS_GCS_ENABLE",
        "FS_EKF_ACTION",
        "FS_EKF_THRESH",
        "FS_GPS_ENABLE",
        "GPS_HDOP_GOOD",
        "GPS_HDOP_MAX",
        "GPS_GNSS_MODE",
    ],
}

# 全パラメータ名（表示順を保った flat リスト）
ALL_PARAM_NAMES: List[str] = [
    name for names in PARAM_GROUPS.values() for name in names
]

# ---------------------------------------------------------------------------
# Golden 値
# ---------------------------------------------------------------------------
GOLDEN_PARAMS: Dict[str, float] = {
    # --- 要件 (1): RTK 測位を EKF へ取り込むソース指定 ---
    "AHRS_EKF_TYPE": 3,      # EKF3 を姿勢・位置推定に使用
    "EK3_ENABLE": 1,         # EKF3 を有効化
    "EK3_SRC1_POSXY": 3,     # 水平位置ソース = GPS（RTK-FIXED を投入）
    "EK3_SRC1_POSZ": 3,      # 高度ソース = GPS（RTK の高精度高度を投入）
    "EK3_SRC1_VELXY": 3,     # 水平速度ソース = GPS
    "EK3_SRC1_VELZ": 3,      # 垂直速度ソース = GPS
    "EK3_SRC1_YAW": 1,       # 方位ソース = コンパス（単一 F9P のため GPS 移動基線は不使用）
    "GPS_TYPE": 9,           # DroneCAN（GPS_TYPE_UAVCAN）※ 1番目 GPS の正準名
    "GPS_AUTO_CONFIG": 2,    # 全自動設定（DroneCAN AutoConfig）
    "GPS_PRIMARY": 0,        # プライマリ GPS = 1 番目（DroneCAN F9P）
    "GPS_AUTO_SWITCH": 0,    # GPS 自動切替無効（劣化時に勝手に切り替えない）
    # --- 要件 (2): RTK FLOAT/FIXED 喪失時のフェイルセーフ ---
    "FS_GCS_ENABLE": 1,      # GCS 喪失時 RTL（1=Always RTL）
    "FS_EKF_ACTION": 1,      # EKF フェイルセーフ動作 = Land（1=Land）
    "FS_EKF_THRESH": 0.8,    # EKF 整合性閾値（低いほど敏感。既定 0.8）
    "FS_GPS_ENABLE": 1,      # GPS 喪失時 Land（1=Land）
    "GPS_HDOP_GOOD": 140,    # GPS 良好 HDOP（1.4m）。アームに必要な GPS ロック品質
    "GPS_HDOP_MAX": 200,     # GPS フェイルセーフ発動 HDOP（2.0m）
    "GPS_GNSS_MODE": 47,     # GLONASS 無効の復元値（bit6 を落とす。詳細は下記）
}

# ---------------------------------------------------------------------------
# 表示名（日本語ラベル）
# ---------------------------------------------------------------------------
LABELS: Dict[str, str] = {
    "AHRS_EKF_TYPE": "EKF 種類（3=EKF3）",
    "EK3_ENABLE": "EKF3 有効化（1=有効）",
    "EK3_SRC1_POSXY": "EKF3 水平位置ソース（3=GPS）",
    "EK3_SRC1_POSZ": "EKF3 高度ソース（3=GPS）",
    "EK3_SRC1_VELXY": "EKF3 水平速度ソース（3=GPS）",
    "EK3_SRC1_VELZ": "EKF3 垂直速度ソース（3=GPS）",
    "EK3_SRC1_YAW": "EKF3 方位ソース（1=コンパス）",
    "GPS_TYPE": "GPS タイプ（9=DroneCAN/UAVCAN）",
    "GPS_AUTO_CONFIG": "GPS 自動設定（2=全自動）",
    "GPS_PRIMARY": "プライマリ GPS（0=1番目）",
    "GPS_AUTO_SWITCH": "GPS 自動切替（0=無効/RTK維持）",
    "FS_GCS_ENABLE": "GCS フェイルセーフ（1=RTL）",
    "FS_EKF_ACTION": "EKF フェイルセーフ動作（1=Land）",
    "FS_EKF_THRESH": "EKF 整合性閾値（低いほど敏感）",
    "FS_GPS_ENABLE": "GPS フェイルセーフ（1=Land）",
    "GPS_HDOP_GOOD": "GPS HDOP 良好閾値（140=1.4m）",
    "GPS_HDOP_MAX": "GPS HDOP 上限（200=2.0m）",
    "GPS_GNSS_MODE": "GNSS コンステレーション（GLONASS 無効の復元値）",
}

# ---------------------------------------------------------------------------
# 型タグ（pymavlink 非依存の文字列。param_guard が MAV_PARAM_TYPE へ変換する）
# ---------------------------------------------------------------------------
PARAM_TYPES: Dict[str, str] = {
    "AHRS_EKF_TYPE": "int8",
    "EK3_ENABLE": "int8",
    "EK3_SRC1_POSXY": "int8",
    "EK3_SRC1_POSZ": "int8",
    "EK3_SRC1_VELXY": "int8",
    "EK3_SRC1_VELZ": "int8",
    "EK3_SRC1_YAW": "int8",
    "GPS_TYPE": "int8",
    "GPS_AUTO_CONFIG": "int8",
    "GPS_PRIMARY": "int8",
    "GPS_AUTO_SWITCH": "int8",
    "FS_GCS_ENABLE": "int8",
    "FS_EKF_ACTION": "int8",
    "FS_EKF_THRESH": "float",
    "FS_GPS_ENABLE": "int8",
    "GPS_HDOP_GOOD": "int16",
    "GPS_HDOP_MAX": "int16",
    "GPS_GNSS_MODE": "int16",
}

# 型タグ → 対応する golden 値の比較幅（float 以外は整数比較）
_FLOAT_TAGS = {"float"}


def is_float_param(name: str) -> bool:
    """パラメータ名が float 型かどうかを返す。"""
    return PARAM_TYPES.get(name) in _FLOAT_TAGS


def values_equal(expected: float, actual: Optional[float], name: str) -> bool:
    """Golden 値と実測値の一致判定（float は許容誤差、整数は丸めて比較）。"""
    if actual is None:
        return False
    if is_float_param(name):
        return abs(float(actual) - float(expected)) <= 1e-4
    return int(round(float(actual))) == int(round(float(expected)))


# ---------------------------------------------------------------------------
# GPS_GNSS_MODE（bitmask）の解釈
# ---------------------------------------------------------------------------
GNSS_MODE_BITS: Dict[int, str] = {
    0: "GPS",
    1: "SBAS",
    2: "Galileo",
    3: "BeiDou",
    4: "IMES",
    5: "QZSS",
    6: "GLONASS",
}

# GPS_GNSS_MODE の Golden 値 47 = bit0(GPS)+bit1(SBAS)+bit2(Galileo)+bit3(BeiDou)+bit5(QZSS)
# → bit6(GLONASS) を無効化した「復元値」。
# 背景: 本プロジェクトの基地局は GLONASS を配信しないため、ローバー側で GLONASS を
#       有効にしても測位に寄与せず、バイアス要因になり得る。
#       archive/rtk_field_test/set_gnss_mode.py で GLONASS を落とした実験後の復元先がこの値。


def decode_gnss_mode(value: Optional[float]) -> str:
    """GPS_GNSS_MODE の bitmask を有効コンステレーション名の文字列へ変換する。"""
    if value is None:
        return "n/a"
    ivalue = int(round(float(value)))
    if ivalue == 0:
        return "0（受信機デフォルト/全コンステレーション）"
    enabled = [GNSS_MODE_BITS[i] for i in sorted(GNSS_MODE_BITS) if (ivalue >> i) & 1]
    return "%d (%s) → %s" % (ivalue, bin(ivalue), ", ".join(enabled) if enabled else "なし")


def group_of(name: str) -> Optional[str]:
    """パラメータ名が属するグループ名を返す（未知なら None）。"""
    for group, names in PARAM_GROUPS.items():
        if name in names:
            return group
    return None


def param_value_repr(name: str, value: Optional[float]) -> str:
    """人間向けの値表示（GPS_GNSS_MODE はビット解釈を添える）。"""
    if value is None:
        return "n/a"
    if name == "GPS_GNSS_MODE":
        return decode_gnss_mode(value)
    if is_float_param(name):
        return "%.3f" % float(value)
    return "%d" % int(round(float(value)))


def synthetic_guard_result(golden: Optional[Dict[str, float]] = None,
                           status: str = "PASS",
                           mismatches: Optional[List[str]] = None) -> Dict[str, Any]:
    """自己検証（--self-test / ユニットテスト）用の合成 guard 結果を生成する。

    ``ArduPilotParamGuard.run_check_and_fix()`` と同じ戻り値スキーマを持つため、
    実機（MAVLink）なしで ``evaluate_ekf_sources()`` / ``evaluate_failsafe()`` を
    検証できる。
    """
    golden = dict(golden if golden is not None else GOLDEN_PARAMS)
    mismatches = list(mismatches or [])
    checked: Dict[str, Any] = {}
    messages: List[str] = []
    for name in ALL_PARAM_NAMES:
        if name not in golden:
            continue
        ok = name not in mismatches
        checked[name] = {
            "key": name,
            "key_display": name,
            "label": LABELS.get(name, name),
            "group": group_of(name),
            "expected": golden[name],
            "actual": None if (not ok) else golden[name],
            "ok": ok,
        }
        if ok:
            messages.append("  OK   %-20s = %s" % (name, param_value_repr(name, golden[name])))
        else:
            messages.append("  NG   %-20s = n/a（期待値 %s / %s）"
                            % (name, param_value_repr(name, golden[name]), LABELS.get(name, name)))
    if not mismatches:
        summary = "すべての ArduPilot パラメータが正常です（修正不要）"
    else:
        summary = "%d 件のパラメータ退行を検出（合成データ）" % len(mismatches)
    return {
        "status": status,
        "checked": checked,
        "fixed": list(mismatches) if status == "FIXED" else [],
        "fix_failed": list(mismatches) if status == "FAIL" else [],
        "messages": messages,
        "summary": summary,
        "transport": {"mode": "mavlink", "connection": "(synthetic)"},
        "timestamp": "synthetic",
    }


__all__ = [
    "GROUP_EKF_SOURCES", "GROUP_FAILSAFE", "GROUP_ORDER", "PARAM_GROUPS",
    "ALL_PARAM_NAMES", "GOLDEN_PARAMS", "LABELS", "PARAM_TYPES",
    "is_float_param", "values_equal",
    "GNSS_MODE_BITS", "decode_gnss_mode", "group_of", "param_value_repr",
    "synthetic_guard_result",
]
