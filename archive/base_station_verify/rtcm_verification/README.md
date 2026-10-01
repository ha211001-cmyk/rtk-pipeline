# rtcm_verification — F9P基地局 vs ichimill RTCMログ比較検証

F9P基地局モードで取得したRTCMログと、ichimill（NTRIP）から取得したRTCMログを比較し、
メッセージ内容・バイナリ形式・設定の差異を検証するディレクトリです。

## ディレクトリ構成

```
rtcm_verification/
├── README.md                        # このファイル（検証結果・知見まとめ）
├── step1_analyze_f9p_logs.py        # Step1: F9P基地局ログ解析
├── step2_analyze_ichimill_logs.py   # Step2: ichimillログ解析
├── step3_compare.py                 # Step3: 比較検証
└── results/                         # 解析結果出力先
    ├── step1_f9p_analysis.txt
    ├── step2_ichimill_analysis.txt
    └── step3_comparison.txt
```

## 実行方法

```bash
cd ~/EVK-F9P
python3 base_station_verify/rtcm_verification/step1_analyze_f9p_logs.py
python3 base_station_verify/rtcm_verification/step2_analyze_ichimill_logs.py
python3 base_station_verify/rtcm_verification/step3_compare.py
```

---

## 検証で確定した最終結論

### ✅ 最重要結論: ZED-F9P は基地局モードで MSM7 出力に対応している

**「ZED-F9Pはファームウェア制限により基地局モードではMSM4が最大で、MSM7は出力できない」という初期結論は誤りでした。**

実際の原因は、**設定を適用したポートとログを取得したポートの不一致**です。

- ZED-F9P のメッセージ出力設定は**インターフェース（USB / UART1 / UART2 / I2C / SPI）ごとに独立**
- 初期検証では `_UART1` 向け設定のみを変更し、ログ取得元の USB ポート（`/dev/ttyACM2`）の設定を変更していなかった
- その結果、USB ポートからは工場出荷設定（Type 1005 + MSM4 + 4072）が出力され続けた
- **`_USB` 向け設定キーを追加したところ、MSM7 の出力を実機確認できた**

---

### 実機検証で確定した F9P の出力仕様（USB+UART1 両設定後）

| Type | 名称 | 出力 |
|------|------|:---:|
| **1006** | Station ARP (with antenna height) | ✅ |
| **1074** | GPS MSM4 | ✅（MSM7と重複のため無効化推奨） |
| **1077** | GPS MSM7 | ✅ |
| **1087** | GLONASS MSM7 | ✅ |
| **1097** | Galileo MSM7 | ✅ |
| **1117** | QZSS MSM7（みちびき） | ✅ |
| **1127** | BeiDou MSM7 | ✅ |
| **1230** | GLONASS L1/L2 Code-Phase Bias | ✅ |
| 1005 | Station ARP（アンテナ高なし） | ✅（1006と競合のため無効化推奨） |
| 4072 | u-blox Proprietary | ✅（不要なため無効化推奨） |

- パースエラー **0**、RTCM3 フレーム構造は完全に規格準拠
- 基地局座標（Type 1006）は完全安定（変動 0.0000 m）

---

### F9P vs ichimill の最終比較

| Type | 名称 | F9P | ichimill | 判定 |
|------|------|:---:|:---:|------|
| 1006 | Station ARP (with antenna height) | ✅ | ✅ | 一致 |
| 1033 | Receiver & Antenna Description | ❌ | ✅ | ichimillのみ（RTK測位に影響なし） |
| 1077 | GPS MSM7 | ✅ | ✅ | 一致 |
| 1087 | GLONASS MSM7 | ✅ | ✅ | 一致 |
| 1097 | Galileo MSM7 | ✅ | ✅ | 一致 |
| 1117 | QZSS MSM7 | ✅ | ✅ | 一致 |
| 1127 | BeiDou MSM7 | ✅ | ✅ | 一致 |
| 1230 | GLONASS Bias | ✅ | ❌ | F9Pのみ（有益な追加情報） |

**MSM7 メッセージ構成は F9P と ichimill で完全一致。** ichimill が持つ Type 1033（受信機・アンテナ情報）のみ F9P 基地局モードでは出力されないが、RTK 測位には必須ではない。

---

## 重要な技術知見

### 1. ポート別設定キー（最重要）

ZED-F9P のメッセージ出力設定は**インターフェースごとに独立**しています。

| インターフェース | 設定キー suffix | 用途 |
|---|---|---|
| USB | `_USB` | PC/ラズパイでのログ取得・検証 |
| UART1 | `_UART1` | ドローン（Pixhawk等）との通信 |
| UART2 | `_UART2` | 補助シリアル |

`_UART1` の設定だけ変更しても USB 出力には影響しません。**対象ポートの設定キーを必ず指定する**必要があります。

### 2. 必要な設定キー

```python
# MSM7 有効化（USB + UART1 両方）
'CFG-MSGOUT-RTCM_3X_TYPE1077_USB/UART1'  # GPS MSM7
'CFG-MSGOUT-RTCM_3X_TYPE1087_USB/UART1'  # GLO MSM7
'CFG-MSGOUT-RTCM_3X_TYPE1097_USB/UART1'  # GAL MSM7
'CFG-MSGOUT-RTCM_3X_TYPE1117_USB/UART1'  # QZSS MSM7
'CFG-MSGOUT-RTCM_3X_TYPE1127_USB/UART1'  # BDS MSM7

# Type 1006 有効化 + Type 1005 無効化（1005と1006の同時出力は帯域圧迫）
'CFG-MSGOUT-RTCM_3X_TYPE1006_USB/UART1'
'CFG-MSGOUT-RTCM_3X_TYPE1005_USB/UART1'  # = 0 に設定

# RTCM3 プロトコル出力許可
'CFG-USBOUTPROT-RTCM3X'
'CFG-UART1OUTPROT-RTCM3X'

# 保存レイヤー: RAM + BBR + Flash（layers=7）で再起動後も設定維持
```

### 3. MSM4 vs MSM7

| 項目 | MSM4 | MSM7 |
|------|------|------|
| コード疑似距離 | 標準分解能 | 高分解能 |
| 搬送波位相 | 標準分解能 | 高分解能 |
| ドップラー | なし | **あり** |
| 主な用途 | 帯域制限環境 | 精密測量・高動態ドローン |

ドローンのような高動態環境では、ドップラー情報を含む **MSM7 が最適**。

### 4. 基地局座標の比較

- F9P: 36.0751418°, 136.2133477°, 44.80m（局ID 0）
- ichimill: 36.0853352°, 136.2586599°, 57.09m（局ID 2849）
- 水平距離 約4,227m（**異なる実験地点のため問題なし**。両方とも正確な位置を出力）

### 5. シリアルポートの二重オープンに注意

`rtk_RTCM_Log2.py` の `_read_gps_status()` がメインの読み取りスレッドと同じポートを
新規オープンすると、**データが奪い合いになり RTCM フレームが破損**する恐れがあります。
NMEA 取得はメインの受信ループ内で非同期に行う設計に修正済みです。

---

## 更新履歴

- 2026-08-08: ディレクトリ新設、Step1〜3 の解析スクリプト作成・実行
- 2026-08-08: 実機検証。**「ZED-F9P は MSM7 出力非対応」という初期結論を誤りと確定し、正しい知見（ポート別設定キーの必要性）に修正**。QZSS(1117)含む全 MSM7 出力を確認。