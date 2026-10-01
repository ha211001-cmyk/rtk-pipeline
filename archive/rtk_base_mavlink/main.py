#!/usr/bin/env python3
"""
RTK Base Station via MAVLink - メインエントリーポイント

ZED-F9Pを基地局モードでMSM7出力し、受信したRTCM3補正データを
MAVLink GPS_RTCM_DATA (ID:233) でArduPilotに注入する。
ArduPilotがDroneCAN経由でH-RTK F9Pに転送し、RTK Fixを実現する。

システム構成:
  [ZED-F9P (基地局)] --USB--> [ラズパイ] --UART--> [Pixhawk6C] --DroneCAN--> [H-RTK F9P]
       MSM7出力              RTCM受信→注入    GPS_RTCM_DATA              RTK Fix

Usage:
    source ~/Mavlink_venv/bin/activate
    cd ~/rtk-pipeline/rtk_base_mavlink
    python3 main.py
"""

import json
import logging
import os
import sys
import threading
import time
from pathlib import Path
from queue import Empty
from typing import Optional

# --- ローカルモジュール ---
from f9p_configurator import F9pConfigurator
from rtcm_receiver import RtcmReceiver
from mavlink_comm import MavlinkComm
from rtcm_injector import RtcmInjector
from position_observer import PositionObserver
from stats import SystemStats


def load_config(config_path: Optional[str] = None) -> dict:
    """設定ファイルを読み込む

    Args:
        config_path: 設定ファイルのパス (省略時は同ディレクトリのconfig.json)

    Returns:
        設定辞書
    """
    if config_path is None:
        config_path = os.path.join(os.path.dirname(__file__), "config.json")

    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def detect_f9p_port() -> Optional[str]:
    """F9PのUSBシリアルポートを自動検出する

    /dev/ttyACM* を検索し、UBX MON-VER ポーリングに応答するポートをF9Pと判定する。

    Returns:
        ポートパス、または見つからない場合はNone
    """
    import glob
    import serial
    import time

    candidates = sorted(glob.glob('/dev/ttyACM*'))
    if not candidates:
        return None

    # 各ポートにUBX MON-VERポーリングを試行
    for port in candidates:
        try:
            ser = serial.Serial(port, 38400, timeout=0.5)
            time.sleep(0.2)
            ser.reset_input_buffer()

            # UBX MON-VER poll (class 0x0A, id 0x04)
            # UBX frame: sync(2) + class(1) + id(1) + len(2) + payload(0) + ck(2)
            poll_msg = b'\xb5\x62\x0a\x04\x00\x00\x0e\x34'
            ser.write(poll_msg)
            ser.flush()

            # 応答を待つ
            deadline = time.time() + 1.0
            while time.time() < deadline:
                if ser.in_waiting >= 8:
                    data = ser.read(ser.in_waiting)
                    # UBX応答のsync bytesを探す
                    if b'\xb5\x62\x0a\x04' in data:
                        ser.close()
                        return port
                time.sleep(0.05)
            ser.close()
        except (serial.SerialException, OSError):
            continue

    # UBX応答がなければ最後のポートを返す（フォールバック）
    return candidates[-1]


def setup_logging(log_level: str = "INFO", log_dir: str = "logs") -> logging.Logger:
    """ロギング設定を行う

    Args:
        log_level: ログレベル (DEBUG, INFO, WARNING, ERROR)
        log_dir: ログ出力ディレクトリ

    Returns:
        ルートロガー
    """
    from datetime import datetime

    log_dir_path = Path(log_dir)
    log_dir_path.mkdir(parents=True, exist_ok=True)

    log_format = '[%(asctime)s] %(levelname)s %(name)s: %(message)s'
    date_format = '%Y-%m-%d %H:%M:%S'

    # ルートロガー設定
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # 既存ハンドラをクリア
    root_logger.handlers.clear()

    # コンソールハンドラ
    console_handler = logging.StreamHandler()
    console_handler.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    console_handler.setFormatter(logging.Formatter(log_format, datefmt=date_format))
    root_logger.addHandler(console_handler)

    # ファイルハンドラ
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir_path / f"rtk_base_{timestamp}.log"
    file_handler = logging.FileHandler(str(log_file))
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(log_format, datefmt=date_format))
    root_logger.addHandler(file_handler)

    return root_logger


