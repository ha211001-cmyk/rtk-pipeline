# RTK (Real-Time Kinematic) 利用ガイド

## クイックスタート

### 対話モード（推奨）

```powershell
C:/Users/keita/AppData/Local/Programs/Python/Python311/python.exe rtk_input.py --interactive
```

対話プロンプトに従い、ポート番号、NTRIP サーバー、マウントポイントを入力してください。  
ユーザー名・パスワードは安全なプロンプトで入力されます。

---

## NTRIP サービス別ガイド

### 1️⃣ RTK2GO.com（無料・推奨）

**メリット**:
- 月額登録不要
- 世界中のマウントポイント
- 安定供給

#### セットアップ手順

1. **マウントポイント探索**
   - https://rtk2go.com/ にアクセス
   - 地図から日本付近をクリック
   - 利用可能なマウントポイントを確認
   - 例: `YMSK`, `YMBE` など

2. **接続実行**
   ```powershell
   C:/Users/keita/AppData/Local/Programs/Python/Python311/python.exe rtk_input.py `
     --port COM13 `
     --server rtk2go.com `
     --mountpoint YMSK `
     --interactive
   ```

3. **プロンプト**
   - Serial port: `COM13`
   - NTRIP Server: `rtk2go.com`
   - NTRIP Port: `2101`
   - Mountpoint: `YMSK` (or your choice)
   - **Username**: メールアドレス (例: `your-email@example.com`)
   - **Password**: 任意（推奨: 複雑なパスワード）

#### マウントポイント例（日本）

| 都道府県 | マウント名 | 備考 |
|---------|-----------|------|
| 千葉 | YMSK | 安定供給 |
| 大阪 | YMBE | 安定供給 |
| 東京 | MYSS | Temporary |

---

### 2️⃣ イチミル（国内提供者）

**メリット**:
- 日本国内最適化
- 高精度補正

#### セットアップ手順

1. **接続情報取得**
   - サービス提供者に接続情報を問い合わせ
   - **Server**: (提供)
   - **Port**: (提供)
   - **Mountpoint**: (提供)
   - **Username**: (提供)
   - **Password**: (提供)

2. **接続実行**
   ```powershell
   C:/Users/keita/AppData/Local/Programs/Python/Python311/python.exe rtk_input.py `
     --port COM13 `
     --server <提供のサーバー> `
     --ntrip-port <提供のポート> `
     --mountpoint <提供のマウント> `
     --username <提供のユーザー> `
     --password <提供のパスワード>
   ```

---

## コマンドラインオプション

```
--port              シリアルポート名 (デフォルト: COM13)
--baudrate          ボーレート (デフォルト: 38400、USB では無視されます)
--server            NTRIP Caster アドレス (例: rtk2go.com)
--ntrip-port        NTRIP ポート (デフォルト: 2101)
--mountpoint        RTK マウントポイント名
--username          NTRIP ユーザー名 (省略時: プロンプト)
--password          NTRIP パスワード (省略時: 隠し入力)
--interactive       対話モード （推奨）
```

### 使用例

#### 完全指定
```powershell
C:/Users/keita/AppData/Local/Programs/Python/Python311/python.exe rtk_input.py `
  --port COM13 `
  --server rtk2go.com `
  --ntrip-port 2101 `
  --mountpoint YMSK `
  --username you@example.com `
  --password yourpassword
```

#### 対話入力
```powershell
C:/Users/keita/AppData/Local/Programs/Python/Python311/python.exe rtk_input.py `
  --port COM13 `
  --server rtk2go.com `
  --ntrip-port 2101 `
  --mountpoint YMSK `
  --interactive
```

---

## リアルタイム出力表示

実行中、5秒ごとに以下の情報が更新表示されます：

```
======================================================================
[1] RTK Integration Status - 2026-03-01 12:34:56
======================================================================

RTK Caster Connection:
  Status: ✓ Connected
  Messages Received: 342

Position Data:
  Latitude:  36.07268123°
  Longitude: 136.59527456°
  Altitude:  45.32 m
  Fix Type:  RTK Fixed
  Satellites: 28

