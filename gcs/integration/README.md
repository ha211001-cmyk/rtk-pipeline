# gcs/integration — GCS バックエンドコア（MAVLink 受信 + RTCM 送信 + GUI）

本番アーキテクチャ（**DroneCAN + MAVLink + UDP**）の GCS 側バックエンドです。

```
[ローバー群 (Raspberry Pi / MAVProxy / ArduPilot)]
        │  MAVLink (UDP): GPS_RAW_INT / HEARTBEAT / SYS_STATUS
        ▼
[GCS PC]  MavlinkTelemetryReader（受信スレッド）──▶ 機体ステータス一覧 GUI
        ▲
        │  RTCM3 (UDP ファンアウト)
[GCS PC]  RtcmCaster（送信スレッド）◀── USB ── [基地局 F9P]
```

旧来の「UBX シリアル/TCP 直読」方式は廃止し、MAVLink（UDP）受信と
RTCM（UDP）配信に一本化しています。

---

## 1. 要件(1)〜(4)の実装場所

| 要件 | 実装 | ファイル |
|---|---|---|
| (1) MAVLink テレメトリ受信 | `MavlinkTelemetryReader` | `gcs/integration/sources.py` |
| (2) RTCM ファンアウト | `RtcmCaster` | `gcs/integration/rtcm_caster.py` |
| (3) 2スレッド並行稼働 | `GcsBackend`（+ CLI） | `gcs/integration/runner.py` |
| (4) 機体ステータス一覧 GUI | ~~`GcsMonitorWindow`~~ → **退避**（Web ダッシュボードが代替） | `gcs/_retired/integration_gui_pyqt5/` |
| 表示行変換（純関数） | `format_vehicle_rows` | `gcs/integration/display.py` |
| 統合エントリポイント | `main()`（ヘッドレス） | `gcs/integration/main.py` |
| 単体テスト | `test_*.py` | `gcs/integration/` |

### (1) MavlinkTelemetryReader（sources.py）
- pymavlink で `udpin://0.0.0.0:14550` を待ち受け、受信スレッドで MAVLink を処理。
- 抽出内容:
  - **GPS_RAW_INT**: `fix_type`（0..6）・衛星数・緯度/経度/高度・EPH/EPV
  - **HEARTBEAT**: フライトモード（`mode_string_v10`）・ARM 状態・機体種別
  - **SYS_STATUS**: バッテリー電圧/電流/残量
- 状態は **`system_id`（機体ID）をキーとする辞書** `_vehicles` に保持（複数台対応）。
  - `vehicles()` / `get_state(system_id)` / `snapshot()` で取得。
- 旧 `RoverUbxReader` は削除せず `DeprecationWarning` を発する非推奨クラスとして残置
  （`gcs/preflight` 等の既存参照との後方互換）。

### (2) RtcmCaster（rtcm_caster.py）
- 基地局 F9P（USB シリアル）から RTCM3 バイト列を読み、`Rtcm3StreamParser` で
  フレーム抽出し、登録された複数 UDP エンドポイントへ一斉送信する。
- `add_destination(host, port)` / `remove_destination(host, port)` で送信先を
  **動的に追加・削除**できる。
- `source_port=None` にすると手動 `feed(bytes)` モード（自己検証/テスト用）。

### (3) GcsBackend（runner.py）
- `MavlinkTelemetryReader`（受信）と `RtcmCaster`（送信）を**別スレッドで並行稼働**。
- `snapshot()` で「機体ごとのステータス + MAVLink/RTCM 統計」を一括取得。
- 旧 `IntegrationRunner`（UBX 直読）は削除済み。

### (4) GcsMonitorWindow（gui.py）— 退避済み
- PyQt5 の `QTimer` ポーリング + `QTableWidget` 一覧 GUI だったが、Phase 0 統合計画（§6）に
  基づき **Web ダッシュボード（`python3 -m gcs.server`）に置換**し、`gcs/_retired/integration_gui_pyqt5/` へ退避。
- 表示行変換の純関数は `gcs/integration/display.py`（`format_vehicle_rows`）に移設。

---

## 2. 使い方

```bash
cd <リポジトリルート>
pip install -r requirements.txt    # pymavlink / PyQt5 を含む

# ヘッドレスバックエンド（コンソール監視のみ。GUI は Web ダッシュボードに一本化）
python3 -m gcs.integration.main \
    --mavlink-port 14550 \
    --base-port /dev/ttyACM0 \
    --dest 192.168.1.10:14550 --dest 192.168.1.11:14550

# 個別エントリポイント
python3 -m gcs.integration.runner   # ヘッドレスバックエンド

# メイン UI（Web ダッシュボード）はこちら
python3 -m gcs.server
```

CLI 引数（runner / main 共通）:
- `--mavlink-host` / `--mavlink-port`: MAVLink 受信 UDP（既定 `0.0.0.0:14550`）
- `--base-port` / `--base-baud`: 基地局 F9P のシリアルポート / ボーレート
- `--dest HOST:PORT`: RTCM 配信先（複数指定可）

---

## 3. 依存関係

`requirements.txt` に追記済み:
- `pymavlink>=2.4.0`
- `PyQt5>=5.15`

---

## 4. テスト（実ハードウェア不要）

```bash
cd <リポジトリルート>
python3 -m unittest gcs.integration.test_mavlink_telemetry \
                       gcs.integration.test_rtcm_caster \
                       gcs.integration.test_runner -v
```

- `test_mavlink_telemetry.py`: 機体別分類・fix_type・フライトモード・バッテリー抽出
- `test_rtcm_caster.py`: 送信先の動的追加/削除・UDP ファンアウト・start/stop
- `test_runner.py`: `GcsBackend` の2スレッド並行稼働・snapshot・GUI 行変換

---

## 5. 設計メモ

- 受信・送信はそれぞれ独立したデーモンスレッドで動き、`GcsBackend` がライフサイクル
  を一元管理する（`start()` / `stop()`）。
- `MavlinkTelemetryReader.process_message()` はメッセージ処理を純粋ロジックとして
  分離しており、実機なしで単体テストできる。
- `display.format_vehicle_rows()` も表示変換を純関数化し、Qt なしでテストできる。
