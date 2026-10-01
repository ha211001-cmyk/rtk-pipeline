# EVK-F9P GPS & RTK プロジェクト サマリー

## 📋 プロジェクト概要

u-blox F9P GNSS受信機を使用した GPS データ表示と、RTK (Real-Time Kinematic) 修正データ流し込みプログラムのセット。NTRIP プロトコル経由で高精度位置情報を実現し、cm-level の精度を達成します。

**作成日**: 2026-03-01  
**Python バージョン**: 3.11.9  
**主要ライブラリ**: pygnssutils, pynmeagps, pyubx2, pyrtcm, pyspartn

---

## 📁 プロジェクト構成

```
EVK-F9P/
├── 📄 README.md                    ← メインドキュメント ⭐
├── 📄 ENVIRONMENT_INFO.md          ← 環境情報詳細（AI用）
├── 📄 RTK_GUIDE.md                 ← RTK利用ガイド
├── 📄 PROJECT_SUMMARY.md           ← このファイル
│
├── 🐍 gps_display.py               ← GPS表示プログラム（推奨）
├── 🐍 rtk_input.py                 ← RTK修正データ流し込み（新規）⭐
│
├── 🐍 debug_serial.py              ← シリアル通信デバッグ
├── 🐍 debug_nmea.py                ← NMEA解析デバッグ
├── 🐍 gps_simple.py                ← シンプル版
├── 🐍 gps_console.py               ← コンソール版
├── 🐍 ubx_mon_hw.py                ← ハードウェア監視
│
├── 🔧 run.bat                      ← 実行メニュー（Windows）
└── .venv/                          ← Python仮想環境
```

### 推奨実行ファイル

| ファイル | 目的 | 実行方法 |
|---------|------|--------|
| **gps_display.py** | GPS 位置情報表示 | `python gps_display.py` |
| **rtk_input.py** | RTK 修正データ流し込み | `python rtk_input.py --interactive` |
| **run.bat** | クイックメニュー | ダブルクリック |

---

## 🚀 クイックスタート

### 1️⃣ GPS データ表示

```powershell
C:\Users\keita\Documents\Local\EVK-F9P> python gps_display.py
```

**出力**:
```
[1] NMEA-GGA (Global Positioning System Fix Data)
  Time:      12:34:56
  Latitude:  36.07268000°
  Longitude: 136.59527000°
  Altitude:  45.32 m
  Fix Type:  3D Fix
  Satellites: 28
```

### 2️⃣ RTK 修正データ流し込み（対話モード）

```powershell
C:\Users\keita\Documents\Local\EVK-F9P> python rtk_input.py --interactive
```

**出力**:
```
Serial port [COM13]: COM13
NTRIP Server [rtk2go.com]: rtk2go.com
Mountpoint (e.g., YMSK): YMSK
NTRIP Username: your-email@example.com
NTRIP Password: ••••••••

======================================================================
RTK Integration Status - 2026-03-01 12:34:56
======================================================================

RTK Caster Connection:
  Status: ✓ Connected
  Messages Received: 342

Position Data:
  Latitude:  36.07268123°
  Longitude: 136.59527456°
  Altitude:  45.32 m
  Fix Type:  RTK Fixed      ⭐ cm-level precision!
  Satellites: 28
```

### 3️⃣ Windows バッチメニュー

```powershell
C:\Users\keita\Documents\Local\EVK-F9P> .\run.bat
```

対話メニューで プログラムを選択実行

---

## 📊 RTK 機能説明

### RTK とは

**RTK (Real-Time Kinematic)** = 衛星信号の搬送波位相を利用した高精度測位

#### 精度改善

```
標準 GPS      : ±5m
DGPS          : ±1m
RTK Float     : ±10-20cm
RTK Fixed     : ±2-3cm ⭐ TARGET
```

### 流れ図

```
┌──────────────────┐
│ NTRIP Caster     │  (rtk2go.com or イチミル)
│ (RTCM3修正データ) │
└────────┬─────────┘
         │
         │ HTTP/NTRIP
         ▼
┌────────────────────────────────┐
│ rtk_input.py                   │
│ ・修正データ受信               │
│ ・GPS位置情報表示              │
│ (リアルタイムリアルタイム)     │
└────────┬─────────────────────┘
         │
         │ USB Serial (修正データ)
         ▼
    ┌──────────────┐
    │ EVK-F9P      │
    │ (f9p GNSS)   │
    └──┬───────────┘
       │
       │ cm-level精度
       └──→ 高精度位置決定
```

---

## 🔧 システム環境

### Python 環境
- **Python**: 3.11.9
- **実行コマンド**: `C:\Users\keita\AppData\Local\Programs\Python\Python311\python.exe`

