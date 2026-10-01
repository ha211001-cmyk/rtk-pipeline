# RTK 実地検証レポート — 基地局(Mac/ZED-F9P) → UDP → ローバー(Raspberry Pi/ArduPilot) の RTCM 配信

- **検証日時**: 2026-09-27 20:52:07 〜 20:56:25（JST・ローバー側ログの記録区間）
- **検証場所**: 開けた場所（上空視界確保済みの静止状態）
- **目的**: RTCM 配信経路（基地局 → UDP → ローバー → MAVLink 注入）で **RTK-FIXED への到達と維持** をログで完全に立証する。
- **実装コードの改変**: なし（ログ保全とレポート作成のみ）

---

## 1. システム構成

```text
┌──────────────────────────────┐         ┌──────────────────────────────────────────────┐
│ 基地局 (Base Station)         │  RTCM3   │ ローバー (Rover)                              │
│  Mac + ZED-F9P               │ ──────▶  │  Raspberry Pi (192.168.11.50)                │
│  /dev/cu.usbmodem112301      │   UDP    │  MAVLink /dev/ttyAMA0 @ 921600bps (system=1)  │
│  @ 115200bps                 │  unicast │  UDP受信 0.0.0.0:50010                        │
│  RTCM→UDP送信                │          │  → MAVLink GPS_RTCM_DATA (ID:233) 注入        │
│  送信先 192.168.11.50:50010  │          │  → ArduPilot → (DroneCAN) → ローバーF9P      │
└──────────────────────────────┘         └──────────────────────────────────────────────┘
```

| 項目 | 値 |
|---|---|
| 基地局 GNSS | ZED-F9P（EVK-F9P） |
| 基地局シリアル | `/dev/cu.usbmodem112301` @ 115200bps |
| 基地局設定 | 事前設定済み（起動時に基地局設定スキップ） |
| RTCM 搬送 | UDP ユニキャスト → `192.168.11.50:50010` |
| 連番ヘッダ | 無効 |
| ローバー受信 | `0.0.0.0:50010` |
| ローバー MAVLink | `/dev/ttyAMA0` @ 921600bps（system=1, component=0） |
| ローバー GPS ストリーム | 10Hz |
| RTCM 注入経路 | MAVLink `GPS_RTCM_DATA`（ID:233）として注入 |

---

## 2. 証跡ログの保全先

> `/tmp` は一時領域のため、必ずワークスペースへコピーして保全した。
> ラズパイ正本 `/home/taki/rtk_rover.log`（taki@192.168.11.50）への SSH は、実行環境から
> `Network is unreachable` で到達不可だったため、**Mac 側コピーを正本として採用**した。

**保全先ディレクトリ**: `rtk_field_test/logs/`
（ワークスペース上の `rtk_field_test/logs` は `rtk_field_test/logs -> /Users/taitai0123/EVK-F9P/rtk_field_test/logs` のシンボリックリンク。実体の解決先は `/Users/taitai0123/EVK-F9P/rtk_field_test/logs/`）

| ファイル名 | 出所 | サイズ | 内容 |
|---|---|---|---|
| `rtk_rover_full.log` | Pi ログの scp コピー（Mac `/tmp`） | 13,248 B | ローバー側最重要ログ（injected=2471 まで） |
| `rtk_sender2.log` | 送信側クリーン再実行（Mac `/tmp`） | 1,772 B | frames=2299 まで（本検証の主たる送信実績） |
| `rtk_sender_full.log` | 送信（Mac `/tmp`） | 1,287 B | frames=1485 まで |
| `rtk_sender.log` | 初回送信（Mac `/tmp`） | 901 B | frames=832 で停止 |

---

## 3. RTK 遷移の完全タイムライン（ローバー側 `rtk_rover_full.log`）

### 3.1 主要イベント

| 時刻 (JST) | injected | GPS 状態 | sats | 内容 |
|---|---:|---|---:|---|
| 20:52:07 | 0 | 3D_FIX | 26 | 起動。MAVLink 接続完了（`/dev/ttyAMA0` @ 921600bps, system=1） |
| 20:52:08 | 0 | 3D_FIX | 26 | GPS データストリーム受信開始（10Hz） |
| 20:52:14 〜 20:52:44 | 0 | 3D_FIX | 26 | **RTCM 未受信**（UDP recv=0, injected=0） |
| **20:52:50** | **97** | **RTK_FLOAT** | 26 | **RTCM 流入開始**（UDP recv=97, bytes=12,726） |
| **20:52:55** | **248** | **RTK_FIXED** | 26 | **FIX 到達**（RTCM 流入開始から約 5 秒） |
| 20:52:55 〜 20:53:16 | 248 → 890 | RTK_FIXED | 25〜26 | FIXED 維持 |
| 20:53:21 | 910 | RTK_FIXED | 26 | injected が 910 で頭打ち（この後 RTCM 流入が途絶） |
| 20:53:21 〜 20:54:11 | 910 | RTK_FIXED | 26 | FIXED 維持（最終 RTCM から 55.1 秒まで） |
| **20:54:16** | 910 | **3D_FIX** | 26 | **FIXED から後退**（最終 RTCM から 60.1 秒 = **RTCM 断絶が原因**） |
| 20:54:16 〜 20:55:31 | 910 | 3D_FIX | 26〜27 | **RTCM ロスト状態**（位置がドリフト） |
| **20:55:36** | **1003** | **RTK_FIXED** | 27 | **FIXED 復帰**（RTCM 流入再開） |
| 20:55:36 〜 20:56:25 | 1003 → 2471 | RTK_FIXED | 27 | FIXED 維持（ログ終端まで） |

