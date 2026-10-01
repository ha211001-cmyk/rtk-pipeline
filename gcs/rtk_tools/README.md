# gcs/rtk_tools — F9P 設定・RTCM 注入・Fix 監視（GCS-UmemotoLab rtk_tools/ 統合版）

GCS-UmemotoLab の `rtk_tools/` を `gcs/rtk_tools/` へ移行し、rtk-pipeline の `gcs/` 側の
正典モジュールと一本化したツール群です（Phase 0 統合計画 `gcs/PHASE0_INTEGRATION_PLAN.md` §4 / §7 Phase 4）。

## 正典（canonical）の所在

| 関心 | 正典 | 移行対象外 / 委譲 |
|---|---|---|
| **RTK Fix 判定** | `gcs/fix_metrics.py`（`fix_name` / `ubx_to_fix_type` / `compute_metrics`） | `gcs_fix_monitor.py`・`f9p_fix_monitor.py` は移行しない |
| **F9P 設定（write-verify）** | `f9p_config_all.py`（`F9pAllConfigurator`） | `f9p_configurator.py` / `f9p_rover_config.py` / `f9p_verify_config.py` は薄い互換ラッパー |
| **RTCM 監視・抽出** | `gcs/rtcm_monitor.py`（`Rtcm3StreamParser` / `rtcm3_crc24q`） | `verify_rtcm_tcp.py` はこれを再利用 |
| **設定解決** | `config_loader.py` | — |

## ツール一覧

| ファイル | 用途 | 起動例 |
|---|---|---|
| `f9p_config_all.py` | ★基地局12+USB7 / 移動局19 キーの write-verify（CFG-VALSET → CFG-VALGET） | `python3 -m gcs.rtk_tools.f9p_config_all --role base --port /dev/tty.usbmodemXXX` |
| `f9p_config_monitor.py` | 設定ベースライン差分監視（継続 / `--once`） | `python3 -m gcs.rtk_tools.f9p_config_monitor --role base --port /dev/tty.usbmodemXXX` |
| `verify_rtcm_tcp.py` | 基地局 TCP ストリームの RTCM3 メッセージタイプ検証 | `python3 -m gcs.rtk_tools.verify_rtcm_tcp --host localhost --port 2101` |
| `rtk_base_station_v2.py` | 基地局統合サービス（F9P 設定 + TCP:2101 配信 + UDP ブロードキャスト） | `python3 -m gcs.rtk_tools.rtk_base_station_v2` |
| `rtk_forwarder_service.py` | RTCM 転送（tcp/ntrip/serial → serial/udp、設定ファイル駆動） | `python3 -m gcs.rtk_tools.rtk_forwarder_service --config rtk_forwarder.yml` |
| `tcp2serial.py` | TCP→シリアル橋渡し（RTCM 注入、設定ファイル対応） | `python3 -m gcs.rtk_tools.tcp2serial --config tcp2serial.yml` |
| `f9p_relposned_monitor.py` | UBX-NAV-RELPOSNED carrSoln 監視 | `python3 -m gcs.rtk_tools.f9p_relposned_monitor --port /dev/ttyAMA4` |
| `fix_monitor_lite.py` | `fix_metrics` 正典を使った RTK FIXED 待機（REST ポーリング） | `python3 -m gcs.rtk_tools.fix_monitor_lite --gcs-url http://localhost:8000` |
| `rtk_data_collector.py` | 基地局 + 移動局の同時データ収集・誤差分析 | `python3 -m gcs.rtk_tools.rtk_data_collector --simulate` |

## F9P 設定の RAM / Flash（layer）の別

F9P（ZED-F9P）の CFG-VALSET は **layer**（書き込み先レイヤー）をビットマスクで指定する。

| 定数 | 値 | 意味 |
|---|---|---|
| `LAYER_RAM` | `1` | 揮発（電源断で消える） |
| `LAYER_BBR` | `2` | Battery Backed RAM（バックアップ電源で保持） |
| `LAYER_FLASH` | `4` | 不揮発（再起動後も維持） |
| `LAYER_ALL` | `7` | RAM + BBR + Flash（＝確実な永続化） |

- `f9p_config_all.py` は **既定で `LAYER_ALL=7`** を使う（`save_to_flash=True`）。
- RAM のみで試す場合は `--no-flash` を指定する（`LAYER_RAM=1`）。実験終了後、電源を
  切れば設定は自動的に失われるため、**「実験後の復元」が不要**で安全。

### 実験後の復元手順

実験で F9P の設定を変えた場合、元へ戻す手順は以下のいずれか。

1. **RAM のみで変更した場合（`--no-flash`）**
   - 電源再投入（または `f9p_config_all.py` の `send_reset()`）で揮発設定は消え、Flash に
     保存済みの元設定へ戻る。追加作業は不要。

2. **Flash（layer=7）まで書いた場合**
   - 保存済みベースライン（`logs/f9p_config_baseline_<role>_<port>.json`）がある場合は、
     差分を `f9p_config_monitor.py --once` で確認できる。
   - 元の Golden 値へ戻すには `f9p_config_all.py` を正しい座標・値で再実行する
     （基地局: `--role base --lat <元の緯度> --lon <元の経度> --alt <元の楕円体高>`、
     移動局: `--role rover`）。基準座標は `gcs/config/config.yaml` の
     `base_station.fixed_lat/lon/alt` を参照。

> 復元は「設定を壊す」操作ではないため、必ず `--mode verify` で現在値を確認してから
> 書き込みを行うこと（write-verify の原則）。

## RTCM 注入・中継（設定ファイル駆動）

RTCM の注入・中継は以下の設定ファイルで起動できる（いずれも `gcs/config/` 配下）。

- `rtk_forwarder.yml` … `rtk_forwarder_service.py` 用（tcp / ntrip / serial → serial / udp）
- `rtk_forwarder_ntrip.example.yml` … NTRIP 接続のテンプレート（**認証情報は環境変数**）
- `tcp2serial.yml` … `tcp2serial.py` 用

## 認証情報・シークレットの扱い

- NTRIP の `username` / `password` 等の認証情報は **設定ファイルに平文で書かない**。
- `${ENV_VAR}` 形式で環境変数を参照する（例: `${NTRIP_USER}` / `${NTRIP_PASSWORD}`）。
  環境変数が未設定の場合は空文字になり、ベーシック認証を送信しない。
- 個人用の実設定ファイル（`rtk_forwarder_ntrip.yml`）は `.gitignore` 対象。
  テンプレート（`*.example.yml`）のみリポジトリにコミットする。

```bash
export NTRIP_HOST=ntrip.example.co.jp
export NTRIP_PORT=2101
export NTRIP_MOUNTPOINT=YOUR_MOUNT
export NTRIP_USER=your_user
export NTRIP_PASSWORD=your_password
python3 -m gcs.rtk_tools.rtk_forwarder_service --config rtk_forwarder_ntrip.yml
```

## テスト

```bash
cd <リポジトリルート>
python3 -m pytest gcs/rtk_tools/ -q
```
