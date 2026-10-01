# gcs/hw_verify — 物理ハードウェア実地検証の準備

実装済みの **①②③監視モジュール（TCP 対応版）** と **runner.py
（`gcs/integration/runner.py`）** を、実際のハードウェアで検証するための
**準備手順**をまとめたドキュメントです。

- **①** コンフィグ自動診断 = `gcs/backend/f9p_configurator.py`（`F9pConfigGuard`）
- **②** RTK ステータス監視 = `gcs/fix_metrics.py`（`compute_metrics`）
- **③** RTCM リンク健全性監視 = `gcs/rtcm_monitor.py`（`CorrectionMonitor`）

> 本タスクは「準備」であり、既存の実装ファイル（①②③モジュール・`runner.py`・
> `config.yaml`）は **改変しません**。成果物は `gcs/config/config.local.example.yaml`
> （設定テンプレート）と本ディレクトリの `README.md` / `check_connectivity.py` です。

---

## 0. 成果物

| ファイル | 役割 |
|---|---|
| `gcs/config/config.local.example.yaml` | TCP 接続の設定テンプレート（要件3） |
| `gcs/hw_verify/README.md` | 本ドキュメント（準備・疎通確認手順） |
| `gcs/hw_verify/check_connectivity.py` | 疎通確認ヘルパー（ping / TCP ポート / シリアル認識） |

---

## 1. 物理構成図（要件1・2）

```
[基地局 F9P] ──USB直結──▶ [GCS PC]                     … 要件2（TMODE3 / RTCM3 出力）
                              │
                              │ 同一 Wi-Fi ネットワーク
                              ▼
[機体 Raspberry Pi 5] ◀── Wi-Fi ──┐
        │                         │
        └─ DroneCAN Serial Forwarding（F9P シリアル ⇄ TCP:5001）
        └─ ローバー F9P（DroneCAN 経由で接続）           … 要件1（USB 接続不要）
```

- **GCS PC ⇔ 機体 RPi5** は **Wi-Fi のみ**（USB ケーブルは接続しない）。
- **基地局 F9P** は **GCS PC へ USB 直結**する。

---

## 2. 要件1 — ローバー（ドローン側）の完全ワイヤレス化

1. **GCS PC と機体 Raspberry Pi 5 を同一 Wi-Fi ネットワークに接続**する。
   - 同一サブネット（例: `192.168.11.0/24`）であることを確認。
   - Wi-Fi 設定は既存の `archive/wifi_scripts/`（`setup_wifi.sh` 等）も参考にできる。
2. **機体 RPi5 の IP アドレスを確認**する（RPi5 上で実行）:

   ```bash
   hostname -I      # 例: 192.168.11.50
   ip addr          # wlan0 の inet を確認
   ```

3. **機体側で DroneCAN Serial Forwarding サービスが起動していること**を確認する。
   これは F9P のシリアル（DroneCAN 経由）を TCP（既定 `5001`）に橋渡しするサービスで、
   GCS 側の①（`F9pConfigGuard`）はこの TCP に UBX を送受信する
   （`gcs/backend/README.md` §8 参照）。
   - サービスのポートは既定 `5001`（環境に合わせて `config.local.yaml` の `port` と一致させる）。
   - 機体側で `ss -lntp | grep 5001` などで待ち受けを確認できる。

> GCS PC ⇔ 機体の USB ケーブルは不要です。① は `forward.mode=tcp` で機体 RPi5 経由に
> 接続します（`gcs/integration/runner.py` の `run_phase1()` が `F9pConfigGuard(host, port)`
> を生成）。

---

## 3. 要件2 — 基地局（自作 F9P 側）の USB 直結と TMODE3 設定

1. **基地局 F9P を GCS PC へ USB 直結**する。
2. **上空が開けた場所**にアンテナを設置する（マルチパス・上空視界が RTK-FIXED 到達に
   大きく影響するため）。
3. **TMODE3（固定点設定）＋ RTCM3 出力**にする。

   既存ツールで基地局を設定します（設定は Flash 保存されます）:

   ```bash
   cd ~/rtk-pipeline

   # 方法 A: 統合ランナーの Phase 0（基地局設定）を使う
   python3 gcs/integration/runner.py --setup-base --skip-phase1
   ```

   > `--setup-base` は `gcs/integration/runner.py` の `run_base_setup()` を呼び、
   > `archive/base_station_verify/rtcm_compare/f9p_configurator_v2.py` の
   > `F9pConfiguratorV2.configure(lat, lon, alt, save)` を再利用して
   > TMODE3（`CFG_TMODE_MODE=2`, `CFG_TMODE_POS_TYPE=1`）と RTCM3 MSM7 出力を設定します。

   ```bash
   # 方法 B: 基地局単体で設定＋RTCM 読取
   cd ~/rtk-pipeline/udp
   python3 udp_base_sender.py
   ```

   - 固定座標は `gcs/config/config.yaml` の `base_station.fixed_lat/lon/alt`
     （既定: 福井大学 `36.0751418 / 136.2133477 / 44.80`）。
     **場所を変えた場合は、新座標を単独測位で再取得して `config.local.yaml` で上書き**する
     （手順は `archive/udp/README.md` の「場所を変えて再テストする場合」を参照）。
   - 設定後、RTCM3 フレーム（先頭バイト `0xD3`）が流れ続けていることを確認する
     （`udp_base_sender.py` の `frames=N` が増えていれば OK）。

---

## 4. 要件3 — `config.local.yaml` の作成（ローバー側 TCP 接続先の定義）

