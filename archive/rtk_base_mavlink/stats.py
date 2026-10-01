#!/usr/bin/env python3
"""
Stats - 統計情報管理モジュール

システム全体の統計情報を一元管理し、定期的なステータス表示を行う。

Usage:
    from stats import SystemStats

    stats = SystemStats()
    stats.print_status(rtcm_receiver, mavlink_comm, rtcm_injector)
"""

import logging
import threading
import time
from datetime import datetime
from typing import Optional


class SystemStats:
    """システム全体の統計情報管理クラス

    各モジュールの統計情報を集約し、定期的なステータス表示を行う。

    Args:
        logger: ロガーインスタンス
    """

    def __init__(self, logger: Optional[logging.Logger] = None):
        self.log = logger or logging.getLogger("SystemStats")
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start_monitor(self, rtcm_receiver, mavlink_comm, rtcm_injector,
                      interval: float = 5.0) -> None:
        """ステータスモニタースレッドを開始する

        Args:
            rtcm_receiver: RtcmReceiverインスタンス
            mavlink_comm: MavlinkCommインスタンス
            rtcm_injector: RtcmInjectorインスタンス
            interval: 表示間隔 (秒)
        """
        self._running = True
        self._thread = threading.Thread(
            target=self._monitor_loop,
            args=(rtcm_receiver, mavlink_comm, rtcm_injector, interval),
            daemon=True
        )
        self._thread.start()

    def stop_monitor(self) -> None:
        """ステータスモニターを停止する"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)

    def _monitor_loop(self, rtcm_receiver, mavlink_comm, rtcm_injector,
                      interval: float) -> None:
        """ステータス表示ループ（別スレッドで実行）"""
        while self._running:
            try:
                time.sleep(interval)
                self.print_status(rtcm_receiver, mavlink_comm, rtcm_injector)
            except KeyboardInterrupt:
                break
            except Exception as e:
                self.log.error(f"ステータス表示エラー: {e}")

    def print_status(self, rtcm_receiver, mavlink_comm, rtcm_injector) -> None:
        """現在のシステムステータスを表示する

        Args:
            rtcm_receiver: RtcmReceiverインスタンス
            mavlink_comm: MavlinkCommインスタンス
            rtcm_injector: RtcmInjectorインスタンス
        """
        pos = mavlink_comm.get_gps_position()

        print(f"\n{'=' * 60}")
        print(f"  📊 システムステータス [{datetime.now().strftime('%H:%M:%S')}]")
        print(f"  {'─' * 40}")
        print(f"  MAVLink: {'✅接続' if mavlink_comm.is_connected else '❌切断'}")
        if pos['eph'] is not None:
            print(f"  GPS:     {pos['fix_name']} | 衛星: {pos['satellites']} | "
                  f"EPH: {pos['eph']:.2f}m")
        else:
            print(f"  GPS:     {pos['fix_name']} | 衛星: {pos['satellites']}")
        print(f"  {'─' * 40}")
        print(f"  RTCM受信バイト:      {rtcm_receiver.stats['bytes_read']}")
        print(f"  RTCM受信フレーム:    {rtcm_receiver.stats['frames_received']}")
        print(f"  RTCM受信エラー:      {rtcm_receiver.stats['read_errors']}")
        print(f"  {'─' * 40}")
        print(f"  GPS_RAW_INT受信:     {mavlink_comm.stats['gps_raw_count']}")
        print(f"  {'─' * 40}")
        print(f"  RTCM注入フレーム:    {rtcm_injector.stats['frames_injected']}")
        print(f"  RTCM注入ドロップ:    {rtcm_injector.stats['frames_dropped']}")
        print(f"  GPS_RTCM_DATA送信:   {rtcm_injector.stats['packets_sent']} フレーム "
              f"({rtcm_injector.stats['fragments_sent']} 分割パケット)")
        print(f"{'=' * 60}")

    def print_summary(self, rtcm_receiver, mavlink_comm, rtcm_injector) -> None:
        """実行結果サマリーを表示する

        Args:
            rtcm_receiver: RtcmReceiverインスタンス
            mavlink_comm: MavlinkCommインスタンス
            rtcm_injector: RtcmInjectorインスタンス
        """
        print("\n" + "=" * 60)
        print("  実行結果サマリー")
        print("=" * 60)
        print(f"  RTCM受信バイト:        {rtcm_receiver.stats['bytes_read']}")
        print(f"  RTCM受信フレーム:      {rtcm_receiver.stats['frames_received']}")
        print(f"  RTCM受信エラー:        {rtcm_receiver.stats['read_errors']}")
        print(f"  GPS_RAW_INT受信:       {mavlink_comm.stats['gps_raw_count']}")
        print(f"  RTCM注入フレーム:      {rtcm_injector.stats['frames_injected']}")
        print(f"  RTCM注入ドロップ:      {rtcm_injector.stats['frames_dropped']}")
        print(f"  GPS_RTCM_DATA送信:     {rtcm_injector.stats['packets_sent']} フレーム "
              f"({rtcm_injector.stats['fragments_sent']} 分割パケット)")
        print("=" * 60)