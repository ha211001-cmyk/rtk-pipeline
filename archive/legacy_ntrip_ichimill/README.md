# legacy_ntrip_ichimill — 構成A（NTRIP/イチミル依存）スクリプトの退避先

ロードマップ（Phase 1 以降）が **自作基地局（構成B）ベース** に移行し、最終的な複数台協調搬送では
**NTRIP/イチミル（構成A）を使用しない方針**となったため、構成Aで使っていた
**NTRIP/イチミル依存スクリプト**を退避・保存するためのサブディレクトリです。

> 上位ディレクトリ `archive/` の README は [../README.md](../README.md) を参照してください。

## 背景・目的

- 従来、移動局（Rover）の RTK 測位は、外部 NTRIP キャスター（イチミル `ntrip.ales-corp.co.jp:2101`）
  から RTCM3 補正データを受信して F9P へ流し込む **構成A（NTRIP/イチミル）** で検証していた。
- その後のロードマップで、基地局を自作（F9P を TMODE3 Fixed Mode に設定して RTCM3 を生成する
  **構成B**）し、その補正データを自前で配信する方式へ方針転換した。
- これに伴い、外部 NTRIP キャスターに依存するスクリプトは今後のメンテナンス対象から外れたため、
  本ディレクトリへ退避する。
- 移動後もスクリプト内容や動作手順はそのまま保持しており、必要になれば参照・再利用できる。

## 封印理由（なぜ退避したか）

- 最終的な複数台協調搬送では **自作基地局（構成B）ベース** で構築する方針であり、
  NTRIP/イチミル（構成A）への依存を廃止するため。
- イチミルの接続情報（`ntrip.ales-corp.co.jp:2101`）や Basic 認証のユーザー名・パスワードが
  ソースコード内にハードコードされており、リポジトリ管理・配布上のリスクでもあった。
- 外部 NTRIP ポート（2101）がネットワーク環境によってブロックされることが多く、
  実運用に適さない場面が増えた。

> 構成Bの資産（`base_station_verify/rtcm_compare/` の `f9p_configurator_v2.py`・
> `rtk_RTCM_Log2.py`・`standalone_obs.py` や `rtk_base_mavlink/`、`windows/base_station.py`、
> `raspberrypi/base_station.py`、ローカル NTRIP キャスター `ntrip_caster.py` など）は
> **本ディレクトリへ移動していません**（移動対象外）。

## ディレクトリ構成

```
archive/legacy_ntrip_ichimill/
├── README.md                    # このファイル（各スクリプトの用途と封印理由）
│
├── windows/                     # 元 windows/ の NTRIP/イチミル依存スクリプト
│   ├── ichimile_log.py          # イチミル接続 RTK 測位（CSV ログ記録あり）
│   ├── ichimile_nolog.py        # イチミル接続 RTK 測位（ログ記録なし）
│   └── __pycache__/             # コンパイル済みキャッシュ（ichimile_log 分のみ）
│
├── raspberrypi/                 # 元 raspberrypi/ の NTRIP/イチミル依存スクリプト
│   ├── ichimile_log.py          # イチミル接続 RTK 測位（CSV ログ記録あり）
│   └── ichimile_nolog.py        # イチミル接続 RTK 測位（ログ記録なし）
│
├── ichimill_log/                # 元 ichimill_log/（macOS 版）を丸ごと退避
│   ├── README.md                # 元 ichimill_log/README.md（macOS 版の説明）
│   ├── ichimile_log.py          # イチミル接続 RTK 測位（macOS 版）
│   └── log/                     # ログ出力先（シンボリックリンク）
│
└── base_station_verify/         # 元 base_station_verify/ の NTRIP 接続確認スクリプト
    ├── check_ntrip.py           # NTRIP キャスター接続確認（単一マウントポイント）
    └── check_ntrip2.py          # NTRIP キャスター接続確認（複数マウントポイント）
```

## 各ファイルの役割

| ファイル | 元の場所 | 用途 |
|---------|---------|------|
| `windows/ichimile_log.py` | `windows/` | イチミル（`ntrip.ales-corp.co.jp:2101`）に接続し、受信した RTCM3 補正データを COM ポートの F9P へ流し込みつつ、F9P の NMEA GGA を解析して RTK Float/Fixed 状態を表示・CSV 記録するプログラム（Windows 版・ログあり）。GGA 出力を 5Hz に設定。 |
| `windows/ichimile_nolog.py` | `windows/` | 上記のログ記録なし版（表示のみ）。マウントポイントは `RTCM32MSM5`。 |
| `windows/__pycache__/ichimile_log.cpython-313.pyc` | `windows/__pycache__/` | `windows/ichimile_log.py` のコンパイル済みキャッシュ。 |
| `raspberrypi/ichimile_log.py` | `raspberrypi/` | イチミル NTRIP クライアント（Raspberry Pi 5 版・ログあり）。シリアルポートは `/dev/ttyACM0` 固定。 |
| `raspberrypi/ichimile_nolog.py` | `raspberrypi/` | 上記のログ記録なし版（表示のみ）。 |
| `ichimill_log/ichimile_log.py` | `ichimill_log/` | イチミル NTRIP クライアント（macOS 版）。`pyserial` + `pyubx2` のみで完結し、シリアルポートを自動検出。 |
| `ichimill_log/README.md` | `ichimill_log/` | 元 `ichimill_log/` ディレクトリの README（macOS 版の使い方・接続情報・動作フロー）。 |
| `base_station_verify/check_ntrip.py` | `base_station_verify/` | `ntrip.ales-corp.co.jp:2101` へ Basic 認証付きで接続し、ソーステーブル（`GET /`）を取得・表示する単発の接続確認スクリプト。 |
| `base_station_verify/check_ntrip2.py` | `base_station_verify/` | 複数のマウントポイント（`RTCM32MSM5` / `RTCM32MSM4` / `RTCM31` / `32MSM7NH`）へ順番に接続し、各マウントポイントの応答を確認するスクリプト。 |

## 前提・注意

- いずれも **外部 NTRIP キャスター（イチミル `ntrip.ales-corp.co.jp:2101`）への接続を前提**としています。
  外部 NTRIP ポート（2101）がネットワーク環境でブロックされている場合は接続できません。
- イチミルの Basic 認証のユーザー名・パスワードがソースコード内にハードコードされています。
  再利用・配布の際は取り扱いに注意してください。
- 現在の基地局・ローバー構成（構成B）は、`rtk_base_mavlink/`・`base_station_verify/rtcm_compare/`・
  `windows/`・`raspberrypi/`（基地局系・PPK 系）などを参照してください。

## 更新履歴

- 2026-09-27: ロードマップ（Phase 1 以降）が自作基地局（構成B）ベースへ移行したため、
  構成A（NTRIP/イチミル依存）スクリプトを `archive/legacy_ntrip_ichimill/` へ退避し、
  本 README を新規作成。