`config.local.yaml` は gitignore 対象（コミットされない）ため、テンプレート
`config.local.example.yaml` をコピーして編集します。

```bash
cd ~/rtk-pipeline
cp gcs/config/config.local.example.yaml gcs/config/config.local.yaml
```

`config.local.yaml` の `forward` セクションを実機に合わせて編集します。

```yaml
# gcs/config/config.local.yaml
forward:
  mode: tcp                 # "tcp"（DroneCAN Serial Forwarding）
  host: 192.168.11.50       # ★ 機体 RPi5 の実 IP アドレスに置き換える
  port: 5001                # DroneCAN Serial Forwarding の TCP ポート
```

- **`host` は必ず実機 RPi5 の IP アドレスに置き換えてください**（`192.168.11.50` は例）。
- `port` は機体側の DroneCAN Serial Forwarding サービスのポートと一致させます（既定 `5001`）。
- `gcs/config/loader.py` が `config.yaml` → `config.local.yaml` の順に deep merge するため、
  「上書きしたいキーだけ」を書けば OK です（`forward` 以外は `config.yaml` の値が使われます）。

---

## 5. 要件4 — 疎通確認（機体 RPi5 への TCP 到達 / 基地局 USB シリアル認識）

### 5-1. ヘルパーで一括確認（推奨）

```bash
cd ~/rtk-pipeline
python3 gcs/hw_verify/check_connectivity.py --host 192.168.11.50 --port 5001
```

出力は `[1] ICMP 疎通（ping）` → `[2] TCP ポート到達` → `[3] シリアルポート認識` の順に
OK/NG を表示します。すべて OK になれば準備完了です。

```bash
# シリアル認識のみ確認する場合
python3 gcs/hw_verify/check_connectivity.py --serial-only

# ツール自体の動作確認（実機なし）
python3 gcs/hw_verify/check_connectivity.py --self-test
```

### 5-2. 手動で確認する場合

**(a) 機体 RPi5 への ping（ICMP 疎通）**

```bash
ping -c 4 192.168.11.50
```

**(b) TCP ポート到達（DroneCAN Serial Forwarding のポート）**

```bash
# macOS / Linux（nc が使える場合）
nc -zv 192.168.11.50 5001

# または Python ワンライナー
python3 - <<'PY'
import socket
s = socket.socket()
s.settimeout(3)
try:
    s.connect(("192.168.11.50", 5001))
    print("TCP 5001: OK")
except Exception as e:
    print("TCP 5001: NG —", e)
finally:
    s.close()
PY
```

**(c) 基地局 USB シリアルポートの認識**

```bash
# macOS（GCS PC が Mac の場合）
ls -l /dev/cu.usbmodem* /dev/tty.usbmodem*

# Linux（GCS PC がラズパイ等の場合）
ls -l /dev/ttyACM* /dev/ttyUSB*
```

- 基地局 F9P は通常 `/dev/cu.usbmodemXXXX`（macOS）または `/dev/ttyACM0`（Linux）として
  認識されます。
- `gcs/config/config.yaml` では `base_station.serial_port: null`（自動検出）のため、
  ポートが複数ある場合は `config.local.yaml` に明示指定することを推奨します:

  ```yaml
  base_station:
    serial_port: /dev/cu.usbmodemXXXX
  ```

---

## 6. 本番実行（準備完了後）

準備と疎通確認が完了したら、統合ランナーを実行します。

```bash
cd ~/rtk-pipeline
source .venv/bin/activate        # または ~/Mavlink_venv

# ①→②→③ を順番に実行（設定は gcs/config/ から読み込み。①は TCP 接続）
python3 gcs/integration/runner.py

# 基地局も同時に設定する場合
python3 gcs/integration/runner.py --setup-base

# 観測時間を上書き
python3 gcs/integration/runner.py --duration 300

# 実機なしの自己検証（動作確認用）
python3 gcs/integration/runner.py --self-test
```

---

## 7. トラブルシューティング

| 症状 | 考えられる原因 | 対処 |
|---|---|---|
| `ping` が NG | 同一 Wi-Fi でない／IP 誤り | GCS PC と RPi5 を同一ネットワークへ。`hostname -I` で IP を再確認 |
| `TCP 5001` が NG | Forwarding サービス未起動／ポート不一致 | 機体側でサービス起動を確認。`ss -lntp \| grep 5001` で待ち受け確認 |
| シリアルが見つからない | USB 未接続／権限 | 基地局 F9P を USB 直結。`ls /dev/cu.usbmodem*` を確認 |
| ① が接続エラーになる | `config.local.yaml` の host が未置換 | `host` を実 IP に置換して再実行 |
| 基地局 RTCM3 が出ない | TMODE3 設定失敗／座標誤り | `--setup-base` を付け直す。場所変更時は新座標を再設定 |

---

## 8. 前提・注意

- **依存ライブラリ**: `pyserial` + `pyubx2`（①・基地局設定）、`PyYAML`（設定読込）。
  `check_connectivity.py` は標準ライブラリのみで動作します。
- **シリアル排他**: 基地局 F9P の USB ポートは `udp_base_sender.py` 等と同時に開かないこと。
- **既存ファイルの無改変**: 本タスクは既存実装（①②③モジュール・`runner.py`・`config.yaml`）
  を一切改変していません。設定の上書きは `config.local.yaml`（gitignore 対象）のみで行います。
- **機体側の前提**: 機体 RPi5 上で DroneCAN Serial Forwarding サービス（F9P シリアル ⇄ TCP）
  が稼働していることが前提です（`gcs/backend/README.md` §8 参照）。