def resolve_base_position(config: dict, logger: logging.Logger) -> Optional[dict]:
    """基地局座標を解決する

    modeが"static"の場合はconfigの固定値を使用。
    modeが"dynamic"の場合は単独測位で座標を取得する。

    Args:
        config: 設定辞書
        logger: ロガー

    Returns:
        {'lat': float, 'lon': float, 'alt': float} または失敗時はNone
    """
    f9p_cfg = config['f9p_base']
    mode = f9p_cfg.get('mode', 'static')

    # F9Pポートの解決
    serial_port = f9p_cfg.get('serial_port', '/dev/ttyACM2')
    if f9p_cfg.get('auto_detect_port', True):
        detected = detect_f9p_port()
        if detected:
            serial_port = detected
            logger.info(f"F9Pポート自動検出: {serial_port}")
        else:
            logger.warning(f"F9Pポート自動検出失敗。設定値を使用: {serial_port}")
    else:
        logger.info(f"F9Pポート (設定値): {serial_port}")

    if mode == 'static':
        lat = f9p_cfg.get('fixed_lat')
        lon = f9p_cfg.get('fixed_lon')
        alt = f9p_cfg.get('fixed_alt')

        if lat is None or lon is None or alt is None:
            logger.error("静的モードだがfixed_lat/fixed_lon/fixed_altが設定されていません")
            return None

        logger.info(f"基地局座標 (静的): lat={lat:.7f} lon={lon:.7f} alt={alt:.2f}m")
        return {'lat': lat, 'lon': lon, 'alt': alt, 'port': serial_port}

    elif mode == 'dynamic':
        duration = f9p_cfg.get('auto_obs_duration', 60)
        logger.info(f"基地局座標 (動的): {duration}秒間単独測位")

        # 以前に保存されたTMODE3固定座標が出力されないようリセットする
        configurator = F9pConfigurator(
            serial_port=serial_port,
            baudrate=f9p_cfg.get('config_baudrate', 38400),
            logger=logger,
        )
        configurator.reset_tmode3(save=f9p_cfg.get('save_to_flash', True))
        # TMODE3リセット後のポート再出現を待つ
        time.sleep(5)

        observer = PositionObserver(serial_port, baudrate=f9p_cfg.get('baudrate', 115200),
                                    logger=logger)
        result = observer.observe(duration_sec=duration)

        if result is None:
            logger.error("単独測位に失敗しました")
            return None

        logger.info(f"基地局座標 (動的): lat={result['lat']:.7f} lon={result['lon']:.7f} "
                    f"alt={result['alt']:.2f}m (samples={result['samples']})")
        return {
            'lat': result['lat'],
            'lon': result['lon'],
            'alt': result['alt'],
            'port': serial_port,
        }

    else:
        logger.error(f"不明なモード: {mode}")
        return None


def configure_f9p(config: dict, base_pos: dict, logger: logging.Logger) -> bool:
    """F9Pを基地局モードに設定する

    Args:
        config: 設定辞書
        base_pos: 基地局座標辞書
        logger: ロガー

    Returns:
        設定成功ならTrue
    """
    f9p_cfg = config['f9p_base']

    if f9p_cfg.get('skip_config', False):
        logger.info("F9P設定をスキップします (skip_config=true)")
        return True

    logger.info("F9P基地局モード設定を開始します...")

    configurator = F9pConfigurator(
        serial_port=base_pos['port'],
        baudrate=f9p_cfg.get('config_baudrate', 38400),
        logger=logger,
    )

    result = configurator.configure(
        lat=base_pos['lat'],
        lon=base_pos['lon'],
        alt=base_pos['alt'],
        save=f9p_cfg.get('save_to_flash', True),
    )

    if result['all_ok']:
        logger.info("F9P基地局モード設定完了 ✅")
    else:
        logger.warning("F9P基地局モード設定に一部問題があります ⚠️")

    return result['all_ok']


def rtcm_inject_loop(rtcm_receiver: RtcmReceiver, rtcm_injector: RtcmInjector,
                     logger: logging.Logger) -> None:
    """RTCM受信キューからフレームを取り出し、MAVLinkに注入するループ

    Args:
        rtcm_receiver: RtcmReceiverインスタンス
        rtcm_injector: RtcmInjectorインスタンス
        logger: ロガー
    """
    frame_queue = rtcm_receiver.get_frame_queue()
    logger.info("RTCM注入ループ開始")

    while True:
        try:
            frame = frame_queue.get(timeout=1.0)
            rtcm_injector.inject_frame(frame)
        except Empty:
            continue
        except KeyboardInterrupt:
            break
        except Exception as e:
            logger.error(f"RTCM注入エラー: {e}")
            time.sleep(0.1)