----------------------------------------------------------------------
```

### 項目説明

| 項目 | 説明 |
|------|------|
| Status | RTK Caster との接続状態 |
| Messages Received | 受信した修正データメッセージ数 |
| Latitude/Longitude | 現在位置（WGS84座標系） |
| Altitude | 楕円体高（メートル） |
| Fix Type | GPS/RTK Fixed/RTK Float 等 |
| Satellites | 使用中の衛星数 |

---

## トラブルシューティング

### エラー: "Cannot open COM13"

**原因**: 
- ポート番号が誤っている
- デバイスが接続されていない
- 別のプログラムがポートを使用している

**対策**:
```powershell
# デバイスマネージャーで確認
Get-WmiObject Win32_SerialPort
```

### エラー: "Failed to connect to NTRIP caster"

**原因**:
- インターネット未接続
- サーバーダウン
- ユーザー名・パスワード誤り
- マウントポイント名誤り

**対策**:
1. インターネット接続確認
2. rtk2go.com にブラウザアクセス確認
3. マウントポイント名を再確認

### RTK Fixed が取得できない

**原因**:
- 初期化時間が短すぎる（5-30秒必要）
- 衛星数が不足（最低 15個必要）
- 屋内または遮蔽環境

**対策**:
1. オープンスカイの場所で実行
2. 30秒以上待機
3. Satellites > 15 を確認

### GPS が移動しない

**原因**:
- RTK Fix まで位置が更新されない場合あり

**対策**:
1. 初期化時間を確認
2. Fix Type が "RTK Fixed" まで待機

---

## RTK 基準知識

### Fix Type の種類

```
No Fix      : GPS 信号不足
2D Fix      : 高度なし (通常の GPS)
3D Fix      : 高度あり (通常の GPS)
RTK Float   : RTK 初期化中 (±10-20cm)
RTK Fixed   : RTK 完全初期化 (±2-3cm) ⭐ TARGET
```

### 精度比較

| 方法 | 精度 | 初期化時間 |
|------|------|----------|
| 標準 GPS | ±5m | 即座 |
| DGPS | ±1m | 数秒 |
| RTK Float | ±10-20cm | 数秒 |
| RTK Fixed | ±2-3cm | 30秒～数分 |

### 衛星信号

```
GPS       : 1575.42 MHz (L1)
GLONASS   : 1602 MHz (L1)
Galileo   : 1575.42 MHz (E1)
BeiDou    : 1561.098 MHz (B1)
```

rtk-pipeline は全システム対応で、より多くの衛星が利用できます。

---

## セキュリティ上の注意

⚠️ **重要**: パスワードの取り扱い

1. **プロンプト入力を推奨**
   ```powershell
   # パスワードが隠し入力されます
   python rtk_input.py --interactive
   ```

2. **コマンドラインでの指定回避**
   ```powershell
   # ❌ 非推奨（履歴に記録される）
   python rtk_input.py --password mypassword
   ```

3. **環境変数使用法（高度）**
   ```powershell
   $env:RTK_PASSWORD = "yourpassword"
   python rtk_input.py --password $env:RTK_PASSWORD
   ```

---

## 参考リンク

- **RTK2GO Caster**: https://rtk2go.com/
- **NTRIP 仕様**: https://igs.bkg.bund.de/ntrip/
- **u-blox F9P ドキュメント**: https://www.u-blox.com/en/product/zed-f9p-module
- **pygnssutils GitHubリポジトリ**: https://github.com/semuconsulting/pygnssutils

---

## よくある質問 (FAQ)

**Q: 無料で RTK が使えるの？**  
A: はい。rtk2go.com は無料で全世界のマウントポイントを提供しています。登録・月額料金不要です。

**Q: インターネット切れたらどうなるの？**  
A: 修正データが受信できず、RTK Fixed が失われて標準 GPS に戻ります。再接続時に再初期化が必要です。

**Q: 複数の F9P を同時に接続できる？**  
A: はい。ただしシリアルポートが異なればプロセスを分けて実行。同じポートは不可。

**Q: 動作に必要な PC スペック？**  
A: CPU: Core i3 以上、RAM: 2GB 以上で十分です。

**Q: ローバー機能だけで、基準局を自分で構築できる？**  
A: 基準局構築には別途設定（F9P を Base Station モード）が必要です。現在のプログラムはローバー受信専用です。

---

**Questions?** 詳細は ENVIRONMENT_INFO.md を参照してください。
