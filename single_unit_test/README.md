# single_unit_test — 実機2台（基地局 + ローバー）による RTK Fix 達成時 再現・検証テスト

実機の **F9P を 2台**（基地局 Base + ローバー Rover）使い、基地局の RTCM 補正データを
ローバーへ供給して **RTK Fix（固定解）達成時を再現・検証する**ためのテスト一式です。

> **重要**: RTK Fix は基地局の RTCM 補正データが必須であり、**F9P 1台だけでは達成できません**。
> 本フォルダは「F9P 1台による測位実験」ではありません。また、ハードウェアを使わない
> ソフトウェア単体テストでもありません（RTCM 補正の授受と実際の Fix 判定に実機 2台が必要です）。

## 1. 背景・目的

- 基地局 F9P（TMODE3 Fixed Mode）が生成する RTCM3（1006/1077/1087/1097/1127/1230 等）を
  ローバー F9P に届けることで、ローバーが RTK Fixed に到達することを**実機で再現**する。
- 到達・維持を **タイムスタンプ付きの RTK 状態ログ（CSV）** に記録し、
  既存の `analyze_status.py` で **「RTK FIXED 到達」「TTFF（初回 FIXED までの秒数）」「維持時間」** を判定する。
- 判定ロジック・基地局設定・RTCM 注入ロジックは **新規実装せず**、リポジトリ内の既存資産
  （`archive/rtk_field_test/` 等）を thin wrapper 経由で再利用する。

### RTK Fix 到達時の判定基準

| 出力元 | 指標 | 到達値 |
| :--- | :--- | :--- |
| NMEA GGA | quality indicator（6 番目フィールド） | **4**（RTK Fixed） |
| MAVLink | `GPS_RAW_INT.fix_type` | **6**（RTK_FIXED） |
| UBX | `UBX-NAV-PVT.flags.carrSoln` | **2**（Fixed） |
| ArduPilot | GPS status 表記 | `RTK Fixed`（RTK_FIXED） |

本テストの自動判定は **MAVLink `fix_type == 6`** を主指標とし、`run_analyze.py`（→
`archive/rtk_field_test/analyze_status.py`）が「✅ RTK_FIXED 到達」を出力すれば再現成功です。

## 2. 必要機材

| 機材 | 役割 | 備考 |
| :--- | :--- | :--- |
| ZED-F9P（rtk-pipeline）× 1 | **基地局** | 基地局側ホストに USB 接続。TMODE3/RTCM3 を設定 |
| ZED-F9P（rtk-pipeline / H-RTK F9P 等）× 1 | **ローバー** | ArduPilot（Pixhawk）に DroneCAN 接続（実績構成） |
| Pixhawk / ArduPilot | RTCM 中継（DroneCAN 転送） | ローバー F9P を DroneCAN で搭載 |
| 基地局側ホスト（Mac mini 等） | `run_base.py` / `run_survey.py` を実行 | 基地局 F9P と USB 接続 |
| ローバー側ホスト（Raspberry Pi 等） | `run_rover.py` を実行 | Pixhawk と UART(MAVLink) 接続 |

> 実績では「基地局 F9P → 基地局側ホスト（Mac）→ WiFi(UDP) → ローバー側ホスト（ラズパイ）
> → MAVLink GPS_RTCM_DATA → ArduPilot → DroneCAN → ローバー F9P」の経路で
> **RTK-FIXED 到達（TTFF 約 5 秒）** を立証済みです（後述「実績」参照）。

## 3. システム構成（標準：UDP/MAVLink 中継）

本リポジトリで **RTK FIXED 到達の実績がある** 経路を標準とします。

```text
┌──────────────────────────────┐   RTCM3    ┌──────────────────────────────────────────────┐
│ 基地局 (Base)                 │ ─────────▶ │ ローバー (Rover)                              │
│  基地局ホスト(Mac等) + F9P     │   UDP      │  ローバーホスト(Raspberry Pi) + Pixhawk       │
│  run_base.py                  │  unicast   │  run_rover.py                                  │
│  (TMODE3/RTCM3設定→RTCM送信)  │            │  (UDP受信→MAVLink GPS_RTCM_DATA注入)          │
│  送信先: <rover-host>:50010    │            │  → ArduPilot → (DroneCAN) → ローバー F9P      │
└──────────────────────────────┘            └──────────────────────────────────────────────┘
```

