# 本システムにおける RTK 実装の定義

本資料は、**このリポジトリ（`gcs/`）が RTK をどう表現し、どう判定しているか**を
実装に即して定義するものです。測位原理そのものは座学編
（[`rtk_gnss_theory.md`](rtk_gnss_theory.md) 〜 [`glossary.md`](glossary.md)）を参照してください。

> **出典ポリシー**: 本資料の記述は `gcs/` パッケージ内のファイルのみを出典とします。

- 索引: [`../README.md`](../README.md)
- 条件・閾値の実値: [`fix_conditions.md`](fix_conditions.md)

---

## 1. 役割と位置づけ

| 資料 | 扱う内容 |
|---|---|
| 座学編（①〜④） | RTK-GNSS の一般原理（外部文献） |
| **本資料** | **`gcs/` における「RTK 状態」のデータ表現・判定・モジュール構成** |
| 機器別編（devices/） | 各機器の具体的な設定値と操作手順 |

用語の定義（`fix_type` とは何か、`carrSoln` とは何か）は本資料が正典です。

---

## 2. `fix_type` の正規化定義

### 2.1 正典マッピング

本システムは **MAVLink `GPS_FIX_TYPE`（0〜6）** を共通語彙として使用します
（出典: [`../../../fix_metrics.py`](../../../fix_metrics.py)）。

| `fix_type` | 名称 | 意味 |
|---|---|---|
| 0 | `NO_FIX` | 測位なし |
| 1 | `NO_FIX` | 測位なし（0 と同一視） |
| 2 | `2D_FIX` | 水平のみ |
| 3 | `3D_FIX` | 3 次元（単独測位） |
| 4 | `DGPS` | コード補正 |
| 5 | `RTK_FLOAT` | RTK 浮動解（整数アンビギュイティ未確定） |
| 6 | `RTK_FIXED` | RTK 固定解（確定＝サブセンチ級） |

実装定数:

```python
FIX_NAMES = {0: "NO_FIX", 1: "NO_FIX", 2: "2D_FIX", 3: "3D_FIX",
             4: "DGPS", 5: "RTK_FLOAT", 6: "RTK_FIXED"}
FIXED = 6
FLOAT = 5
```

出典: [`../../../fix_metrics.py`](../../../fix_metrics.py) の `FIX_NAMES` / `FIXED` / `FLOAT`。

### 2.2 UBX → fix_type 変換

UBX-NAV-PVT の値（`fixType` / `carrSoln` / `diffSoln`）を正規化 `fix_type` へ変換します。
**RTK の真偽は `carrSoln` が最も直接的**という方針で、`carrSoln` を優先します。

| 入力 | 出力 |
|---|---|
| `carrSoln == 2` | `6`（`RTK_FIXED`） |
| `carrSoln == 1` | `5`（`RTK_FLOAT`） |
| `carrSoln == 0` かつ `fixType >= 3` | `3`（`3D_FIX`） |
| `carrSoln == 0` かつ `fixType == 2` | `2`（`2D_FIX`） |
| その他 | `0`（`NO_FIX`） |

出典: [`../../../fix_metrics.py`](../../../fix_metrics.py) の `ubx_to_fix_type()`。

なお UBX-NAV-PVT の `fixType` は
`0=no fix / 1=dead reckoning / 2=2D / 3=3D / 4=GNSS+DR / 5=time only`、
`flags.carrSoln` は `0=no carrier phase / 1=float / 2=fixed`、
`flags.diffSoln` は `0=no differential / 1=differential applied` です
（出典: 同上の docstring）。

> ⚠️ **実装間の差異**: [`../../../rtk_tools/mavlink_bridge.py`](../../../rtk_tools/mavlink_bridge.py) は
> `0: "NO_GPS"` という**独自の `FIX_NAMES`** を持ちます（正典は `0: "NO_FIX"`）。
> ログ表示上用語が異なる場合がありますが、**数値 `fix_type` は両者で同一**です。

### 2.3 遷移の計測

`fix_type` 時系列から、値が変化した点を**遷移**として抽出します
（出典: [`../../../fix_metrics.py`](../../../fix_metrics.py) の `iter_transitions()`）。

| 指標 | 定義 |
|---|---|
| `transitions` | 遷移の一覧（`from` / `to` / `t` / `ts`） |
| `transition_count` | 総遷移回数 |
| `float_transition_count` | `to == 5`（FLOAT へ入った）回数 |
| `fixed_to_float_count` | FIXED→FLOAT の脱落回数（`from==6 and to==5`） |

