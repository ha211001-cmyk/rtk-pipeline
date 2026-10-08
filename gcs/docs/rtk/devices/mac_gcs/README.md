# Mac（基地局配信・Web GCS・解析）

**Mac** が担う 3 つの役割（基地局 RTCM 配信・Web GCS ダッシュボード・事後解析）と、
その構築・運用手順をまとめます。

- 索引: [`../../README.md`](../../README.md)
- 手順書: [`../../../RTK_PROCEDURES_MANUAL.md`](../../../RTK_PROCEDURES_MANUAL.md) §1〜§3 / §5
- 基地局 F9P 単体: [`../f9p_base/README.md`](../f9p_base/README.md)

> **出典ポリシー**: 本資料は `gcs/` パッケージ内のみを出典とします。

---

## 1. 役割

| 役割 | 実装 | 内容 |
|---|---|---|
| **基地局として動作** | [`../../../../rtk_tools/rtk_base_station_v2.py`](../../../../rtk_tools/rtk_base_station_v2.py) | F9P を固定座標に設定し RTCM3 を TCP:2101 で配信 |
| **ルーター親機 / AP 中継** | — | `192.168.2.1` を保持し DHCP で配下に払い出し |
| **Web GCS** | [`../../../../server.py`](../../../../server.py) | FastAPI + uvicorn（REST + WebSocket）、最大 4 機監視 |
| **運用操作** | `gcs/app/operations/` | 設定・監視・ロギングを Web から実行 |
| **事後解析** | `gcs/analyze_fix_log.py` ほか | CSV 後処理・ヒストグラム・精度評価 |

出典: [`../../../RTK_PROCEDURES_MANUAL.md`](../../../RTK_PROCEDURES_MANUAL.md) §1 / §3 / §5、
[`../../../../README.md`](../../../../README.md) の機能表、
[`../../../OPERATIONS.md`](../../../OPERATIONS.md) §1。

---

## 2. ネットワーク構成

```text
┌───────────────────────────────────────────────┐
│              Mac (地上基地局 & GCS)            │
│  - IP: 192.168.2.1 (Wi-Fi/有線ルーター親機)    │
│  - 基地局 F9P: USB (/dev/cu.usbmodem112301)   │
│  - RTCM3 配信: TCP 2101                       │
│  - Web GCS ダッシュボード: http://localhost:9000│
│                           (UDP:14550 受信)    │
└───────────────────────┬───────────────────────┘
                        │ 有線LAN (USB-LANアダプタ)
┌───────────────────────▼───────────────────────┐
│         アクセスポイント (BUFFALO AP)          │
│  - IP: 192.168.2.7 (ブリッジ接続)              │
└───────────────┬───────────────────────┬───────┘
                │ Wi-Fi                 │ Wi-Fi
┌───────────────▼───────────────┐   ┌───▼───────────────────────────┐
│ ローバー (Raspberry Pi 5)     │   │ 別のPC (監視 / 作業用ノートPC)│
│  - IP: 192.168.2.4 (固定)     │   │  - IP: 192.168.2.2 (DHCP)     │
│  - Pixhawk: /dev/ttyAMA0      │   │  - ブラウザ等で GCS を閲覧可能 │
│  - mavlink_bridge.py 実行     │   │    http://192.168.2.1:9000    │
└───────────────────────────────┘   └───────────────────────────────┘
```

- Mac は **Tailscale 等の VPN に依存せず**、自身が親機ルーター（`192.168.2.1`）となり、
  有線接続された AP を通じて全機器を同一サブネットで相互通信させます。
- `bridge100` / 有線インターフェースに `192.168.2.1`（サブネット `255.255.255.0`）を保持し、
  DHCP サーバー（`bootpd`）で配下へ `192.168.2.x` を配布します。
- 別 PC は AP の Wi-Fi に接続し、`http://192.168.2.1:9000` で GCS を共有・監視できます。

出典: [`../../../RTK_PROCEDURES_MANUAL.md`](../../../RTK_PROCEDURES_MANUAL.md) §1 / §5、
[`../../../../README.md`](../../../../README.md)。

---

## 3. 仮想環境

Mac 側のライブラリ競合を避けるため、リポジトリ直下に `.venv` を作成します。

```bash
cd ~/rtk-pipeline-local
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install matplotlib numpy  # 誤差ヒストグラム作成用
```

| ホスト | 仮想環境 | 主なライブラリ |
|---|---|---|
| **Mac**（基地局 & GCS） | `~/rtk-pipeline-local/.venv` | `fastapi` / `uvicorn` / `pyserial` / `matplotlib` / `numpy` / `pyyaml` 等 |
| Raspberry Pi 5（Rover） | `~/Mavlink_venv` | `pymavlink` / `pyserial` |

