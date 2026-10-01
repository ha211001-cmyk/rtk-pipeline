# wifi_scripts — ラズパイの Wi-Fi 接続 & NTRIP ルーティング設定スクリプト集

ルート直下に散在していた Wi-Fi 設定スクリプト 6 本を集約したディレクトリです。
ラズパイの `wlan0` を Wi-Fi（SSID: だるま雪2）へ接続し、NTRIP サーバー
（`ntrip.ales-corp.co.jp:2101`）への通信だけを wlan0 経由に振り分けます。
これにより、有線 `eth0` 経由の SSH 接続を維持したまま、RTK 補正データの取得経路を確保できます。

## 背景・目的

- ラズパイは通常 `eth0`（有線）経由で SSH 運用しており、この接続は維持したい。
- NTRIP サーバーからの補正データ取得は Wi-Fi（`wlan0`）経由にしたい。
- そのため、単に Wi-Fi へ接続するだけでなく、
  「`ntrip.ales-corp.co.jp` 宛のルートだけ wlan0 経由に追加する」処理が必要。
- 本ディレクトリの各スクリプトは、接続方式を変えながら試行錯誤した履歴であり、
  最終的にどの方式が安定するかを比較できるよう整理した。

> 接続方式は大きく 2 系統あります。
> 1. **NetworkManager（nmcli）** を使う方式
> 2. **wpa_supplicant + dhclient** で NetworkManager をバイパスする方式

## ディレクトリ構成

```
wifi_scripts/
├── README.md           # このファイル（全体概要・使い分け）
├── setup_wifi.sh       # NetworkManager (nmcli) 方式（シェル）
├── setup_wifi2.py      # NetworkManager（nmconnection 直接書き込み）方式
├── setup_wifi3.py      # wpa_supplicant + dhclient 方式（Python）
├── setup_wifi4.py      # NetworkManager（nmconnection 直接書き込み）方式・改良版 ⭐
├── setup_wifi5.sh      # wpa_supplicant + dhclient 方式（シェル・PSKハッシュ直書き）
└── setup_wifi6.sh      # wpa_supplicant + dhclient 方式（シェル・PSK自動生成）
```

## 各スクリプトの役割一覧

### 共通の接続情報

| 項目 | 値 |
|---|---|
| SSID | だるま雪2 |
| PSK（パスフレーズ） | 1234546789（※ setup_wifi6.sh のみ 123456789） |
| Wi-Fi インターフェース | wlan0 |
| NTRIP サーバー | ntrip.ales-corp.co.jp:2101 |

### スクリプト別の役割

| ファイル | 言語 | 接続方式 | 概要 |
|---|---|---|---|
| `setup_wifi.sh` | bash | NetworkManager (nmcli) | `nmcli dev wifi connect` で接続 → NTRIP IP へルート追加 → 到達テスト |
| `setup_wifi2.py` | Python3 | NetworkManager（nmconnection 直接書き込み） | NM プロファイルを `/etc/NetworkManager/system-connections/daruma.nmconnection` に生成 → `nmcli con reload/up` |
| `setup_wifi3.py` | Python3 | wpa_supplicant + dhclient | NM を unmanage して wpa_supplicant で接続。SSH(eth0) 維持の意図を明記 |
| `setup_wifi4.py` | Python3 | NetworkManager（nmconnection 直接書き込み） | setup_wifi2.py の改良版。UUID 明示・既存削除・エラーログ確認・NTRIP ルート追加まで完備 ⭐ |
| `setup_wifi5.sh` | bash | wpa_supplicant + dhclient | setup_wifi3.py のシェル版。PSK はハッシュ済みを直書き |
| `setup_wifi6.sh` | bash | wpa_supplicant + dhclient | `wpa_passphrase` で PSK をその場で生成。※ passphrase が他と異なる |

### 各スクリプトの詳細

#### `setup_wifi.sh` — NetworkManager (nmcli) 方式・シェル
- `nmcli dev wifi connect` で `wlan0` を `だるま雪2` へ接続（PSK 平文）。
- 接続後、`ntrip.ales-corp.co.jp` の IP を解決し、その IP 宛のルートを wlan0 経由に追加。
- 最後に `ping` と `nc` で Google DNS / NTRIP:2101 への到達性を確認。
- 失敗時は `nmcli dev wifi list` でスキャン結果を表示して終了。

#### `setup_wifi2.py` — NetworkManager (nmconnection 直接書き込み)
- NM の接続プロファイルを `/etc/NetworkManager/system-connections/daruma.nmconnection` へ直接書き込み。
- `nmcli con reload` → `nmcli con up だるま雪2` で接続。
- IPv4 は `method=auto` + `route-metric=200`、IPv6 は `method=ignore`。
- NTRIP ルート追加やエラー処理は無い（接続まで）。

#### `setup_wifi4.py` — NetworkManager (nmconnection 直接書き込み)・改良版 ⭐
- `setup_wifi2.py` の改良版。UUID を明示生成し、既存プロファイル（`だるま雪2`）を削除してから再作成。
- `nmcli con up` にタイムアウト（30 秒）を設定し、失敗時は `journalctl` で NM のログを確認。
- IPv6 は `method=auto`。NTRIP の IP 解決 → wlan0 経由ルート追加 → ポート 2101 到達テストまで一通り完備。

