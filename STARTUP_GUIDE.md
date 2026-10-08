# RTK測位システム 完全起動手順書（ローカルネットワーク / Tailscale対応版）

本ドキュメントは、u-blox ZED-F9P および Pixhawk 6C を用いた RTK 測位システム（地上基地局・Web GCS・ローバー Raspberry Pi 5）を一連の流れで正常起動・監視するための運用手順書です。

---

## 1. システム構成・ネットワーク構成

```mermaid
flowchart TD
    subgraph Mac ["Mac (地上基地局 & GCS: 192.168.2.1)"]
        F9P_Base["F9P 基地局 (USB: /dev/cu.usbmodem112301)"]
        Base_Script["rtk_base_station_v2.py (TCP: 2101 配信)"]
        GCS_Server["Web GCS (FastAPI: Port 9000 / UDP 14550 受信)"]
        Browser["ブラウザ (http://localhost:9000)"]
        
        F9P_Base -->|RTCM3| Base_Script
        Base_Script -->|TCP: 2101| AP
        GCS_Server <--> Browser
    end

    subgraph Network ["ローカル Wi-Fi / 有線 AP"]
        AP["BUFFALO AP (192.168.2.7 / APモード)"]
    end

    subgraph Rover ["ローバー (Raspberry Pi 5 + Pixhawk 6C)"]
        Bridge["mavlink_bridge.py (Mavlink_venv)"]
        Pixhawk["Pixhawk 6C (/dev/ttyAMA0 @ 921600)"]
        Rover_F9P["F9P 移動局 (TELEM1 / UART4)"]
        
        Bridge -->|GPS_RTCM_DATA| Pixhawk
        Pixhawk --> Rover_F9P
        Pixhawk -->|MAVLink Telemetry| Bridge
    end

    Base_Script -.->|RTCM3 補正データ (TCP 2101)| Bridge
    Bridge -.->|MAVLink UDP 14550| GCS_Server
```

### 通信ポート・要件一覧
- **基地局 RTCM 配信**: TCP `2101`（マルチクライアント・ブロードキャスト）
- **GCS テレメトリ受信**: UDP `14550`
- **GCS Web UI**: HTTP `9000`（ブラウザで操作）
- **Pixhawk TELEM1**: `/dev/ttyAMA0` @ 921600 bps（MAVLink 2.0 / RTS/CTS 有効）

---

## 2. 事前確認・準備

### ① Mac 側シリアルポートの確認
基地局 F9P が Mac に USB 接続されていることを確認します。
```bash
ls -la /dev/cu.usbmodem*
# 例: /dev/cu.usbmodem112301 が存在すること
```

### ② 基地局設定ファイル (`gcs/config/base_station.json`)
基準局のアンテナ位置が設定されていることを確認します。
```json
{
    "mode": "manual",
    "serial_port": "/dev/cu.usbmodem112301",
    "baudrate": 115200,
    "fixed_lat": 36.0756835,
    "fixed_lon": 136.2135045,
    "fixed_alt": 45.72,
    "save_to_flash": false,
    "auto_obs_duration": 300
}
```
> [!IMPORTANT]
> 基地局アンテナを移動した場合は、必ず実測した緯度・経度・楕円体高(HAE)を上記ファイルに記入してください。アンテナ位置と設定座標の乖離が大きいと Rover が RTK 計算を拒絶します。

---

## 3. 起動手順

### ステップ 1: 基地局（Base Station）の起動 (Mac側)

F9P を基地局モード（TMODE3 Fixed）に自動設定し、RTCM3 補正データの TCP 配信を開始します。

```bash
cd ~/rtk-pipeline-local
source .venv/bin/activate

# 基地局の起動
python3 gcs/rtk_tools/rtk_base_station_v2.py \
  --config gcs/config/base_station.json \
  --serial-port /dev/cu.usbmodem112301
```

**正常起動の確認ポイント:**
- `[BASE Write] TMODE3 Fixed: lat=...`
- `[BASE Write] RTCM3 (both): 14 msgs`
- `TCP server started on 0.0.0.0:2101`
- `rtk_base_station.log` に `RTCM frame: ... bytes` が継続出力されていること