- **標準 = UDP/MAVLink 中継**（実績あり）。基地局とローバーを別ホストで運用する。
- **シリアル直結**（基地局 TX → ローバー RX）も可能だが、本リポジトリの実績・既存スクリプトの
  主対象ではないため「代替構成」として後述する。

## 4. フォルダ構成

```text
single_unit_test/
├── README.md            # このファイル（機材・構成・手順・判定基準）
├── run_survey.py        # ⓪ 基地局座標の再測（standalone_obs.py の wrapper）
├── run_base.py          # ① 基地局 TMODE3/RTCM3 設定 + RTCM 出力 + UDP送信（base_recorder.py の wrapper）
├── run_rover.py         # ② ローバー UDP受信 → MAVLink注入 + RTK状態CSV（rover_recorder.py の wrapper）
├── run_analyze.py       # ③ RTK FIXED 到達判定（analyze_status.py の wrapper）
├── run_gnss_mode.py     # （任意）ローバー GLONASS ON/OFF（set_gnss_mode.py の wrapper）
├── run_rtcm_rate.py     # （任意）基地局 RTCM レート変更（set_rtcm_rate.py の wrapper）
└── logs/                # RTCM（.rtcm3）/ RTK 状態 CSV の保存先（.gitignore 対象）
```

## 5. スクリプト一覧（wrapper → 再利用元）

各 `run_*.py` は **判定・設定・注入ロジックを新規実装せず**、`archive/` 配下の既存資産を
`sys.path` に追加して import し、`main()` を呼ぶだけの thin wrapper です。

| 本フォルダの wrapper | 再利用元（既存資産） | 実行場所 | 主な依存 |
| :--- | :--- | :--- | :--- |
| `run_survey.py` | `archive/base_station_verify/rtcm_compare/standalone_obs.py` | 基地局側ホスト | `pyserial` `pyubx2` `pyyaml` |
| `run_base.py` | `archive/rtk_field_test/base_recorder.py` | 基地局側ホスト | `pyserial`（設定時 `pyubx2`） |
| `run_rover.py` | `archive/rtk_field_test/rover_recorder.py` | ローバー側ホスト | `pyserial` `pymavlink` |
| `run_analyze.py` | `archive/rtk_field_test/analyze_status.py` | どちらでも | 標準ライブラリのみ |
| `run_gnss_mode.py` | `archive/rtk_field_test/set_gnss_mode.py` | ローバー側ホスト | `pymavlink` |
| `run_rtcm_rate.py` | `archive/rtk_field_test/set_rtcm_rate.py` | 基地局側ホスト | `pyserial` `pyubx2` |

## 6. 依存ライブラリ

```bash
# 基地局側ホスト（run_survey / run_base / run_rtcm_rate）
pip install pyserial pyubx2 pyyaml

# ローバー側ホスト（run_rover / run_gnss_mode。pymavlink は専用 venv を推奨）
python3 -m venv ~/Mavlink_venv
~/Mavlink_venv/bin/pip install pyserial pymavlink
```

> リポジトリ全体（`archive/` 配下の再利用元を含む）を両ホストに用意してください。
> `run_rover.py` は `archive/rtk_base_mavlink/`（`mavlink_comm` / `rtcm_injector`）を、
> `run_base.py` は `archive/base_station_verify/rtcm_compare/f9p_configurator_v2.py` を内部で参照します。

## 7. 標準実行手順（実機2台）

基地局・ローバーを開けた場所へ設置し（上空視界を確保・アンテナ静止）、以下を実行します。

### ⓪ 基地局座標の再測（新規場所のみ・基地局側ホスト）

基地局を動かした場合は **必ず** 単独測位で座標を取り直します（旧座標のままだと
RTK_FIXED になっても出力位置が移動距離ぶんズレるため）。