> ⚠️ Mac 側で作業するターミナルでは、必ず最初に `source .venv/bin/activate` を実行してください。

出典: [`../../../RTK_PROCEDURES_MANUAL.md`](../../../RTK_PROCEDURES_MANUAL.md) §1.1。

---

## 4. 標準運用フロー

### Step 1: 基地局 RTCM 配信の起動

```bash
cd ~/rtk-pipeline-local
source .venv/bin/activate
python3 gcs/rtk_tools/rtk_base_station_v2.py \
    --config gcs/config/base_station.json \
    --serial-port /dev/cu.usbmodem112301
```

確認: **`TCP listening on 0.0.0.0:2101`** が表示されれば待機完了です。

### Step 2: Web GCS ダッシュボードの起動

```bash
cd ~/rtk-pipeline-local
source .venv/bin/activate
python3 -m gcs.server --port 9000
```

- ブラウザで **`http://localhost:9000`**（別 PC からは `http://192.168.2.1:9000`）を開き、
  右上の **「Connect」** を 1 回クリックします。
- `gcs.server` の既定は `0.0.0.0:8000` で、`--host` / `--port` で変更できます。

出典: [`../../../../server.py`](../../../../server.py) の docstring（既定と `--port 9000` の例）、
[`../../../RTK_PROCEDURES_MANUAL.md`](../../../RTK_PROCEDURES_MANUAL.md) §2 Step 2。

### Step 3: 機体側の起動（Raspberry Pi で実行）

```bash
~/Mavlink_venv/bin/python3 gcs/rtk_tools/mavlink_bridge.py --serial /dev/ttyAMA0 --baud 921600
```

詳細は [`../raspberrypi/README.md`](../raspberrypi/README.md) を参照。

### Step 4: 実験終了と集計

ラズパイで `Ctrl + C` を押すと、その場で位置誤差の標準偏差サマリーが出力されます
（[`../raspberrypi/README.md`](../raspberrypi/README.md) §5）。

---

## 5. Web UI（GCS ダッシュボード）

`http://localhost:9000` で以下を操作できます。

### 5.1 制御操作

- **機体監視**: 最大 4 機の状態（Armed / Mode / バッテリー / RTK Fix / NED）を監視。
- **一斉制御**: 『ALL DRONES』パネルから ARM / DISARM / TAKEOFF / LAND を送信。

### 5.2 「⚙️ 運用」タブ

| 分類 | 操作 | 危険 |
|---|---|---|
| 設定系 | `f9p_verify`（読み取りのみ） | |
| 設定系 | `f9p_write_verify`（base/rover・Flash+リセット+検証） | ⚠️ |
| 設定系 | `base_tmode3_set`（基地局座標再測・TMODE3 設定） | ⚠️ |
| 設定系 | `rtcm_rate_set`（RTCM 出力レート変更） | ⚠️ |
| 設定系 | `glonass_toggle`（GLONASS RTCM 出力 ON/OFF） | ⚠️ |
| 監視系 | `rtk_fix_monitor`（FIXED 維持率・TTFF・遷移） | |
| 監視系 | `rtcm_verify_tcp` / `rtcm_rover_monitor` | |
| ロギング系 | `ppk_logger` / `rtcm_logger` / `gps_fix_log` | |
| 基地局系 | `base_station_start` | ⚠️ |

> **⚠️ 危険操作**（Flash 書込・基地局座標の上書き・GLONASS 切替・RTCM レート変更・
> 基地局起動）は、実行前に**確認モーダル**が表示されます。
> 設定変更前は必ず `f9p_verify` で現在値を確認してください。

出典: [`../../../RTK_PROCEDURES_MANUAL.md`](../../../RTK_PROCEDURES_MANUAL.md) §3、
[`../../../OPERATIONS.md`](../../../OPERATIONS.md) §1。

---

## 6. REST API / WebSocket

| メソッド | パス | 説明 |
|---|---|---|
| GET | `/api/ops` | 操作カタログ（カテゴリ・パラメータ・危険フラグ） |
| POST | `/api/ops/{op_id}/start` | 操作開始。`{"params": {...}}` → `{"job_id": ...}` |
| GET | `/api/ops/jobs` | ジョブ一覧 |
| GET | `/api/ops/jobs/{job_id}` | ジョブ詳細（status/progress/logs/result/error） |
| POST | `/api/ops/jobs/{job_id}/stop` | 停止要求 |
| DELETE | `/api/ops/jobs/{job_id}` | 終了済みジョブの除去 |
| WS | `/ws/ops` | ジョブ状態の 1Hz ブロードキャスト |
| WS | `/ws/telemetry` | テレメトリ配信 |

