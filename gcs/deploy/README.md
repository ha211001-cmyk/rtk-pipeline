# gcs/deploy — systemd 常駐化・Raspberry Pi セットアップ

GCS-UmemotoLab から移行したデプロイ資産を、統合後の `rtk-pipeline/gcs/` 構成に
合わせて再配置したものです。Raspberry Pi（Rover 側）で、RTCM 注入系サービスを
**systemd で常駐起動**するためのテンプレートとインストールスクリプトを提供します。

## ファイル一覧

| ファイル | 役割 |
|---|---|
| `rtk-uart4-inject.service` | RTCM 転送（`rtk_forwarder_service`）の systemd テンプレート |
| `tcp2serial.service` | TCP→シリアル橋渡し（`tcp2serial`）の systemd テンプレート |
| `install_rtk_uart4_service.sh` | `rtk-uart4-inject.service` を導入・enable |
| `install_tcp2serial_service.sh` | `tcp2serial.service` を導入・enable |
| `install_all_services.sh` | 上記 2 サービスを一括導入 |
| `uninstall_rtk_uart4_service.sh` | `rtk-uart4-inject.service` を停止・無効化・削除 |
| `uninstall_tcp2serial_service.sh` | `tcp2serial.service` を停止・無効化・削除 |
| `setup_raspi.sh` | venv 作成・依存導入・サービス導入をまとめた単一セットアップ |
| `start_raspi_services.sh` | systemd を使わない手動起動版（デバッグ用） |
| `can_setup_raspi.sh` | MCP2515 CAN インターフェース設定（DroneCAN 監視用） |
| `can0.link` / `can0.network` / `interfaces.d/can0` | CAN ネットワーク設定（systemd-networkd / ifupdown） |
| `mavlink_router_raspi.conf` | mavlink-router 設定（Pixhawk ⇄ GCS ルーティング） |
| `requirements_raspi.txt` | Raspberry Pi 側の追加依存 |

> 認証情報・シークレットは **一切ハードコードしません**。NTRIP の
> `username` / `password` は `gcs/config/rtk_forwarder.yml` 内で
> `${NTRIP_USER}` / `${NTRIP_PASSWORD}` の環境変数参照として記述します。

## 前提

- Raspberry Pi 5（Rover 側）に本リポジトリを配置済み（例: `~/rtk-pipeline`）。
- `/dev/ttyAMA0`（Pixhawk TELEM1）と `/dev/ttyAMA4`（F9P UART2）を
  `config.txt` で有効化済み（`enable_uart=1` / `dtoverlay=uart4`）。
- 基地局側（Mac など）が TCP:2101 で RTCM を配信している。

## 単一セットアップ手順

```bash
cd ~/rtk-pipeline

# 1. venv 作成 + 依存導入 + systemd サービス導入（一括）
./gcs/deploy/setup_raspi.sh

# 2.（任意）DroneCAN 監視用の CAN インターフェースも設定する場合
sudo ./gcs/deploy/setup_raspi.sh --can

# 3. サービス起動
sudo systemctl start rtk-uart4-inject.service tcp2serial.service

# 4. 状態確認
systemctl status rtk-uart4-inject.service tcp2serial.service
journalctl -u rtk-uart4-inject.service -f
```

## systemd サービスの導入詳細

`.service` ファイルはテンプレートで、`@INSTALL_DIR@`（リポジトリルート）と
`@GCS_USER@`（実行ユーザー）をインストールスクリプトが自動置換して
`/etc/systemd/system/` へ配置します。

```bash
cd ~/rtk-pipeline/gcs/deploy
./install_rtk_uart4_service.sh     # rtk-uart4-inject.service のみ
./install_tcp2serial_service.sh    # tcp2serial.service のみ
./install_all_services.sh          # 両方
```

実行ユーザーを明示したい場合は `GCS_USER=pi ./install_all_services.sh` とします。
削除は `./uninstall_rtk_uart4_service.sh` / `./uninstall_tcp2serial_service.sh`。

## 各サービスの役割

### rtk-uart4-inject.service

- 実行: `.venv/bin/python -m gcs.rtk_tools.rtk_forwarder_service`
- 設定: `gcs/config/rtk_forwarder.yml`
- 動作: 基地局の生 TCP ストリーム（TCP:2101）を RTCM 受信し、
  F9P Rover の `/dev/ttyAMA4` へ注入。再接続は自動（`retry.reconnect_sec`）。

### tcp2serial.service

- 実行: `.venv/bin/python -m gcs.rtk_tools.tcp2serial`
- 設定: `gcs/config/tcp2serial.yml`
- 動作: TCP（0.0.0.0:2102）で受けたバイト列を `/dev/ttyAMA4` へ転送。
  自動再接続・ヘルスチェック・SIGTERM graceful shutdown 対応。

## CAN 設定（任意）

DroneCAN 経由の RTCM 監視を行う場合のみ必要です。

```bash
sudo ./gcs/deploy/can_setup_raspi.sh          # systemd-networkd（推奨）
sudo ./gcs/deploy/can_setup_raspi.sh --interfaces  # ifupdown を使う場合
```

設定後は再起動が必要です（device tree overlay 反映）。

## mavlink-router（任意）

Pixhawk と GCS の MAVLink をルーティングする場合:

```bash
sudo cp gcs/deploy/mavlink_router_raspi.conf /etc/mavlink-router/main.conf
sudo systemctl restart mavlink-router
```

- MAVLink: `/dev/ttyAMA0`（921600 bps）⇄ UDP:14550 + TCP:5760
