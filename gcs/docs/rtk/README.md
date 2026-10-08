# RTK-GNSS 資料索引（`gcs/docs/rtk/`）

本ディレクトリは、本リポジトリ（`gcs/`）で **RTK-GNSS 測位を運用・保守するための資料**を、
「共通の座学・定義」と「機器別の手順」に分けて収録したものです。

| 目的 | 参照先 |
|---|---|---|
| **運用で実行するスクリプトだけを知りたい** | [`../../ops/README.md`](../../ops/README.md) |
| 起動手順（通し） | [`../../../STARTUP_GUIDE.md`](../../../STARTUP_GUIDE.md) |
| RTK 手順書（運用の全体） | [`../RTK_PROCEDURES_MANUAL.md`](../RTK_PROCEDURES_MANUAL.md) |
| 操作カタログ | [`../OPERATIONS.md`](../OPERATIONS.md) |
| gcs パッケージ全体の入口 | [`../../README.md`](../../README.md) |
| リポジトリ全体 | [`../../../README.md`](../../../README.md) |

---

## 1. 情報源ポリシー（重要）

本ディレクトリの文書は、**記述の根拠を厳格に分離**しています。

| 区分 | 対象 | 出典の扱い |
|---|---|---|
| **座学編** | `common/rtk_gnss_theory.md` 〜 `common/glossary.md`（座学①〜④） | 一般文献（教科書・u-blox 資料等）を出典とする。リポジトリ固有の実装に触れる場合は `gcs/` 内の出典を併記 |
| **機器別編** | `devices/.../README.md` | **`gcs/` パッケージ内のみ**を出典とする。`パス:行` を根拠として併記 |
| **実値まとめ** | `common/fix_conditions.md` / `common/rtk_details.md` | `gcs/` 内の実装値・設定値のみ。未確定値は「仮置き」と明記 |

> 一般文献の数値を、そのまま本システムの設定値として扱わないでください。
> 本システムの実値は必ず [`common/fix_conditions.md`](common/fix_conditions.md) を参照します。

---

## 2. 用語の前提

本ディレクトリ全体で、次の語を下記の意味に固定して使います。

| 語 | 意味 | 定義元 |
|---|---|---|
| `fixed_lat` / `fixed_lon` / `fixed_alt` | 基地局アンテナの固定座標。**`fixed_alt` は楕円体高（HAE）であり MSL ではない** | [`../../config/base_station.json`](../../config/base_station.json) |
| `fix_type` | MAVLink `GPS_RAW_INT.fix_type` を `0..6` に正規化した値。**`6` = RTK_FIXED** | [`common/rtk_details.md`](common/rtk_details.md) §2 |
| `carrSoln` | u-blox の搬送波位相解ステータス（`0`=none / `1`=float / `2`=fixed） | [`common/rtk_details.md`](common/rtk_details.md) §3 |
| `MSM4` / `MSM7` | RTCM3 の観測データメッセージ形式 | [`devices/f9p_base/README.md`](devices/f9p_base/README.md) §2.4 |
| APC | Antenna Phase Center（アンテナ位相中心）。固定座標は APC 基準 | [`common/coordinate_systems.md`](common/coordinate_systems.md) §3.1 |
| golden | 退行監視の基準値（F9P レジスタ / ArduPilot パラメータ） | [`devices/f9p_rover/README.md`](devices/f9p_rover/README.md) §3 |

---

## 3. 構成

```
gcs/docs/rtk/
├── README.md                       # 本ファイル（索引）
├── common/                         # 機器に依存しない共通資料
│   ├── rtk_gnss_theory.md          # 座学① GNSS 測位の基礎と RTK の原理
│   ├── coordinate_systems.md       # 座学② 座標系・高さ・アンテナ基準点
│   ├── error_and_accuracy.md       # 座学③ 誤差要因・補正データ・精度指標
│   ├── glossary.md                 # 座学④ 用語集
│   ├── rtk_details.md              # 本システムにおける RTK 実装の定義
│   └── fix_conditions.md           # RTK-FIXED 確立・維持の条件（実値まとめ）
└── devices/                        # 機器別の設定・手順
    ├── f9p_base/README.md          # 基地局 F9P（ZED-F9P / Base）
    ├── f9p_rover/README.md         # 移動局 F9P（ZED-F9P / Rover）
    ├── pixhawk_ardupilot/README.md # Pixhawk 6C + ArduPilot（RTK 取り込み・EKF）
    ├── raspberrypi/README.md       # Raspberry Pi 5（中継・RTCM 注入）
    └── mac_gcs/README.md           # Mac（基地局配信・Web GCS・解析）
```