### 重要ライブラリ（自動チェック）

```python
pygnssutils   (1.1.22)  # GNSS utility library
pynmeagps     (1.1.2)   # NMEA parser
pyubx2        (1.2.60)  # UBX parser  
pyrtcm        (1.1.10)  # RTCM3 parser
pyspartn      (1.0.8)   # SPARTN parser
paho-mqtt     (2.1.0)   # MQTT client
pyserial      (3.5)     # Serial communication
requests      (2.32.5)  # HTTP requests
```

### ハードウェア

- **受信機**: u-blox EVK-F9P (RTK対応)
- **接続**: USB 仮想COM (COM13 typical)
- **プロトコル**: NMEA 0183, UBX, RTCM3, SPARTN
- **アンテナ**: u-blox standard antenna

---

## 📖 ドキュメント ガイド

### ユーザー向け
1. **README.md** ← 最初に読む（全概要）
2. **RTK_GUIDE.md** ← RTK 詳細ガイド

### システム管理者・開発者向け
1. **ENVIRONMENT_INFO.md** ← 環境詳細（AI向け）
2. **PROJECT_SUMMARY.md** ← このファイル（全体構成）

### 実行方法
```powershell
# GPS表示
python gps_display.py

# RTK統合（推奨）
python rtk_input.py --interactive

# RTK統合（パラメータ指定）
python rtk_input.py --port COM13 --server rtk2go.com --mountpoint YMSK
```

---

## ✅ チェックリスト

実行前に確認してください：

- [ ] Python 3.11 がインストール済み
- [ ] F9P が USB で接続済み
- [ ] インターネット接続確認（RTK用）
- [ ] 必要なライブラリがインストール済み
  ```powershell
  pip install --upgrade pygnssutils pynmeagps pyubx2
  ```
- [ ] シリアルポート番号確認（通常 COM13 or COM6）
  ```powershell
  Get-WmiObject Win32_SerialPort  # Windows PowerShell
  ```
- [ ] NTRIP マウントポイント確認
  - rtk2go.com で地図から選択
  - または提供者から取得

---

## 🔗 外部リンク

| リソース | URL |
|---------|-----|
| **RTK2GO Caster** | https://rtk2go.com/ |
| **NTRIP 仕様** | https://igs.bkg.bund.de/ntrip/ |
| **pygnssutils** | https://github.com/semuconsulting/pygnssutils |
| **u-blox F9P** | https://www.u-blox.com/en/product/zed-f9p-module |

---

## 🔍 トラブルシューティング概要

| 問題 | 原因 | 解決法 |
|------|------|-------|
| "Cannot open COM13" | ポート未接続 | デバイスマネージャーで確認 |
| NTRIP 接続失敗 | インターネット未接続 | ネットワーク確認 |
| RTK Fixed 未取得 | 初期化時間不足 | 30秒以上待機、衛星数確認 |
| GPS 動作しない | 受信機未初期化 | 電源・アンテナ確認 |

詳細は **RTK_GUIDE.md** の「トラブルシューティング」参照。

---

## 📝 バージョン履歴

### v2.0 (2026-03-01) - RTK統合版 🎉

✨ **新機能**:
- RTK 修正データ流し込み機能
- NTRIP/SPARTN 対応
- リアルタイム位置情報表示
- イチミル対応
- 対話型設定モード
- Windows バッチメニュー

📚 **ドキュメント**:
- RTK_GUIDE.md (50+ 行)
- ENVIRONMENT_INFO.md 拡張
- README.md RTK セクション追加
- PROJECT_SUMMARY.md（本ファイル）

### v1.0 (2026-03-01) - 初版

✅ GPS 表示機能  
✅ NMEA メッセージ対応  
✅ エラーハンドリング  

---

## 👨‍💻 サポート対象

- **OS**: Windows 10 / Windows 11
- **Python**: 3.11.x
- **デバイス**: u-blox EVK-F9P (RTK対応)
- **RTK サービス**: rtk2go.com, イチミル等 (NTRIP/SPARTN互換)

---

## 📋 今後の拡張予定 (Optional Future Work)

- [ ] 基準局 (Base Station) モード対応
- [ ] ローカル NTRIP Caster 構築
- [ ] MQTT/SPARTN IP 対応強化
- [ ] Web ダッシュボード
- [ ] データログ出力機能
- [ ] マルチレシーバー対応
- [ ] GUI インターフェース

---

**最終更新**: 2026-03-01  
**作成者**: AI Assistant (GitHub Copilot)  
**ライセンス**: MIT (推奨)

質問や問題は適切なドキュメントを参照いただくか、コミュニティフォーラムでお尋ねください。
