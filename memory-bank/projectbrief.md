# EVK-F9P プロジェクト概要

## プロジェクトの目的

u-blox ZED-F9P RTK受信機（EVK-F9P）を使用して、GNSS測位システムを構築する。

## 主な機能

1. **移動局（Rover）としての動作**
   - イチミルRTK（ichimile）のNTRIP補正データを受信してRTK測位を実行
   - RTK Float（浮動小数点解）まで到達可能
   - ※ この NTRIP/イチミル（構成A）方式はロードマップ方針転換（自作基地局＝構成Bベース）に伴い
     スクリプトを `archive/legacy_ntrip_ichimill/` へ退避済み

2. **基地局（Base Station）としての動作**
   - 固定座標（既知点）を設定し、RTCM3補正信号を生成・出力
   - 標準RTCMメッセージ（1005, 1077, 1087, 1097, 1127, 1230）を生成

3. **PPK（Post-Processed Kinematic）ログ記録**
   - 測位データのログ記録と事後解析

## 対象プラットフォーム

- **Windows**: COMポート経由でF9Pに接続
- **Raspberry Pi**: UART/USB経由でF9Pに接続

## ハードウェア

- u-blox ZED-F9P RTK受信機
- 通信ボーレート: 38400 baud
- Windows接続ポート: COM7（UART1）