---

## 4. 読者別の読み方

| 目的 | 読む順 |
|---|---|
| はじめて全体像を知りたい | [座学①](common/rtk_gnss_theory.md) → [座学②](common/coordinate_systems.md) → [座学③](common/error_and_accuracy.md) → [座学④](common/glossary.md) → [rtk_details](common/rtk_details.md) |
| 基地局を立てたい | [f9p_base](devices/f9p_base/README.md) → [mac_gcs](devices/mac_gcs/README.md) §4 → [fix_conditions](common/fix_conditions.md) §1 |
| 機体側を組みたい | [raspberrypi](devices/raspberrypi/README.md) → [f9p_rover](devices/f9p_rover/README.md) → [pixhawk_ardupilot](devices/pixhawk_ardupilot/README.md) |
| `RTK_FIXED` にならない | [fix_conditions](common/fix_conditions.md) §1 / §2 / §5 → [rtk_details](common/rtk_details.md) §2 |
| 過去の運用を再現したい | [RTK_PROCEDURES_MANUAL](../RTK_PROCEDURES_MANUAL.md) → [OPERATIONS](../OPERATIONS.md) |
| どのファイルを実行すればよいか知りたい | [`../../ops/README.md`](../../ops/README.md) |

---

## 5. システム全体像

| 役割 | ホスト | 実体 | 備考 |
|---|---|---|---|
| 基地局 RTCM 配信 | Mac | [`../../rtk_tools/rtk_base_station_v2.py`](../../rtk_tools/rtk_base_station_v2.py) | TCP `2101` でマルチクライアント配信 |
| Web GCS | Mac | [`../../server.py`](../../server.py) → `gcs.app.server:app` | HTTP `9000` / MAVLink UDP `14550` 受信 |
| MAVLink 中継・RTCM 注入 | Raspberry Pi 5 | [`../../rtk_tools/mavlink_bridge.py`](../../rtk_tools/mavlink_bridge.py) | `/dev/ttyAMA0` @ 921600 |
| フライトコントローラ | Pixhawk 6C | ArduPilot | RTK を EKF ソースに取り込み |

### fix_type の昇格

| 値 | 名称 | 意味 |
|---|---|---|
| `1` / `3` | `3D_FIX` | 単独測位。補正なし |
| `4` | `DGPS` | コードベースの補正 |
| `5` | `RTK_FLOAT` | 搬送波位相・浮動解（収束中） |
| `6` | **`RTK_FIXED`** | 搬送波位相・固定解（センチメートル級） |

昇格シーケンスの実測手順は [`common/fix_conditions.md`](common/fix_conditions.md) §2 を参照してください。

---

## 6. 既知の矛盾と要確認事項

`gcs/` 内に**相反する記述が併存している**項目です。運用前に必ず確認してください。
詳細と根拠は [`common/fix_conditions.md`](common/fix_conditions.md) §6 にあります。

| ID | 論点 | 状態 |
|---|---|---|
| 6-1 | `CFG_NAVHPG_DGNSSMODE` を `0` にするか `3` にするか | 要確認 |
| 6-2 | 基地局設定が 2 経路（UART1 / USB）あり、RTCM 形式と `POS_TYPE` が食い違う | 要確認 |
| 6-3 | 基地局座標キーが `fixed_lat/lon/alt` か `fixed_pos` か | 要確認 |
| 6-4 | ArduPilot パラメータが `GPS_TYPE` か `GPS1_TYPE` か | 要確認 |

---

## 7. ロギングに関する既知の注意

[`../../rtk_tools/mavlink_bridge.py`](../../rtk_tools/mavlink_bridge.py) は、CSV / `.rtcm3` の書き出し処理が**現在コメントアウトされており**、起動バナーは `Logging Disabled` を表示します。

| 参照元 | 記載 | 実際 |
|---|---|---|
| [`../../../STARTUP_GUIDE.md`](../../../STARTUP_GUIDE.md) §4 ②③ | `~/logs/rtk_status_*.csv` を `tail -f` | **生成されない** |

ログが必要な場合は、`--log-dir` の指定に加えて当該箇所の有効化が必要です。

---

## 8. ドキュメント索引

### 8.1 座学・共通定義（`common/`）