def main():
    """メイン関数"""
    print("=" * 60)
    print("RTK Base Station via MAVLink")
    print("ZED-F9P MSM7 → MAVLink GPS_RTCM_DATA → H-RTK F9P")
    print("=" * 60)

    # 設定読み込み
    config = load_config()
    log_level = config.get('log_level', 'INFO')
    logger = setup_logging(log_level, log_dir=os.path.join(os.path.dirname(__file__), "logs"))

    logger.info("=" * 60)
    logger.info("RTK Base Station via MAVLink 起動")
    logger.info("=" * 60)

    # 基地局座標の解決
    base_pos = resolve_base_position(config, logger)
    if base_pos is None:
        logger.error("基地局座標の解決に失敗しました。終了します。")
        sys.exit(1)

    # F9P基地局モード設定
    f9p_cfg = config['f9p_base']
    if not f9p_cfg.get('skip_config', False):
        f9p_ok = configure_f9p(config, base_pos, logger)
        if not f9p_ok:
            logger.warning("F9P設定に問題がありますが、続行します...")
        # F9P設定後は少し待つ（設定反映 + ポート再出現のため）
        time.sleep(5)

    # MAVLink接続
    mav_cfg = config['mavlink']
    logger.info(f"MAVLink接続: {mav_cfg['port']} @ {mav_cfg['baud']}bps "
                f"(RTS/CTS: {mav_cfg['rtscts']})")

    mavlink = MavlinkComm(
        port=mav_cfg['port'],
        baud=mav_cfg['baud'],
        rtscts=mav_cfg['rtscts'],
        logger=logger,
    )

    if not mavlink.connect():
        logger.error("MAVLink接続に失敗しました。終了します。")
        sys.exit(1)

    # GPSデータストリーム受信開始
    mavlink.start_gps_stream()
    time.sleep(1)

    # RTCM受信開始
    # F9P設定（Flash保存）後はポートが変わることがあるため再検出する
    rtcm_port = base_pos['port']
    if f9p_cfg.get('auto_detect_port', True):
        detected = detect_f9p_port()
        if detected:
            rtcm_port = detected
            logger.info(f"RTCM受信用ポート再検出: {rtcm_port}")
        else:
            logger.warning(f"RTCM受信用ポート再検出失敗。設定値を使用: {rtcm_port}")

    rtcm_receiver = RtcmReceiver(
        serial_port=rtcm_port,
        baudrate=f9p_cfg.get('baudrate', 115200),
        log_dir=os.path.join(os.path.dirname(__file__), "logs"),
        logger=logger,
    )
    rtcm_receiver.start()
    time.sleep(1)

    # RTCM注入器
    rtcm_cfg = config['rtcm_inject']
    rtcm_injector = RtcmInjector(
        mavlink_comm=mavlink,
        max_packet_size=rtcm_cfg.get('max_packet_size', 180),
        max_fragments=rtcm_cfg.get('max_fragments', 4),
        logger=logger,
    )

    # ステータスモニター
    system_stats = SystemStats(logger=logger)
    system_stats.start_monitor(rtcm_receiver, mavlink, rtcm_injector, interval=5.0)

    # RTCM注入ループ（メインスレッドで実行）
    logger.info("🚀 システム起動完了。RTCM注入を開始します。")
    print("\n" + "=" * 60)
    print("  🚀 システム起動完了")
    print("  F9P基地局 → RTCM受信 → MAVLink注入 → H-RTK F9P")
    print("  Ctrl+C で停止")
    print("=" * 60 + "\n")

    try:
        rtcm_inject_loop(rtcm_receiver, rtcm_injector, logger)
    except KeyboardInterrupt:
        print("\n\n🛑 停止シグナル受信。終了します...")
    finally:
        # クリーンアップ
        logger.info("システム停止中...")
        system_stats.stop_monitor()
        rtcm_receiver.stop()
        mavlink.disconnect()

        # サマリー表示
        system_stats.print_summary(rtcm_receiver, mavlink, rtcm_injector)
        logger.info("システム停止完了")


if __name__ == "__main__":
    main()