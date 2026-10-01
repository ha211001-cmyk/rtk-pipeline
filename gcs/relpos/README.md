# gcs/relpos — 複数ローバー RELPOSNED ペアリング（協調搬送向け自作 GCS 拡張）

協調搬送に向けた自作 GCS の拡張として、複数ローバーが出力する
**UBX-NAV-RELPOSNED**（基準局からの相対位置）を読み出し、**可視化**し、
**ログ記録**するモジュール群です。

## 最重要要件（設計の核）

機体間の相対位置は、各ローバーの RELPOSNED を「単に都度表示」するのではなく、
**両ローバーの値を同一 iTOW（GPS 時刻エポック）でペアリングしてから差分を取る**こと。

飛行中（協調搬送本番）はエポックのズレがそのまま相対位置誤差として現れるため、
ペアリング処理は必須です。本モジュールは iTOW をキーに両ローバーの最新値を
バッファリングし、一致エポックで **相対位置 = RELPOSNED_B − RELPOSNED_A** を算出します。

## 前提

- 全ローバーが**同一基地局から補正**を受ける構成（`refStationId` が一致することを
  実行時に確認・警告）。
- 各ローバーの F9P が RTK 補正（RTCM3）を受信できていること（`relPosValid` で判定）。
- UBX-NAV-RELPOSNED は `pyubx2` でパースする（既存の `archive/udp/base_ubx_logger.py` と同方式）。

## ファイル構成

```
gcs/relpos/
├── README.md            # このファイル
├── __init__.py          # パッケージ定義
├── pairing.py           # 中核ロジック（標準ライブラリのみ・ハードウェア非依存）
├── reader.py            # UBX-NAV-RELPOSNED のシリアル読み取り（pyubx2）
├── monitor.py           # 2 ローバーのライブ表示＋CSV 記録ドライバ（CLI）
├── test_pairing.py      # ペアリングロジックのユニットテスト
├── test_reader.py       # pyubx2 換算のユニットテスト
└── logs/                # monitor.py の CSV 出力先（.gitignore 済み）
```

## 要件への対応

| # | 要件 | 実装 |
|---|------|------|
| (1) | iTOW キーのバッファリング＆差分 | `RelposPairingBuffer` / `compute_relative()` |
| (2) | iTOW 週跨ぎロールオーバー（604800000 ms） | `itow_diff_ms()`（mod 折り畳み） |
| (3) | 許容エポック差ウィンドウと警告 | `match_window_ms` / `emit_warnings()` |
| (4) | accN/accE/accD の誤差伝播 | `propagate_accuracy()`（σ_Δ=√(σA²+σB²)） |
| (5) | relPosHeading のペアリングと機体間方位 | `bearing_ab_deg`（atan2(E,N)）+ heading 値 |
| (6) | 表示（距離・方位・精度・整合状態） | `format_paired()` |
| (7) | ペアリング後時系列の CSV 記録（iTOW 付き） | `monitor.py` / `PAIRED_CSV_FIELDS` |

## 使い方（コアライブラリ）

```python
from gcs.relpos.pairing import RelposPairingBuffer
from gcs.relpos.reader import from_pyubx2

# 各ローバーの pyubx2 解析結果を正規化（cm→m, 0.1mm→m 換算）
sample_a = from_pyubx2(parsed_a, rover_id="A")
sample_b = from_pyubx2(parsed_b, rover_id="B")

buf = RelposPairingBuffer(rover_ids=("A", "B"), match_window_ms=200)
buf.update(sample_a)
paired = buf.update(sample_b)   # 同一 iTOW なら相対位置を返す

print(paired.distance_3d_m)     # 相対距離 [m]
print(paired.bearing_ab_deg)    # 機体間方位 A→B [deg]
print(paired.acc_3d_m)          # 誤差伝播済み相対位置精度 [m]
print(paired.matched)           # エポック整合状態
```

## 使い方（ライブ表示＋CSV 記録）

2 台のローバー（F9P 直結シリアル）を PC / ラズパイに接続して実行します。

```bash
cd ~/rtk-pipeline
python3 gcs/relpos/monitor.py \
    --rover-a-port /dev/cu.usbmodem101 \
    --rover-b-port /dev/cu.usbmodem102 \
    --match-window-ms 200
```

| オプション | 既定値 | 説明 |
|---|---|---|
| `--rover-a-port` | 自動検出 | ローバー A の F9P シリアルポート |
| `--rover-b-port` | 自動検出 | ローバー B の F9P シリアルポート |
| `--baud` | `115200` | シリアルボーレート |
| `--poll-interval` | `0.1` | RELPOSNED ポーリング間隔 [秒] |
| `--match-window-ms` | `200` | **許容エポック差**（マッチング許容ウィンドウ）[ms] |
| `--csv` | `gcs/relpos/logs/relpos_<ts>.csv` | CSV 出力先 |
| `--display-interval` | `1.0` | 待機中ステータスの表示間隔 [秒] |
| `--duration` | `0`（無限） | 記録秒数（`Ctrl+C` で停止） |
| `--selftest` | — | ペアリングロジックの自己検証のみ実行 |