- ジョブの `status` は `PENDING / RUNNING / PASS / FAIL / STOPPED`。
- `logs` はリングバッファ（最大 500 行）。

出典: [`../../../OPERATIONS.md`](../../../OPERATIONS.md) §2 / §3、
[`../../../../README.md`](../../../../README.md) のディレクトリ構成。

---

## 7. 設定ファイル

### 7.1 一覧

| ファイル | 用途 | コミット |
|---|---|---|
| `gcs.yml` | MAVLink 接続のデフォルト（serial / udp / drones） | ✅ |
| `gcs_local.yml` | ローカル開発用（UDP + 複数ドローン例） | ✅ |
| `gcs_multidrone_example.yml` | 複数ドローン管理の例 | ✅ |
| `gcs.user.local.yml` | **個人用上書き**（シリアルポート等） | ❌ |
| `config.yaml` | 統合テストの一元設定（監視・判定基準） | ✅ |
| `config.local.yaml` | 個人用上書き | ❌ |
| `base_station.json` | 基地局設定（固定座標） | ✅ |

出典: [`../../../../config/README.md`](../../../../config/README.md) の設定ファイル一覧。

### 7.2 接続設定（`gcs.yml`）の例

```yaml
connection_type: serial
serial_port: /dev/ttyACM0
serial_baudrate: 115200
udp_listen_port: 14550
drones:
  drone1:
    system_id: 1
    endpoint: "127.0.0.1:14550"
```

出典: [`../../../../config/gcs.yml`](../../../../config/gcs.yml)。

### 7.3 設定の優先順位

接続設定は `gcs/rtk_tools/config_loader.py` が次の順で解決します（高い順）。

1. CLI 明示パス
2. 環境変数 `GCS_CONFIG_PATH`
3. `gcs.user.local.yml`
4. `gcs_local.yml`
5. `gcs.yml`

さらに `DEFAULT_CONFIG`（deep merge）で補完されます。

出典: [`../../../../config/README.md`](../../../../config/README.md) §「設定の優先順位」。

### 7.4 スキーマ検証

```bash
python3 -c "from gcs.config.schema import validate_bundled_configs; print(validate_bundled_configs())"
```

出典: [`../../../../config/README.md`](../../../../config/README.md) §「スキーマ検証」。

> **シークレット**: 認証情報は設定ファイルに平文で書かず、
> `${ENV_VAR}` 形式で環境変数を参照します。平文シークレットが無いことは
> `gcs/config/test_no_hardcoded_secrets.py` がテストで担保します
> （出典: 同上 §「シークレットの扱い」）。

---

## 8. 事後解析（CSV 後処理）

| ツール | 用途 | 起動例 |
|---|---|---|
| [`../../../../analyze_fix_log.py`](../../../../analyze_fix_log.py) | CSV から RTK 維持率・位置標準偏差を後処理 | `python3 gcs/analyze_fix_log.py <CSV>` |
| [`../../../../analyze_intervals.py`](../../../../analyze_intervals.py) | 5 分 / 20 分 / 60 分など**任意区間**を切り出して精度比較 | `python3 gcs/analyze_intervals.py <CSV>` |
| [`../../../../rtk_tools/plot_rtk_histogram.py`](../../../../rtk_tools/plot_rtk_histogram.py) | 水平誤差・垂直誤差の**ヒストグラム**（PNG） | `python3 gcs/rtk_tools/plot_rtk_histogram.py <CSV>` |
| [`../../../../rtk_tools/rtk_data_collector.py`](../../../../rtk_tools/rtk_data_collector.py) | 基地局＋移動局の同時収集・誤差分析 | `python3 -m gcs.rtk_tools.rtk_data_collector --simulate` |
| [`../../../../accuracy/README.md`](../../../../accuracy/README.md) | 機体間**相対測位**精度の実測（既知距離・PPK クロスチェック） | `gcs/accuracy/` |

### 8.1 ヒストグラム入力形式

`plot_rtk_histogram.py` は次の 2 形式に対応します
（出典: [`../../../../rtk_tools/plot_rtk_histogram.py`](../../../../rtk_tools/plot_rtk_histogram.py) の docstring）。

1. `rtk_data_collector.py` の出力（`horizontal_error_m` / `delta_alt_m` を含む）
2. `mavlink_bridge.py` の出力（`lat` / `lon` / `alt` を含む）
   ※ **`RTK_FIXED` 時の重心からの距離**を誤差として扱う