---

### ステップ 2: Web GCS ダッシュボードの起動 (Mac側 別ターミナル)

Web UI と MAVLink 受信サーバーを立ち上げます。

```bash
cd ~/rtk-pipeline-local
source .venv/bin/activate

# Web GCS 起動 (ポート 9000)
python3 -m gcs.server --port 9000
```

**操作:**
1. ブラウザで [http://localhost:9000](http://localhost:9000) にアクセスします。
2. 画面右上の **「Connect」** をクリックして MAVLink バックエンドを接続状態にします。

---

### ステップ 3: ローバー側（Raspberry Pi 5）の起動

Raspberry Pi へ SSH 接続し、MAVLink ブリッジを起動します。

#### 1. Raspberry Pi への SSH 接続
```bash
# ローカルネットワーク（APモード時）
ssh taki@192.168.2.4

# または Tailscale 経由の場合
ssh raspi
# (または ssh taki@100.69.75.96)
```

#### 2. ローバー起動コマンドの実行
```bash
cd ~/rtk-pipeline

# バックグラウンド起動（推奨）
nohup /home/taki/Mavlink_venv/bin/python3 gcs/rtk_tools/mavlink_bridge.py \
  --serial /dev/ttyAMA0 \
  --baud 921600 \
  --target-host 192.168.2.1 \
  --rtcm-host 192.168.2.1 \
  > ~/logs/mavlink_bridge_run.log 2>&1 &
```

> [!NOTE]
> Tailscale 経由でテストする場合は `--target-host 100.80.225.4 --rtcm-host 100.80.225.4` を指定します。

---

## 4. 動作確認・ステータス監視

### ① GCS Web UI での確認
[http://localhost:9000](http://localhost:9000) のカードにドローン（System ID 1）が表示され、テレメトリ情報が更新されていることを確認します。

### ② RTK ログのリアルタイム確認 (Raspberry Pi 側)
```bash
# 最新の RTK CSV ログを表示
tail -f ~/logs/rtk_status_*.csv
```
出力カラム:
`utc_time, elapsed_sec, fix_type, fix_name, sats, lat, lon, alt, eph, epv`

**fix_type の遷移:**
- `1` / `3`: `3D_FIX`（単独測位）
- `5`: `RTK_FLOAT`（浮動解・収束中）
- `6`: **`RTK_FIXED`（センチメートル級・測位成功）**

### ③ RTCM 生パケット受信確認
```bash
# ファイルサイズが秒単位で増加していれば受信正常
ls -lh ~/logs/rtcm_rover_*.rtcm3
```

---

## 5. トラブルシューティング

| 現象 | 主な原因 | 対処法 |
| :--- | :--- | :--- |
| **MacからラズパイにローカルSSHできない** | BUFFALO ルーターが「ROUTER モード」になっている（二重ルーター） | ルーター底面/背面のスイッチを **「AP」または「BRIDGE」** に切り替えて電源を入れ直し、Mac から `192.168.2.x` の DHCP を受けるようにする。 |
| **`3D_FIX`（3）のまま `RTK_FIXED`（6）にならない** | 基地局座標（`base_station.json`）と実測値の乖離 | アンテナ位置を移動した場合、単独測位で現在座標を計測し直して設定に反映する。 |
| **シリアルポートが開けない (`/dev/ttyAMA0: Device or resource busy`)** | 既存のプロセスがポートを占有している | `fuser /dev/ttyAMA0` で PID を確認し、`kill <PID>` で解放する。 |
| **Pixhawk が RTCM パケットを認識しない** | MAVLink 1.0 で送られている、またはフロー制御なし | `os.environ["MAVLINK20"] = "1"` と `--rtscts`（RTS/CTS）が有効になっているか確認する。 |
| **基地局起動時に JSONDecodeError が出る** | `base_station.json` の末尾カッコ等の文法エラー | `python3 -c "import json; json.load(open('gcs/config/base_station.json'))"` で構文を検証する。 |