- 停止時（`Ctrl+C`）に、エポック整合・不整合の件数と保存先を表示します。
- エポックが揃わない場合（`delta_ms > match_window_ms`）や `refStationId` が
  不一致の場合、都度 `[WARN]` を表示します。

## 出力（表示・CSV）

### 表示 1 行の例

```
[12:00:00.123] iTOW=123456789 epoch=OK(+3ms) refStation=OK | dist2D=0.123m dist3D=0.130m | bearing(A→B)=45.0° | accH=0.005m accV=0.008m acc3D=0.009m | valid=OK heading=OK
```

| フィールド | 意味 |
|---|---|
| `epoch=OK(+3ms)` | エポック整合状態（`NG` のとき警告） |
| `refStation=OK` | 両ローバーの `refStationId` 一致（不一致は警告） |
| `dist2D / dist3D` | 相対距離（水平 / 3D）[m] |
| `bearing(A→B)` | 機体間方位（A から見た B の方位）[deg] |
| `accH / accV / acc3D` | 誤差伝播で推定した相対位置精度（水平/鉛直/3D）[m] |
| `valid` | 両ローバーの `relPosValid` |
| `heading` | 両ローバーの `relPosHeadingValid` |

### CSV スキーマ（`PAIRED_CSV_FIELDS`）

```
utc_time, itow_ms, itow_a, itow_b, delta_ms, matched,
ref_station_match, ref_station_a, ref_station_b,
rel_n_m, rel_e_m, rel_d_m, distance_2d_m, distance_3d_m, bearing_ab_deg,
heading_a_deg, heading_b_deg, heading_valid,
acc_n_m, acc_e_m, acc_d_m, acc_horizontal_m, acc_3d_m, valid
```

- `rel_n_m / rel_e_m / rel_d_m`: 相対位置 = B − A（N/E/D）[m]
- `delta_ms`: `itow_b - itow_a`（週跨ぎ対応の符号付き最短差）
- `acc_*_m`: 誤差伝播後の相対位置精度 [m]

## 設計方針・換算メモ

- `pairing.py` は**標準ライブラリのみ**に依存し、通信層（pyserial / pyubx2）から独立。
  GCS 側は正規化済み `RelposnedSample` を `update()` するだけでペアリングできる。
- pyubx2 の NAV-RELPOSNED は「生値の単位」で返るため、`reader.py` で SI へ換算する:
  - `relPosN/E/D/Length`: **cm → m**（÷100）
  - `relPosHeading`: **deg**（そのまま）
  - `accN/E/D/Length`: **0.1 mm → m**（÷1000）
  - `accHeading`: **deg**（そのまま）
- iTOW は 0..604799999 ms でラップするため、`itow_diff_ms()` は mod 演算で最短の
  符号付き差（−302400000..+302400000 ms）へ折り畳む。
- 誤差伝播は「独立な 2 測定値の差の分散 = 各分散の和」より σ_Δ = √(σA² + σB²)。

## 既存資産の再利用マップ（既存ファイルは無改変）

| 既存資産 | 再利用方法 | 用途 |
|---|---|---|
| `archive/udp/base_ubx_logger.py` | `from base_ubx_logger import auto_detect_port` | シリアルポート自動検出（`reader.py`） |
| `pyubx2`（依存ライブラリ） | `UBXMessage / UBXReader / POLL` | NAV-RELPOSNED のパース（`reader.py`） |
| `gcs/fix_type_logger.py` | 設計踏襲（`UbxPvtReader` と同型のポーリング） | リーダーの構造参考 |

## テスト

```bash
cd ~/rtk-pipeline
python3 -m unittest gcs.relpos.test_pairing gcs.relpos.test_reader -v
# または
python3 gcs/relpos/test_pairing.py
python3 gcs/relpos/test_reader.py
```

`test_pairing.py` は標準ライブラリのみで動作し、iTOW ロールオーバー・誤差伝播・
ペアリング整合を検証します。`test_reader.py` は `pyubx2` があれば cm/m・0.1mm/m の
単位換算を検証します（無い場合は自動スキップ）。

## 注意点

- **シリアル排他**: 各ローバーの F9P ポートは `base_recorder.py` / `fix_type_logger.py` /
  `udp_base_sender.py` 等と同時に開かないこと。
- **RTK 前提**: RELPOSNED が有効な値を持つには、F9P が基準局からの RTCM3 補正を
  受信できている必要がある（`relPosValid` で判定）。
- **refStationId**: 協調搬送では全ローバーが同一基地局を参照する前提。不一致時は
  警告を表示するが、ペアリング自体は継続する。
- **iTOW とエポックズレ**: ローバー間でサンプリング位相がズレると `delta_ms` が
  大きくなる。`--match-window-ms` を運用レートに合わせて調整する（例: 5Hz なら
  200ms が目安。エポック差が相対位置誤差に直結する点に注意）。