**必要ライブラリ**: `matplotlib` と `numpy`（未導入時はエラーメッセージを出して終了）。

### 8.2 解析ツールの位置づけ

`gcs/analyze_fix_log.py` / `gcs/accuracy/*` / `gcs/relpos/*` は
**CLI のまま維持**される解析・後処理ツールです（ルーチン運用は Web UI がリアルタイム集計）。

出典: [`../../../OPERATIONS.md`](../../../OPERATIONS.md) §4。

---

## 9. 動作確認（ハードウェア不要）

```bash
cd ~/rtk-pipeline-local

# システム全体の自己検証（合成データ）
python3 -m gcs.selftest

# 判定ロジック単体
python3 -m unittest gcs.test_fix_metrics gcs.test_rtcm_monitor \
    gcs.integration.test_runner gcs.preflight.test_checklist gcs.preflight.test_runner \
    gcs.ekf_failsafe.test_golden gcs.ekf_failsafe.test_checklist \
    gcs.ekf_failsafe.test_param_guard gcs.flight_test.test_metrics
```

出典: [`../../../RTK_PROCEDURES_MANUAL.md`](../../../RTK_PROCEDURES_MANUAL.md) §6、
[`../../../../flight_test/README.md`](../../../../flight_test/README.md) §9。

---

## 10. 注意事項

1. **各ターミナルで `.venv` を有効化**してから実行すること（§3）。
2. **UDP:14550 は排他**: 他の GCS（QGroundControl 等）が占有していると
   機体が表示されません。Mac 側で `gcs.server` が起動しているかも確認すること。
3. **`--target-host` の確認**: ラズパイ側の送信先が Mac のローカル IP
   （`192.168.2.1`）になっていること。
4. **基地局座標**は実際のアンテナ位置と数メートル以内で一致させること
   （[`../../common/fix_conditions.md`](../../common/fix_conditions.md) §1-A4）。
5. **AP 経由の疎通**: Mac の USB-LAN アダプタが AP に接続され `192.168.2.1` を持つこと、
   ラズパイが `192.168.2.x` を取得していること、`ping 192.168.2.1` が通ることを確認。
6. **秘密情報**: 認証情報は環境変数参照のみ（§7.4）。

出典: [`../../../RTK_PROCEDURES_MANUAL.md`](../../../RTK_PROCEDURES_MANUAL.md) §5 / §6。

---

## 11. 出典（`gcs/` 内のみ）

| ファイル | 参照箇所 |
|---|---|
| `gcs/server.py` | docstring（既定 `0.0.0.0:8000`、`--port 9000` の例、`Connect` 手順） |
| `gcs/rtk_tools/rtk_base_station_v2.py` | `Config`（`tcp_port = 2101`）/ `start()` / `_run_f9p_configuration()` |
| `gcs/config/base_station.json` | 基地局設定（`serial_port` / `fixed_*`） |
| `gcs/config/gcs.yml` | `connection_type` / `serial_port` / `udp_listen_port` / `drones` |
| `gcs/config/config.yaml` | `base_station.*` / `forward.*` / `monitor.*` / `pass_criteria.*` |
| `gcs/config/README.md` | 設定ファイル一覧 / 優先順位 / スキーマ検証 / シークレット |
| `gcs/rtk_tools/config_loader.py` | 設定パス解決 |
| `gcs/rtk_tools/plot_rtk_histogram.py` | docstring（入力 2 形式・必要ライブラリ） |
| `gcs/analyze_fix_log.py` | CSV 後処理 |
| `gcs/analyze_intervals.py` | docstring（任意区間の精度比較） |
| `gcs/rtk_tools/rtk_data_collector.py` | 基地局＋移動局の同時収集 |
| `gcs/accuracy/README.md` | 相対測位精度の実測 |
| `gcs/docs/OPERATIONS.md` | §1 操作カタログ / §2 REST / §3 WebSocket / §4 CLI 維持 |
| `gcs/README.md` | 機能表 / ディレクトリ構成 / クイックスタート |
| `gcs/selftest.py` | ハードウェア不要の自己検証 |
| `gcs/docs/RTK_PROCEDURES_MANUAL.md` | §1 / §1.1 / §2 / §3 / §5 / §6 |

> 関連: [`../f9p_base/README.md`](../f9p_base/README.md)（基地局 F9P）／
> [`../raspberrypi/README.md`](../raspberrypi/README.md)（対向の機体側）／
> [`../../common/fix_conditions.md`](../../common/fix_conditions.md)（条件の実値）