```bash
cd ~/rtk-pipeline/single_unit_test
python3 run_survey.py --set-rover --duration 120 --save
```

- `--set-rover` で一時的に移動局化（TMODE3 を解除）して実測する
- 出力の **平均 緯度 / 経度 / 高度（楕円体高 HAE）** を控える（次の `--lat/--lon/--alt` に使用）
  - `--alt` には **HAE（楕円体高）** を使う（MSL ではない）
- ポートが見つからない場合は `--port /dev/cu.usbmodemXXXX` を明示指定

### ① 基地局を起動（基地局側ホスト・後から起動）

```bash
cd ~/rtk-pipeline/single_unit_test

# 新規場所（再設定が必要）の場合：座標を指定して TMODE3 + RTCM3 を設定（Flash 保存 → 自動再検出）
python3 run_base.py --lat <新緯度> --lon <新経度> --alt <新高度HAE>

# RAM のみで設定（Flash に残さない）
python3 run_base.py --lat <新緯度> --lon <新経度> --alt <新高度HAE> --no-save

# 設定済みの基地局をそのまま記録（座標指定なし）
python3 run_base.py
```

- RTCM が `logs/rtcm_base_*.rtcm3` に保存されつつ、ローバーへ UDP 送信される
- 送信先は既定 `raspi5.local:50010`（`--host` / `--port` で変更可）
- 記録のみ（UDP 送信なし）にしたい場合は `--no-udp`

### ② ローバーを起動（ローバー側ホスト・先に起動）

```bash
cd ~/rtk-pipeline/single_unit_test
source ~/Mavlink_venv/bin/activate
python3 run_rover.py --rtscts --log-dir logs
```

- `UDP受信待機中: 0.0.0.0:50010` と表示されるまで待つ
- RTK 状態が `logs/rtk_status_*.csv` に **1秒毎** 記録される
- 起動前は `sudo systemctl stop mavlink-router.service` で `/dev/ttyAMA0` の競合を回避する

### ③ 静止観測

基地局側（`run_base.py`）で `frames=N` が増加し、ローバー側（`run_rover.py`）で
`[STATUS] injected=N` が増加して `GPS:RTK_FLOAT → GPS:RTK_FIXED` に遷移するのを待つ。

- 実績では RTCM 流入開始から **約 5 秒** で FIXED 到達（環境に依存）
- 目安：数秒〜数分。`RTK_FIXED` 到達後も **数十秒〜数分** 維持してから終了する

### ④ 終了

両方の端末で **Ctrl+C**。msgType 別集計と保存先パスが表示されます。

### ⑤ 判定（再現成功の確認）

ローバー側ホスト（または CSV をコピーしたホスト）で、`run_rover.py` が出力した
RTK 状態 CSV を解析します。

```bash
cd ~/rtk-pipeline/single_unit_test
python3 run_analyze.py logs/rtk_status_YYYYMMDD_HHMMSS.csv
```

出力に以下が含まれていれば **再現成功**：

```text
--- RTK FIXED 判定 ---
  ✅ RTK_FIXED 到達（開始から N.N 秒後）
```

- `❌ RTK_FIXED 未到達` の場合は、FIX 別継続時間・衛星数（sats/nsats）・基線長（base）・
  位置安定性（std）を確認して切り分ける。詳しい切り分け項目（衛星数/C/N0/基線長/RTCM 連続性等）は
  [`archive/udp/README.md`](../archive/udp/README.md) の「FIX しない場合の切り分け項目」を参照。

## 8. 設定の変更（RAM のみ vs Flash 保存）と復元手順

RTK Fix の再現に必須ではありませんが、切り分け・帯域調整で使う設定変更と復元方法です。

