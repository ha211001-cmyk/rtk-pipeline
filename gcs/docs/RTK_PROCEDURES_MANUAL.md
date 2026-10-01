# GCS (RTK-Pipeline) 運用・操作手順書

本手順書は、`gcs` ディレクトリ内に統合された **RTK測位システムの地上管制（GCS）** の運用・操作手順をまとめたものです。
Mac（地上基地局・GCS）とRaspberry Pi（ドローン搭載機・Pixhawk接続）を組み合わせた標準的な運用フローをベースに解説します。

---

## 1. システム構成と準備

このシステムは、以下の2つの主要モジュールから構成されます。

1. **Mac (GCS & 基地局)**: Webダッシュボードの提供、基地局としてのRTCM補正データの配信。
2. **Raspberry Pi (Rover)**: 機体側のMAVLink通信の中継、RTCMデータの受信・注入、およびログ記録。

### 1.1 依存ライブラリのインストール
初めて実行する場合は、仮想環境を作成し、必要なライブラリをインストールします。

**Mac (GCS/基地局側)**
```bash
cd ~/rtk-pipeline # またはリポジトリのルート
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**Raspberry Pi (Rover側)**
```bash
cd ~/rtk-pipeline
source .venv/bin/activate
pip install -r gcs/deploy/requirements_raspi.txt
```

---

## 2. 標準運用フロー（実機運用クイックスタート）

MacとRaspberry Piを **Tailscale (VPN)** 経由で接続し、自動でRTK-FIXED（サブセンチ精度）を達成し、実験ログを保存する手順です。

### Step 1: 基地局 RTCM 配信の起動（Mac側）
第1ターミナルを開き、基地局のF9Pを固定座標モードで起動します。これにより `TCP:2101` で補正データの配信が始まります。

```bash
cd ~/rtk-pipeline
source .venv/bin/activate
python3 gcs/rtk_tools/rtk_base_station_v2.py --config gcs/config/base_station.json --serial-port /dev/cu.usbmodem112301
```
> **確認:** `TCP listening on 0.0.0.0:2101` と表示されれば待機完了です。ポート名は環境に応じて変更してください。

### Step 2: GCS Webダッシュボードの起動（Mac側）
第2ターミナルを開き、監視・制御用のWebサーバーを起動します。

```bash
cd ~/rtk-pipeline
source .venv/bin/activate
python3 -m gcs.server --port 9000
```
> **確認:** ブラウザで **http://localhost:9000** にアクセスし、右上の **「Connect」** を1回クリックしてデータ待機状態にします。

### Step 3: MAVLink ブリッジ & RTK 注入・ロギング起動（Raspberry Pi側）
機体に搭載したラズパイにSSH接続し、統合ブリッジプログラムを起動します。
`--target-host` にはMac（GCS）のTailscale IPアドレスを指定します。

```bash
cd ~/rtk-pipeline
source .venv/bin/activate
python3 mavlink_bridge.py --target-host 100.x.x.x  # MacのTailscale IPを指定
```

**起動後の状態:**
- Webダッシュボードが緑色の「Online」になり、姿勢・バッテリー・GPS情報が表示されます。
- 基地局から補正データが受信され、GPSステータスが `3D_FIX` → `DGPS` → `RTK_FLOAT` → **`RTK_FIXED`** へと自動で昇格します。
- 測位時系列データ(`csv`)とRTCM3生データ(`rtcm3`)が `logs/` ディレクトリに自動保存されます。

### Step 4: 実験終了と標準偏差の自動集計
実験が完了したら、ラズパイ側のターミナルで **`Ctrl + C`** を1回押します。
即座に位置誤差の標準偏差・RTK精度のサマリーがターミナルに出力されます。

---

## 3. Web UI (GCS) での運用・監視

ブラウザ (http://localhost:9000) 上のGCSダッシュボードでは、以下の操作が可能です。

### 制御操作
- **機体監視:** 最大4機のドローンの状態（Armed / Mode / バッテリー / RTK Fix / NED）を監視。
- **一斉制御:** 『ALL DRONES』パネルから機体への指示（ARM / DISARM / TAKEOFF / LAND）を送信可能。

### 「⚙️ 運用」タブからの高度な操作
Web UIの「⚙️ 運用」タブから、CLIを使わずに各種ツールを実行できます。

- **設定系:** F9Pの各種設定の読み取り(`f9p_verify`)や書き込み(`f9p_write_verify`)。
- **監視系:** RTK FIXEDの維持率やTTFF（Time To First Fix）の監視、RTCMの到達やCRCエラー監視。
- **ロギング系:** PPK用ログ（RAWX/SFRBX）の記録やRTCM生フレームの記録。

> **⚠️ 注意:** 「基地局座標の再設定」や「Flashへの書き込み」などの危険な操作（Dangerous）は、実行前に必ず確認モーダルが表示されます。設定変更前は `f9p_verify` で現在値を確認してください。

---

## 4. F9Pモジュールの設定と保存（RAM / Flash）

F9Pの設定書き込み時、レイヤー（揮発・不揮発）を意識して運用してください。

- **RAMへの一時保存（推奨）:** 
  一時的な実験で設定を変更する場合、不揮発（Flash）には保存せず、RAMのみに書き込みます。電源を再投入すれば元の設定に戻ります。（例: `f9p_config_all.py` 実行時に `--no-flash` を指定）
- **Flashへの永続保存:**
  恒久的に設定を変更する場合はFlashへ保存します。設定を元に戻す場合は、正しい座標と設定値を指定して再度 `f9p_config_all.py` を実行し、上書きする必要があります。

---

## 5. 学内Wi-Fiなどでの通信トラブル対策（Tailscale）

大学などのWi-Fi環境では、APアイソレーション（端末間通信の遮断）によりMacとラズパイが直接通信できない場合があります。

- **解決策:** 学内Wi-Fi接続時でも、必ずMacとラズパイの**両方でTailscaleを起動**してください。これにより制限を越えて安全に通信できます。
- **プロキシ設定:** もし学内プロキシの影響で通信エラー (`ProxyError`) が発生する場合は、Tailscale通信(`100.x.x.x`)やローカル通信(`127.0.0.1`)がプロキシを通らないように `no_proxy` を設定してください。
  ```bash
  export no_proxy="localhost,127.0.0.1,100.64.0.0/10"
  ```
  ※学外（自宅やテザリング）に移動した際は、プロキシ環境変数を削除 (`unset http_proxy https_proxy ...`) することを忘れないでください。

---

## 6. よくあるトラブルシューティング

| 症状 | 確認事項 |
|---|---|
| **Connectしても機体が表示されない** | `gcs/config/` の接続設定や、`mavlink-router` の `UDP:14550` ポート設定が正しいか確認してください。 |
| **RTCMがRover(ドローン)に届かない** | ラズパイ側で `systemctl status rtk-uart4-inject.service` や基地局の `TCP:2101` への疎通を確認してください。 |
| **NTRIP接続で 401エラー / 拒否される** | 認証情報が設定ファイルに書かれていないか確認し、環境変数 (`NTRIP_USER` / `NTRIP_PASSWORD`) に正しくセットされているか確認してください。 |

設定ファイルのスキーマ検証など、ハードウェアなしのシステム検証を行いたい場合は、以下のコマンドを実行します。
```bash
python3 -m gcs.selftest
```