---

## 3. `carrSoln`（搬送波位相解）の解釈

`UBX-NAV-RELPOSNED` の `flags` は次のビット構成です
（出典: [`../../../rtk_tools/f9p_relposned_monitor.py`](../../../rtk_tools/f9p_relposned_monitor.py)）。

| ビット | 内容 |
|---|---|
| 0-7 | `gnssFixOk` |
| 8 | `diffSoln` |
| 9 | `relPosValid` |
| 10-11 | `refPosMiss` |
| 12 | `refObsMiss` |
| **16-18** | **`carrSoln`（0=NONE / 1=FLOAT / 2=FIXED）** |

- 抽出: `(flags >> 16) & 0x07`
- 名称対応: `{0: "NONE", 1: "FLOAT", 2: "FIXED"}`

> ⚠️ **メッセージ ID の注意**: 実装は NAV-RELPOSNED の MID を `0x3C` としています。
> コメントに「F9P HPG 1.32 firmware: RELPOSNED moved from 0x10 to 0x3C」とあり、
> ファームウェアによって ID が異なる点が明記されています（出典: 同上）。
> ファームウェア更新時は要確認です。

---

## 4. 品質指標の定義（`compute_metrics()`）

`fix_metrics.compute_metrics()` が返す指標の定義です
（出典: [`../../../fix_metrics.py`](../../../fix_metrics.py)）。

| キー | 意味 | 算出方法 |
|---|---|---|
| `total_samples` | サンプル数 | 行数 |
| `duration_sec` | 記録時間 [秒] | `max(t) − min(t)` |
| `counts_by_fix` | `fix_type` 別サンプル数 | 集計 |
| `duration_by_fix` | `fix_type` 別継続時間 [秒] | 遷移区間の時間積分 |
| `fixed_samples` | `RTK_FIXED` のサンプル数 | `counts_by_fix[6]` |
| **`fixed_rate_pct`** | FIXED 維持率（**全期間**）[%] | `fixed_duration / duration_sec × 100` |
| **`fixed_rate_after_first_pct`** | FIXED 維持率（**初回 FIXED 以降**）[%] | 初回 FIXED 以降の時間で同様に算出 |
| **`ttff_sec`** | TTFF [秒] | 初回 `RTK_FIXED` の時刻 − 記録開始 |
| `first_fixed_t` / `first_fixed_ts` | 初回 FIXED の時刻 / 壁時計 | 先頭から探索 |
| `reached_fixed` | FIXED 到達の有無 | `first_fixed_t is not None` |
| `transitions` / `transition_count` | 遷移一覧 / 回数 | §2.3 |
| `float_transition_count` | FLOAT 遷移回数 | §2.3 |
| `fixed_to_float_count` | FIXED→FLOAT 脱落回数 | §2.3 |

> **注目点**: `fixed_rate_pct` は「サンプル数の割合」ではなく **時間の割合**です。
> サンプリング間隔が不均一でも意味が変わらないよう、遷移区間の継続時間を積分しています。

判定基準（PASS/FAIL）は [`fix_conditions.md`](fix_conditions.md) §3 を参照。
自己検証は `python3 -m gcs.fix_metrics`（合成時系列で期待値を検証）で実行できます
（出典: [`../../../fix_metrics.py`](../../../fix_metrics.py) の `self_test()`）。

---

## 5. 補正リンクの監視定義

| 監視項目 | 実装 | 出力元 |
|---|---|---|
| RTCM 到達・RTK age・CRC・msgUsed | `gcs/rtcm_monitor.py` の `CorrectionMonitor` | ローバー F9P の UBX ストリーム |
| 基地局 RTCM ストリームのメッセージ種別 | `gcs/rtcm_monitor.py` の `Rtcm3StreamParser` | 基地局 TCP:2101 |
| 基地局 RTCM 到達レート | `CorrectionMonitor` の `rxm_rtcm` 集計 | ローバー F9P |

出典: [`../../../preflight/README.md`](../../../preflight/README.md) §1 および §7。
監視の実行は `python3 gcs/preflight/runner.py --host <機体IP> --port 5001` です（同 §4-1）。

---

## 6. モジュールマップ（関心 → 正典）