| 対象 | コマンド | 保存先（既定） | 復元方法 |
| :--- | :--- | :--- | :--- |
| 基地局 TMODE3/RTCM3 設定 | `run_base.py --lat … --lon … --alt …` | **Flash**（`--no-save` で RAM のみ） | Flash へ残した場合は `run_survey.py --set-rover` で移動局化（TMODE3 解除） |
| 基地局 GLONASS RTCM 出力 | `archive/udp/glonass_toggle.py --off` | **RAM のみ** | `archive/udp/glonass_toggle.py --on`、または電源再投入 |
| ローバー GLONASS | `run_gnss_mode.py --no-glonass` | **Pixhawk 永続** | `run_gnss_mode.py --restore <元値>`（**必ず実施**。反映には Pixhawk/GPS 再起動が必要） |
| 基地局 RTCM レート | `run_rtcm_rate.py --rate 1` | **RAM のみ** | `run_rtcm_rate.py --restore 200`（200ms=5Hz）。`--save` を付けた場合は Flash にも永続 |

**復元の原則**：

- `--no-save` / 既定 RAM のみの変更は **電源再投入で自動復元** される（恒久化しない）。
- `--save` / Flash 保存 / Pixhawk パラメータ変更は **実験後に必ず手動で元へ戻す**。
  - 特に `run_gnss_mode.py --no-glonass` は Pixhawk に永続保存されるため、画面に表示される
    「元値」を控えておき、`--restore <元値>` で復元すること。

## 9. 代替構成：シリアル直結（基地局 TX → ローバー RX）

ArduPilot を挟まず、**基地局 F9P の UART1 TX → ローバー F9P の UART1 RX** を直結する簡易構成です
（GND 共通・レベル整合に注意）。本リポジトリの実績・主対象は UDP/MAVLink 中継のため、
ここでは参考として記載します。

1. 基地局は `run_base.py --no-udp`（または既存 `f9p_configurator_v2.py`）で
   TMODE3/RTCM3 を設定（RTCM は USB と UART1 の両方に出力される）。
2. 配線：基地局 F9P UART1 TX → ローバー F9P UART1 RX、GND 共通。
3. ローバー F9P の USB を任意のホストへ接続し、NMEA GGA（quality=4）または
   UBX-NAV-PVT（carrSoln=2）を読み取って Fix を確認する。

> ローバー F9P が DroneCAN GPS（Pixhawk 配下）の場合、シリアル直結には配線の組み替えが必要です。
> 既存の `archive/udp/udp_rover.py` / `archive/udp/direct_inject.py` も参照してください。

## 10. 実績（既存レポート）

- [`archive/rtk_field_test/RTK_FIELD_TEST_REPORT.md`](../archive/rtk_field_test/RTK_FIELD_TEST_REPORT.md)
  — 基地局 Mac/ZED-F9P → UDP → ローバー Raspberry Pi/ArduPilot の RTCM 配信で、
  **RTK-FIXED 到達（TTFF 約 5 秒）と維持（dropped=0 / loss 0%）** をログで立証した記録。
- [`archive/rtk_field_test/README.md`](../archive/rtk_field_test/README.md)
  — 実地手順の詳細（GLONASS 両側オフ検証を含む）と解析コマンド。

## 11. 注意点

- **認証情報**: 本テストは自己基地局（構成B）による RTK のため、**NTRIP/イチミルの
  ユーザー名・パスワードは一切使用しません**（新規にハードコードもしません）。
- **シリアル排他アクセス**: 基地局 F9P のシリアルポートを `run_base.py` と `run_rtcm_rate.py` 等で
  同時に開かないこと（不安定化の原因）。
- **基地局座標**: 基地局を動かしたら必ず `run_survey.py` で再測し、`run_base.py` で再設定すること。
- **復元**: Flash 保存・Pixhawk パラメータの変更は実験後に元へ戻す（上記「設定の変更」参照）。

## 12. 更新履歴

- 2026-09-28: 『F9P 1台による測位実験』の位置づけを廃止し、**『実機2台（基地局 + ローバー）による
  RTK Fix 達成時 再現・検証テスト』** に全面改訂。
  - `archive/rtk_field_test/` 等の既存資産を再利用する thin wrapper（`run_*.py`）を整備。
  - 判定は既存 `analyze_status.py` を再利用（新規判定ロジックなし）。
  - 標準構成を UDP/MAVLink 中継とし、設定変更（RAM/Flash の別）と復元手順を明記。

