# gcs/backend — F9P コンフィグ退行監視・自動修正バックエンド

ロードマップ **Phase 1（スクリプト①）** の成果物です。

RTK-FIXED 到達の必須条件である U-blox ZED-F9P のレジスタ設定（Golden 値）が、
フライトコントローラの自動設定などによって意図せず退行していないかを、GCS から
**「飛行前チェック」としてワンクリックで現状確認・自動修正（Flash 保存）** します。

- 依存: `af1d0`（Phase 0: F9P レジスタの真因特定・コンフィグ一元化）
- 子タスク: `664ae`（④: 1 台実機での FIXED 確立・統合テスト）

---

## 1. アーキテクチャ（ハイブリッド方式）

| フェーズ | 配置 | 接続先 | 備考 |
|---|---|---|---|
| **Phase 1（現在）** | GCS 集中型（地上の GCS 用 PC） | `host=<機体 IP>`（Wi-Fi） | TCP 通信（DroneCAN Serial Forwarding） |
| **Phase 3（将来）** | エッジ分散型（機体の Raspberry Pi 5 内） | `host=127.0.0.1` | 自己完結 |

トランスポート層を抽象化しているため、**`host` を差し替えるだけ**で
Phase 1 → Phase 3 へシームレスに移行できます。さらに直接シリアル接続
（`serial_port=`）にも対応しています。

```
[GCS / Raspberry Pi] --TCP(DroneCAN Serial Forwarding)--> [F9P シリアル]
        │                                                      │
   F9pConfigGuard                                    UBX-CFG-VALGET/VALSET
```

---

## 2. 監視対象（Golden 値）

| キー（u-blox 表記） | pyubx2 内部名 | Golden 値 | 意味 |
|---|---|---|---|
| `CFG-NAVHPG-DGNSSMODE` | `CFG_NAVHPG_DGNSSMODE` | `3` | RTK Fixed |
| `CFG-NAVSPG-DYNMODEL` | `CFG_NAVSPG_DYNMODEL` | `7` | Airborne <2g |
| `CFG-RATE-MEAS` | `CFG_RATE_MEAS` | `200` | 5 Hz（測位間隔 200 ms） |
| `CFG-UART1INPROT-RTCM3X` | `CFG_UART1INPROT_RTCM3X` | `1` | UART1 RTCM3 入力許可 |

値はモジュール先頭の `GOLDEN_VALUES` に **辞書形式で一括定義** されています。
（NTRIP / イチミルの構成 A は使用しません。）

---

## 3. ディレクトリ構成

```
gcs/backend/
├── README.md                 # このファイル
├── f9p_configurator.py       # バックエンドクラス（本成果物）
└── test_f9p_configurator.py  # ユニットテスト（モック検証）
```

---

## 4. 依存関係

```bash
pip install pyserial pyubx2
```

- `pyserial` … 直接シリアル接続時のみ使用（TCP 利用時は不要）
- `pyubx2` … UBX フレーム生成 / 解析 / コンフィグキー解決

既存資産 `archive/base_station_verify/rtcm_compare/f9p_configurator_v2.py` を
**import（`LAYER_ALL` の再利用）のみで参照** しており、既存ファイルの改変は行いません。

---

## 5. 使い方

### 5-1. GCS GUI（GCS-UmemotoLab）からの呼び出し

```python
from gcs.backend.f9p_configurator import F9pConfigGuard

# Phase 1: 機体（Raspberry Pi 5）の IP を指定
guard = F9pConfigGuard(host="192.168.1.100", port=5001)
result = guard.run_check_and_fix()

print(result["status"])   # "PASS" / "FIXED" / "FAIL"
print(result["summary"])  # UI 表示用の 1 行サマリー
```

### 5-2. コマンドライン（ワンクリック）

```bash
# Phase 1（機体 IP）
python3 gcs/backend/f9p_configurator.py --host 192.168.1.100 --port 5001

# Phase 3（機体内で自己完結）
python3 gcs/backend/f9p_configurator.py --host 127.0.0.1 --port 5001

# 現状確認のみ（自動修正しない）
python3 gcs/backend/f9p_configurator.py --host 192.168.1.100 --no-fix

# 直接シリアル（USB 接続の F9P）
python3 gcs/backend/f9p_configurator.py --serial /dev/ttyACM2 --baud 115200
```

---

## 6. 戻り値（`run_check_and_fix()`）

`dict` 型で返します。GCS GUI は戻り値をそのまま表示に使えます。

| キー | 型 | 内容 |
|---|---|---|
| `status` | str | `PASS`（正常）/ `FIXED`（退行を自動修正）/ `FAIL`（失敗） |
| `summary` | str | UI 表示用 1 行サマリー |
| `messages` | list[str] | キーごとの OK/NG 表示メッセージ |
| `checked` | dict | キーごとの `{key, key_display, label, expected, actual, ok}` |
| `fixed` | list[str] | 自動修正に成功したキー |
| `fix_failed` | list[str] | 修正失敗 / 修正後も NG のキー |
| `layer` | int | 保存レイヤー（`7` = RAM + BBR + Flash） |
| `transport` | dict | 接続先（`mode` / `host` / `port` 等） |
| `timestamp` | str | 実行時刻（UTC ISO8601） |

`status` の意味:

- **PASS** … 全 Golden 値が一致（修正不要）
- **FIXED** … 退行を検知し、UBX-CFG-VALSET（layer=7）で自動修正 → 再検証 OK
- **FAIL** … 接続失敗 / 読取失敗 / 修正失敗 / 修正後も退行が残る

---

## 7. 確実な Flash 永続化

退行を検知した際の自動修正（`UBX-CFG-VALSET`）では、必ず **`layer=7`
（RAM + BBR + Flash）** を指定します。これにより **F9P の再起動後も設定が維持** されます。

```python
self._send(UBXMessage.config_set(LAYER_ALL, 0, cfg).serialize())  # LAYER_ALL = 7
```

修正後は F9P のコンフィグサブシステム再起動を待ってから再ポーリングし、
実測値が Golden 値に一致したことを確認してから `FIXED` を返します。

---

## 8. DroneCAN Serial Forwarding について

機体（Raspberry Pi 5）側で、F9P のシリアル（DroneCAN 経由）を TCP に橋渡しする
サービスが起動している前提です。GCS 側はその TCP に素のバイト列で UBX を送受信します。

- `--host` … 機体の IP（Phase 1）または `127.0.0.1`（Phase 3）
- `--port` … Forwarding サービスのポート（既定 `5001`。環境に合わせて変更）

> 既定ポートは本モジュールの仮置き値です。実際の Forwarding サービスのポートに
> 合わせて `--port` / `port=` を指定してください。

---

## 9. テスト

実機不要のモック検証（PASS / FIXED / FAIL、layer=7 永続化、接続・読取失敗）を
`test_f9p_configurator.py` に実装しています。

```bash
cd <リポジトリルート>
python3 -m pytest gcs/backend/test_f9p_configurator.py -v
```

---

## 10. 既存資産の再利用方針

- `archive/base_station_verify/rtcm_compare/f9p_configurator_v2.py` から `LAYER_ALL`
  および `F9pConfiguratorV2` を import して再利用。
- 既存ファイルは **無断改変しません**（NTRIP / イチミルの構成 A も不使用）。
- 本モジュールは `gcs/backend/` に新規格納し、トランスポート抽象化
  （TCP / シリアル）と Golden 値一括監視を追加したリファクタ版です。
