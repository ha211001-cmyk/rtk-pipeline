# gcs/config — 設定ファイル・スキーマ検証

統合後の gcs/ が使う設定を一元管理します。**接続設定（MAVLink / ドローン）** と
**監視・判定基準**、そして **RTCM 転送 / TCP→シリアル** の実行時設定がここに
まとまっています。

## 設定ファイル一覧

| ファイル | 用途 | コミット |
|---|---|---|
| `gcs.yml` | MAVLink 接続のデフォルト（serial / udp / drones） | ✅ |
| `gcs_local.yml` | ローカル開発用（UDP + 複数ドローン例） | ✅ |
| `gcs_multidrone_example.yml` | 複数ドローン管理の例 | ✅ |
| `gcs.user.local.yml` | **個人用上書き**（シリアルポート等） | ❌（gitignore） |
| `config.yaml` | 統合テストの一元設定（監視・判定基準） | ✅ |
| `config.local.yaml` | 個人用上書き（TCP 接続版テンプレートあり） | ❌（gitignore） |
| `rtk_forwarder.yml` | RTCM 転送サービス設定 | ✅ |
| `rtk_forwarder_ntrip.yml` | NTRIP 実設定（認証情報） | ❌（gitignore） |
| `rtk_forwarder_ntrip.example.yml` | NTRIP 設定テンプレート（`${ENV}` 参照） | ✅ |
| `tcp2serial.yml` | TCP→シリアル橋渡し設定 | ✅ |
| `base_station.json` | 基地局設定の JSON 例 | ✅ |

> テンプレートは `*.example.*` / `*.local.example.*` のみコミットします。
> 実設定（`config.local.yaml` / `gcs.user.local.yml` / `rtk_forwarder_ntrip.yml`）は
> `gcs/config/.gitignore` の対象です。

## 設定の優先順位

接続設定は `gcs/rtk_tools/config_loader.py` が以下の順で解決します（高い順）:

1. CLI 明示パス
2. 環境変数 `GCS_CONFIG_PATH`
3. `gcs.user.local.yml`
4. `gcs_local.yml`
5. `gcs.yml`

さらに `DEFAULT_CONFIG`（deep merge）で補完されるため、一部のキーを省略しても
既定値で動作します。

## スキーマ検証

`gcs/config/schema.py` が 3 種類の設定を検証します:

```bash
# 同梱設定を一括検証（セルフチェック）
python3 -c "from gcs.config.schema import validate_bundled_configs; print(validate_bundled_configs())"

# 任意の YAML を検証
python3 - <<'PY'
from gcs.config.schema import validate_config_file
cfg, errors = validate_config_file("gcs/config/gcs.yml", "gcs")
print(errors)
PY
```

- `kind` は `gcs` / `rtk_forwarder` / `tcp2serial` のいずれか。
- 数値フィールドは `${ENV_VAR}` 形式の環境変数参照も許可します（実行時に解決）。
- テスト: `gcs/config/test_schema.py`。

## シークレットの扱い（重要）

**認証情報・シークレットは設定ファイルに平文で書きません。**

- NTRIP の `username` / `password` は `${NTRIP_USER}` / `${NTRIP_PASSWORD}` の
  環境変数参照で記述します（`gcs/rtk_tools/rtk_forwarder_service.py` の
  `_expand_env` が解決）。
- 環境変数が未設定の場合は空文字になり、ベーシック認証を送信しません。
- 平文シークレットが無いことは `gcs/config/test_no_hardcoded_secrets.py` が
  テストで担保します。

```bash
# NTRIP を使用する場合の例
export NTRIP_HOST=ntrip.example.co.jp
export NTRIP_PORT=2101
export NTRIP_MOUNTPOINT=YOUR_MOUNT
export NTRIP_USER=your_user
export NTRIP_PASSWORD=your_password

cp gcs/config/rtk_forwarder_ntrip.example.yml gcs/config/rtk_forwarder_ntrip.yml
python3 -m gcs.rtk_tools.rtk_forwarder_service --config rtk_forwarder_ntrip.yml
```

## 環境別テンプレートの整備方針

- **接続（serial）**: `config.local.example.yaml` を `config.local.yaml` にコピーし、
  `forward.mode: tcp`（DroneCAN Serial Forwarding）やシリアルポートを環境に合わせて編集。
- **接続（udp / 複数ドローン）**: `gcs_multidrone_example.yml` を参照。
- **NTRIP**: `rtk_forwarder_ntrip.example.yml` を `rtk_forwarder_ntrip.yml` にコピーし、
  環境変数で認証情報を渡す。
- **TCP→シリアル**: `tcp2serial.yml` の `serial_device` を実機のデバイス名に変更。
