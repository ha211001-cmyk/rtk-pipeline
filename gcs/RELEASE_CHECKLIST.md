# gcs — リリース手順・動作確認チェックリスト

統合後の `gcs/` を実運用に出すための手順と確認項目です。**実機なしで確認できる
項目（A）** と **実機が必要な項目（B）** を分けて記載しています。実機がない環境では
A をすべて満たし、B は「手順書としての確認」までを行います。

## 0. 前提

- リポジトリ: `~/EVK-F9P`
- Python: 3.9 以上
- 依存導入: `pip install -r requirements.txt`（Raspberry Pi 側は
  `gcs/deploy/requirements_raspi.txt` も追加）

---

## A. 実機なしで確認できる項目（CI / ローカル）

```bash
cd ~/EVK-F9P
```

### A1. 全テスト（単一コマンド）

```bash
python3 -m pytest gcs/
```

- [ ] 全テストが **PASS** すること（295 件超）。
- [ ] 失敗が 1 件も無いこと。

### A2. 実機不要の自己検証（合成データ）

```bash
python3 -m gcs.selftest
```

- [ ] 出力の `"ok": true` であること。
- [ ] `rtcm3_parser`（合成 RTCM3 フレーム抽出 + CRC）が ok。
- [ ] `fix_metrics`（合成 FLOAT→FIXED 系列の TTFF/維持率集計）が ok。
- [ ] `config_schema`（同梱 YAML 6 件の検証）が ok。

### A3. 設定スキーマ検証

```bash
python3 -c "from gcs.config.schema import validate_bundled_configs; print(validate_bundled_configs())"
```

- [ ] 全ファイルの `errors` が `[]` であること。

### A4. 平文シークレットが無いこと

```bash
python3 -m pytest gcs/config/test_no_hardcoded_secrets.py -v
```

- [ ] `gcs/config/` / `gcs/deploy/` に平文の認証情報が無いこと。
- [ ] NTRIP の `username` / `password` が `${ENV}` 参照であること。

### A5. systemd テンプレート検証

```bash
python3 -m pytest gcs/deploy/test_deploy.py -v
```

- [ ] `.service` テンプレートのプレースホルダ置換後、未置換が残らないこと。
- [ ] `ExecStart` が `-m gcs.rtk_tools.*` 形式で正しい設定を参照すること。

### A6. Web サーバー起動スモークテスト

```bash
python3 -m gcs.server --host 127.0.0.1 --port 8000 &
sleep 3
curl -s http://127.0.0.1:8000/api/health
curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/
kill %1
```

- [ ] `/api/health` が 200 を返すこと。
- [ ] `/`（Web UI）が 200 を返すこと。

---

## B. 実機が必要な項目（フィールド / ベンチ）

### B1. Raspberry Pi（Rover 側）の systemd 常駐化

```bash
cd ~/EVK-F9P
./gcs/deploy/setup_raspi.sh            # venv + 依存 + サービス導入
sudo systemctl start rtk-uart4-inject.service tcp2serial.service
systemctl status rtk-uart4-inject.service tcp2serial.service
```

- [ ] 両サービスが `active (running)` であること。
- [ ] `journalctl -u rtk-uart4-inject.service -f` にエラーが無いこと。
- [ ] 再起動後も `systemctl is-enabled` が `enabled` であること。

### B2. 基地局 → Rover の RTCM 注入

- [ ] 基地局（Mac 側 `rtk_base_station_v2` 等）が TCP:2101 で配信していること。
- [ ] Rover の `gcs/config/rtk_forwarder.yml` の `source.host` が正しいこと。
- [ ] `journalctl -u rtk-uart4-inject.service` に "Forward stats" が出ること。

### B3. RTK FIXED 到達

- [ ] Web UI / CLI で Rover の `GPS Fix = RTK_FIXED` を確認。
- [ ] `gcs/fix_type_logger.py` で FIXED 維持率・TTFF を記録。
- [ ] 補正の途切れが無いこと（`gcs/rtcm_monitor.py` の age 監視）。

### B4. 機体制御（Web UI）

- [ ] Connect 後にカードへ機体が表示されること。
- [ ] テレメトリ（Armed / Mode / バッテリー / NED）が更新されること。
- [ ] ⚠️ ARM / DISARM 等の制御は **安全確認の上** で実施（Force Arm は使用禁止）。

### B5. CAN 監視（任意）

```bash
sudo ./gcs/deploy/can_setup_raspi.sh
# 再起動後
candump can0
```

- [ ] DroneCAN メッセージが観測できること。

---

## C. リリース判定

| 項目 | 条件 |
|---|---|
| 実機なし環境 | A1〜A6 をすべて満たすこと |
| 実機あり環境 | A1〜A6 に加え、B1〜B3（+必要なら B4/B5）を満たすこと |

すべて満たした時点でリリース可能と判断します。確認結果は日付・環境・実行者を
添えて記録してください。