| 文書 | 内容 |
|---|---|
| [`rtk_gnss_theory.md`](common/rtk_gnss_theory.md) | 測距の原理、コード測位と搬送波位相測位、RTK と PPK の違い、NTRIP と補正データ配送経路 |
| [`coordinate_systems.md`](common/coordinate_systems.md) | WGS84 / ECEF、高さの種類（楕円体高・MSL・ジオイド）、APC とアンテナ高、NED / ENU、基線ベクトル |
| [`error_and_accuracy.md`](common/error_and_accuracy.md) | 誤差要因の分類、基線長と精度、DOP、1σ による定量化、RTCM3 メッセージ体系 |
| [`glossary.md`](common/glossary.md) | 用語集（衛星系 / 測位 / 補正 / 座標 / 誤差 / 受信機 / 機体側 / 本リポジトリ固有 / 略語） |
| [`rtk_details.md`](common/rtk_details.md) | `fix_type` 正規化、`carrSoln` の解釈、品質指標 `compute_metrics()`、モジュールマップ、F9P 設定の 3 層構造 |
| [`fix_conditions.md`](common/fix_conditions.md) | 到達条件チェックリスト、昇格シーケンス、PASS / FAIL 判定基準（実値）、リンク健全性、維持と FS、既知の矛盾 |

### 8.2 機器別（`devices/`）

| 文書 | 内容 |
|---|---|
| [`f9p_base/README.md`](devices/f9p_base/README.md) | 基地局 F9P の 20 キー、TMODE3 固定座標、RTCM3 出力（UART1 / USB）、固定座標の決め方、write-verify の原則 |
| [`f9p_rover/README.md`](devices/f9p_rover/README.md) | 移動局 F9P の 19 キー、golden 4 キー、RELPOSNED による状態監視、適用方法 |
| [`pixhawk_ardupilot/README.md`](devices/pixhawk_ardupilot/README.md) | 二層 golden、`ekf_sources` 11 パラメータ、`failsafe` 7 パラメータ、RTK 喪失時の EKF / FS 挙動 |
| [`raspberrypi/README.md`](devices/raspberrypi/README.md) | 3 スレッド構成、RTCM3 フレーム抽出、`GPS_RTCM_DATA` 分割、安全チェック、終了時集計、ロギングの現状 |
| [`mac_gcs/README.md`](devices/mac_gcs/README.md) | ネットワーク構成、仮想環境、標準運用フロー 4 ステップ、Web UI、REST API / WebSocket、設定の優先順位、事後解析 |

### 8.3 関連する `gcs/` 文書・コード

| 参照先 | 内容 |
|---|---|
| [`../../README.md`](../../README.md) | パッケージ概要、ディレクトリ構成、クイックスタート |
| [`../../ops/README.md`](../../ops/README.md) | **運用時に実行するスクリプトの一覧（入口）** |
| [`../../rtk_tools/README.md`](../../rtk_tools/README.md) | ツール一覧、`layer` の定義 |
| [`../../config/README.md`](../../config/README.md) | 設定ファイル一覧 / 優先順位 / スキーマ |
| [`../../preflight/README.md`](../../preflight/README.md) | 飛行前セルフテスト（Item 1 / 2 / 3） |
| [`../../ekf_failsafe/README.md`](../../ekf_failsafe/README.md) | EKF / フェイルセーフ golden 照合 |
| [`../../flight_test/README.md`](../../flight_test/README.md) | 実飛行試験の評価モデル |
| [`../../accuracy/README.md`](../../accuracy/README.md) | 相対測位精度の実測と PPK クロスチェック |
| [`../../hw_verify/README.md`](../../hw_verify/README.md) | 物理ハードウェア検証 |
| [`../../backend/README.md`](../../backend/README.md) | 監視対象（Golden 値） |
| [`../../relpos/README.md`](../../relpos/README.md) | RELPOSNED の読み取り |
| [`../../deploy/README.md`](../../deploy/README.md) | systemd 常駐デプロイ |
| [`../PHASE0_INTEGRATION_PLAN.md`](../PHASE0_INTEGRATION_PLAN.md) | Phase 0 統合計画 |
| [`../RELEASE_CHECKLIST.md`](../RELEASE_CHECKLIST.md) | リリース手順 |

---

## 9. 動作確認

本ディレクトリの記述は、ハードウェアなしで検証できます。

```bash
cd ~/rtk-pipeline-local
python3 -m gcs.selftest          # システム全体の自己検証（合成データ）
python3 -m unittest discover -t . -s gcs -p 'test_*.py'         # 判定ロジックの単体テスト
```

`gcs.selftest` は合成データで判定経路を検証するもので、実機の RTK 到達を保証するものではありません。実値の確認は [`common/fix_conditions.md`](common/fix_conditions.md) を参照してください。