#### `setup_wifi3.py` — wpa_supplicant + dhclient（Python）
- NetworkManager をバイパスして接続する方式。
- `nmcli dev set wlan0 managed no` で NM の管理対象から外し、wpa_supplicant を手動起動。
- `wpa_cli status` で `COMPLETED` を確認 → `dhclient wlan0` で IP 取得。
- NTRIP ルート追加・到達テストまで実施。
- ドキュメントに「SSH (eth0) は維持したまま」と明記（本ディレクトリの目的を最も明確に表す）。

#### `setup_wifi5.sh` — wpa_supplicant + dhclient（シェル・PSK ハッシュ直書き）
- `setup_wifi3.py` のシェル版。NM の unmanage（`nmcli dev set wlan0 managed no`）を実施。
- wpa_supplicant の設定ファイルに PSK のハッシュ値を直書き。
- 直書きされている PSK `79bb645f…` は passphrase `1234546789` のハッシュ（他スクリプトと一致）。

#### `setup_wifi6.sh` — wpa_supplicant + dhclient（シェル・PSK 自動生成）
- `setup_wifi5.sh` とほぼ同じ流れだが、PSK を `wpa_passphrase` コマンドでその場で生成。
- ハッシュ値をハードコードしないため、passphrase を変えても生成処理はそのまま使える。
- ⚠️ passphrase が `123456789`（9 桁）で、他スクリプトの `1234546789`（10 桁）と一致しない。
- ⚠️ NM の unmanage（`nmcli dev set wlan0 managed no`）を行わない点が `setup_wifi5.sh` と異なる。

## 重複スクリプトの使い分け（推奨）

スクリプト番号は概ね作成順で、番号が大きいほど後発（改良版）です。
接続方式が 2 系統あるため、環境に応じて以下を選んでください。

### 方式 A: NetworkManager（nmcli）を使う場合

| 位置づけ | ファイル | 説明 |
|---|---|---|
| ⭐ 最新・推奨 | `setup_wifi4.py` | UUID 明示・既存削除・エラーログ確認・NTRIP ルート追加まで完備した最も堅牢な版 |
| 簡易確認 | `setup_wifi.sh` | 1 コマンドで接続＋到達テストまで行える手軽な版 |
| （旧） | `setup_wifi2.py` | 初期版。接続のみでエラー処理・ルート追加が無い。原則 `setup_wifi4.py` を使用 |

### 方式 B: wpa_supplicant + dhclient（NM をバイパス）する場合

| 位置づけ | ファイル | 説明 |
|---|---|---|
| ⭐ 推奨 | `setup_wifi5.sh` | passphrase が多数派（`1234546789`）と一致し、NM unmanage も実施。安定運用向け |
| 最新（要確認） | `setup_wifi6.sh` | PSK 自動生成が特徴だが、passphrase 不一致＋NM unmanage なし。接続できない場合は要確認 |
| Python 版 | `setup_wifi3.py` | 上記の Python 版。目的・意図がコメントで最も明確 |

> **どちらを選ぶか**:
> NetworkManager が正常に動作している環境では方式 A（`setup_wifi4.py`）がシンプルで安定します。
> NM が wlan0 の管理と競合して接続が不安定になる場合は、方式 B（wpa_supplicant + dhclient）を試してください。
> 方式 B では passphrase が一致している `setup_wifi5.sh` をまず使い、
> PSK を都度生成したい場合は `setup_wifi6.sh` の passphrase（`123456789`）が正しいかを確認してから使用してください。

## 実行方法

> いずれも root 権限が必要です（`/etc/NetworkManager` への書き込み、
> `nmcli` / `ip route` / `wpa_supplicant` / `dhclient` を実行するため）。

### NetworkManager 方式

```bash
cd ~/EVK-F9P/wifi_scripts

# 推奨（改良版）
sudo python3 setup_wifi4.py

# 手軽な疎通確認のみ
sudo bash setup_wifi.sh
```

### wpa_supplicant + dhclient 方式

```bash
cd ~/EVK-F9P/wifi_scripts

# 推奨（passphrase が一致する直書きハッシュ版）
sudo bash setup_wifi5.sh

# Python 版（目的・意図をコメントで確認したい場合）
sudo python3 setup_wifi3.py
```

各スクリプトは接続後、`ntrip.ales-corp.co.jp:2101` への到達テストまで行い、
「ポート2101 接続成功 / 到達OK」と表示されれば接続・ルーティングとも正常です。

## 注意点

- **root 権限が必須**: いずれのスクリプトも `sudo` で実行してください。
- **PSK（パスフレーズ）の不一致（setup_wifi6.sh）**:
  `setup_wifi6.sh` のみ passphrase が `123456789`（9 桁）で、他の 5 本の `1234546789`（10 桁）と
  一致していません。`setup_wifi6.sh` で接続できない場合は `setup_wifi5.sh` を試してください。
  （スクリプト本体は未変更のため、passphrase の見直しは別途判断してください。）
- **認証情報・パスフレーズが平文でハードコード**されています。取り扱いに注意してください
  （本リポジトリの他スクリプトと同様の運用）。
- **eth0 の SSH は維持する前提**: 各スクリプトは NTRIP 宛のルートだけ wlan0 に振り分けますが、
  環境によってはデフォルトルートが変わることがあります。切断時は有線側から確認してください。
- **ロジック変更は行っていません**: 本ディレクトリへの移動は `git mv` による履歴保持のみで、
  各スクリプトの中身は変更していません。

## 更新履歴

- 2026-09-27: ディレクトリ新設。ルート直下の Wi-Fi 設定スクリプト 6 本を `git mv` で集約し、README を追加。