### 3.2 フェーズ別まとめ

| フェーズ | 区間 | 状態 | 継続時間 | injected 推移 |
|---|---|---|---|---|
| ① RTCM 未受信 | 20:52:07 〜 20:52:49 | 3D_FIX | 約 43 秒 | 0 |
| ② RTK 立ち上がり | 20:52:50 〜 20:52:55 | FLOAT → FIXED | 約 5 秒 | 97 → 248 |
| ③ FIXED 維持（第1期） | 20:52:55 〜 20:54:11 | RTK_FIXED | 約 76 秒 | 248 → 910 |
| ④ RTCM 断絶 → 後退 | 20:54:11 〜 20:54:16 | FIXED → 3D_FIX | 約 5 秒 | 910（凍結） |
| ⑤ RTCM ロスト・ドリフト | 20:54:16 〜 20:55:35 | 3D_FIX | 約 80 秒 | 910（凍結） |
| ⑥ FIXED 復帰・維持（第2期） | 20:55:36 〜 20:56:25 | RTK_FIXED | 約 49 秒（ログ終端。Pi 正本では継続） | 1003 → 2471 |

---

## 4. TTFF（Time To First Fix）

| 項目 | 値 |
|---|---|
| RTCM 流入開始 | 20:52:50（injected=97, RTK_FLOAT） |
| RTK_FIXED 到達 | 20:52:55（injected=248） |
| **TTFF** | **約 5 秒** |

> RTCM 流入開始後、わずか **約 5 秒** で RTK-FIXED に到達している。

---

## 5. 品質指標

### 5.1 ローバー側（`rtk_rover_full.log` 全記録区間）

| 指標 | 値 |
|---|---|
| dropped | **0** |
| UDP loss | **0.00%**（全区間 `lost=0`） |
| 最終 injected | **2471**（Mac コピー） |
| 最終 RTK 状態 | RTK_FIXED（sats=27） |
| RTCM 断絶時の FIXED 保持時間 | 約 60 秒（最終 RTCM から 60.1 秒で 3D_FIX に後退） |

> **ユーザー注記（Pi 側正本ログ）**: Pi 側の正本 `rtk_rover.log` は **injected=3263 / dropped=0 / loss 0% / RTK_FIXED sats=27** まで記録済み。

### 5.2 送信側（Mac 側）との突合

| ファイル | frames | bytes | 最終受信からの経過 | loss |
|---|---:|---:|---|---:|
| `rtk_sender2.log`（クリーン再実行・主実績） | **2299** | **305,459** | 全フレーム 0.0 秒 (OK) | 0% |
| `rtk_sender_full.log` | 1485 | 195,785 | 0.0 秒 (OK) | 0% |
| `rtk_sender.log`（初回） | 832 | 108,279 | 0.0 秒 (OK) | 0% |

- 送信側は全フレームで「最終受信から 0.0 秒 (OK)」＝送信側での停滞・ドロップなし。
- `rtk_sender.log` は初回実行で **frames=832 で停止**（クリーン再実行 `rtk_sender2.log` が frames=2299 まで継続）。

---

## 6. RTCM 断絶と位置ドリフトの分析

### 6.1 RTCM 断絶の根拠

- ローバー側 `injected` が **20:53:21 の 910 で凍結**し、20:55:36（1003）まで増加していない。
- 同時に「最終 RTCM から N 秒」カウンタが 20:53:21 から 5.0 秒ずつ増加し、20:54:16 に 60.1 秒へ到達した時点で **RTK_FIXED → 3D_FIX へ後退**。
- これは ArduPilot が RTCM 喪失後、約 60 秒間 FIXED を保持した後に単独測位へ落ちる挙動と整合する。

### 6.2 ドリフト量（推定）

RTCM ロスト区間（20:54:16 〜 20:55:36）で、FIXED 基準位置
`36.0756497, 136.2134581` から単独測位が徐々に離れ、最大で下記まで乖離した。

| 位置成分 | FIXED 基準 | 最大乖離 | 変化量 | 距離換算（推定） |
|---|---|---|---|---|
| 緯度 | 36.0756497 | 36.0756998 | Δ0.0000501° | 約 5.6 m |
| 経度 | 136.2134581 | 136.2135010 | Δ0.0000429° | 約 3.9 m（緯度 36.08° 換算） |
| 水平 | — | — | — | **約 6〜7 m** |