| 関心 | 正典 | 備考 |
|---|---|---|
| RTK Fix 判定 | [`../../../fix_metrics.py`](../../../fix_metrics.py) | `fix_name` / `ubx_to_fix_type` / `compute_metrics` |
| RTCM 監視・抽出 | [`../../../rtcm_monitor.py`](../../../rtcm_monitor.py) | `Rtcm3StreamParser` / `Rtcm3Crc24q` |
| F9P 設定（write-verify） | [`../../../rtk_tools/f9p_config_all.py`](../../../rtk_tools/f9p_config_all.py) | 39 キー定義・`F9pAllConfigurator` |
| 設定解決 | [`../../../rtk_tools/config_loader.py`](../../../rtk_tools/config_loader.py) | 優先順位は [`../../../config/README.md`](../../../config/README.md) |
| 基地局サービス | [`../../../rtk_tools/rtk_base_station_v2.py`](../../../rtk_tools/rtk_base_station_v2.py) | F9P 設定＋TCP:2101＋任意 UDP |
| 機体側中継・注入 | [`../../../rtk_tools/mavlink_bridge.py`](../../../rtk_tools/mavlink_bridge.py) | MAVLink 中継＋`GPS_RTCM_DATA` |
| RELPOSNED 監視 | [`../../../rtk_tools/f9p_relposned_monitor.py`](../../../rtk_tools/f9p_relposned_monitor.py) | `carrSoln` |
| Web 運用 UI | [`../../../app/operations/`](../../OPERATIONS.md) | REST `/api/ops/*` + `/ws/ops` |

出典: [`../../../rtk_tools/README.md`](../../../rtk_tools/README.md)（正典の所在）、
[`../../OPERATIONS.md`](../../OPERATIONS.md)（操作カタログ）。

---

## 7. F9P 設定の 3 層構造（実装上の定義）

| 層 | 実装 | 内容 |
|---|---|---|
| **キー定義** | `_build_key_table(lat, lon, alt)` | 39 キー（基地局 20 / 移動局 19）と期待値 |
| **キー ID** | `_KEY_*` 定数 | `CFG-VALGET` 応答の解析に使用 |
| **保存先 layer** | `LAYER_RAM=1` / `LAYER_BBR=2` / `LAYER_FLASH=4` / `LAYER_ALL=7` | 既定は `LAYER_ALL`（永続化） |

出典: [`../../../rtk_tools/f9p_config_all.py`](../../../rtk_tools/f9p_config_all.py)、
[`../../../rtk_tools/README.md`](../../../rtk_tools/README.md)。

- 基地局キー: `CFG_TMODE_*`（固定座標）＋ `CFG_MSGOUT_RTCM_3X_TYPE*_UART1`（7 件：1005/1006/1074/1084/1094/1124/1230）
- 基地局キー（USB）: 同上 7 件の `..._USB` 版
- 移動局キー: `CFG_UART2*`（RTCM3 入力）・`CFG_NAVHPG_DGNSSMODE`・`CFG_RATE_*`・GNSS 信号・`CFG_MSGOUT_UBX_NAV_RELPOSNED_UART2` 等

---

## 8. 出典（`gcs/` 内のみ）

| ファイル | 参照箇所 |
|---|---|
| `gcs/fix_metrics.py` | `FIX_NAMES` / `FIXED` / `FLOAT` / `ubx_to_fix_type()` / `iter_transitions()` / `compute_metrics()` / `format_metrics()` / `self_test()` |
| `gcs/rtk_tools/f9p_relposned_monitor.py` | `flags` ビット定義 / `carrSoln` 抽出 / MID `0x3C` |
| `gcs/rtk_tools/mavlink_bridge.py` | 独自 `FIX_NAMES` / `extract_rtcm_frames()` / `gps_rtcm_data_encode()` |
| `gcs/rtk_tools/f9p_config_all.py` | `_build_key_table()` / `_KEY_*` / `_RTCM_MSG_KEYS_*` / `_UART2_ROVER_CFG_KEYS` |
| `gcs/rtk_tools/README.md` | 正典の所在、layer の定義 |
| `gcs/rtcm_monitor.py` | `CorrectionMonitor` / `Rtcm3StreamParser` |
| `gcs/preflight/README.md` | Item 1/2/3 の構成と再利用マップ |
| `gcs/docs/OPERATIONS.md` | 運用操作カタログ・正典の一覧 |
| `gcs/config/README.md` | 設定の優先順位 |

> 次に読む: [`fix_conditions.md`](fix_conditions.md)（FIXED の条件と実値）