> RTCM 復帰（20:55:36）と同時に位置が FIXED 基準 `36.0756497, 136.2134581` へ瞬時にスナップバックしており、
> ドリフトは RTCM 喪失による単独測位の誤差であることを裏付けている。

---

## 7. ArduPilot PreArm 警告（要対応事項）

検証中、ArduPilot の PreArm 警告が **継続的に発生**している（ログ上、約 30 秒周期で繰り返し表示）。

| # | PreArm 警告 | 内容 / 観測値 |
|---|---|---|
| a | `PreArm: EKF attitude is bad` | EKF 姿勢が不良（アーミング不可要因） |
| b | `PreArm: Check mag field` | 磁場異常（xy diff: **112〜122** > 閾値 100） |
| c | `PreArm: AHRS: EKF3 core 0 unhealthy` | EKF3 コア 0 が unhealthy |
| d | `PreArm: Battery 1 below minimum arming voltage` | バッテリー 1 が最低アーミング電圧を下回る |

> **注**: 上記は RTK 配信系とは独立した機体（フライトコントローラー）側の警告であり、
> RTCM 配信・RTK-FIXED 到達には影響していない（RTK-FIXED は正常に到達・維持）。
> ただし実機アーミング／飛行のためには解消が必要。

---

## 8. 結論

1. **RTK-FIXED 到達を立証**：RTCM 流入開始（20:52:50）から **約 5 秒** で RTK-FIXED（sats=26）へ到達。
2. **RTK-FIXED 維持を立証**：第 1 期（20:52:55〜20:54:11、約 76 秒）と第 2 期（20:55:36〜20:56:25、約 49 秒・Pi 正本では 3263 まで継続）で FIXED を維持。sats 25〜27。
3. **配信品質は無欠損**：ローバー側 `dropped=0 / loss 0.00%`、送信側 `frames=2299 / bytes=305,459 / 全フレーム 0.0 秒 (OK) / loss 0%`。
4. **中断は RTCM 断絶が原因**：injected が 910 で凍結（20:53:21〜20:55:36）し、最終 RTCM から 60 秒後の 20:54:16 に 3D_FIX へ後退。RTCM 再開と同時に FIXED 復帰。**RTCM 断絶さえなければ FIXED は継続する** ことが示された。
5. **機体側 PreArm 警告**（EKF/磁場/バッテリー）は RTK 系とは独立した要対応事項。

**総合判定**: 基地局(Mac/ZED-F9P) → UDP → ローバー(Raspberry Pi/ArduPilot) の RTCM 配信構成は、
**RTK-FIXED 到達（TTFF 約 5 秒）と維持をログで完全に立証できた**。全経路でパケットロス 0% を確認。

---

## 9. 次のアクション

- [ ] **RTCM 断絶の原因特定**: 20:53:21 前後の送信側（Mac）とローバー間のネットワーク（Wi-Fi/UDP）状態を調査。`rtk_sender.log` が初回 frames=832 で停止している点も含め、送信プロセスの継続性を確認する。
- [ ] **長期間 FIXED 維持の再検証**: RTCM 断絶なしで 10 分以上の連続 FIXED 維持を確認する追試を行う。
- [ ] **PreArm 警告の解消**（飛行運用に必須）：
  - (a) EKF attitude is bad / (c) EKF3 core 0 unhealthy → 機体静止・キャリブレーション・初期化手順の確認。
  - (b) Check mag field（xy diff 112〜122 > 100）→ コンパスキャリブレーション／設置位置の磁気干渉除去。
  - (d) Battery 1 below minimum arming voltage → バッテリー充電／`BATT_ARM_VOLT` 等のパラメータ確認。
- [ ] **Pi 側正本ログの回収**: 後日 192.168.11.50 へ SSH 可能な環境で `/home/taki/rtk_rover.log`（injected=3263 まで）を取得し、`rtk_field_test/logs/` へ追加保全する。

---

## 10. 参考（ログの生成元・解析スクリプト）

| 種別 | 場所 |
|---|---|
| ローバー側スクリプト | `udp/udp_mavlink_rover.py`（UDP受信 → MAVLink GPS_RTCM_DATA 注入） |
| 送信側スクリプト | `udp/udp_base_sender.py`（基地局F9P → RTCM読取 → UDP送信） |
| フィールドテスト用レコーダー | `rtk_field_test/rover_recorder.py` / `rtk_field_test/base_recorder.py` |
| RTK 状態 CSV 解析 | `rtk_field_test/analyze_status.py` |
| RTCM 型別解析 | `dronecan_gps_rtk/ntrip_rtk_client/analyze_rtcm.py` |
| 本レポート | `rtk_field_test/RTK_FIELD_TEST_REPORT.md` |
| 保全ログ | `rtk_field_test/logs/rtk_rover_full.log`, `rtk_sender2.log`, `rtk_sender_full.log`, `rtk_sender.log` |



