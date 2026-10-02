import scipy.io
import numpy as np
import sys
import os

if len(sys.argv) < 3:
    print('Usage: python generate_report.py <TARGET_DIR> <TIMESTAMP>')
    sys.exit(1)
target_dir = sys.argv[1]
timestamp = sys.argv[2]
mat_path = os.path.join(target_dir, f'rtk_evaluation_{timestamp}.mat')
data = scipy.io.loadmat(mat_path)

periods = ['5min', '20min', '60min']
labels = {'5min': '5分', '20min': '20分', '60min': '60分'}

report_path = os.path.join(target_dir, f'accuracy_report_{timestamp}.md')

with open(report_path, 'w', encoding='utf-8') as f:
    f.write("# RTK測位精度 評価レポート (水平・高さ)\n\n")
    f.write("全体（60分間）の平均座標を基準値（真値）とし、5分・20分・60分間の各データ区間について、水平方向（2D）と高さ方向（Up）の標準偏差と平均誤差を算出しました。\n\n")
    
    f.write("## 評価結果まとめ\n\n")
    f.write("| 計測時間 | 水平方向 平均誤差 | 水平方向 標準偏差 | 高さ方向 平均絶対誤差 | 高さ方向 標準偏差 |\n")
    f.write("| :--- | :--- | :--- | :--- | :--- |\n")
    
    for p in periods:
        # Load arrays
        err_2d = data[f'x{p}_err2d'][0]
        dz = data[f'x{p}_dz'][0]
        
        # Calculate stats in mm
        mean_2d = np.mean(err_2d) * 1000
        std_2d = np.std(err_2d) * 1000
        
        mean_abs_dz = np.mean(np.abs(dz)) * 1000
        std_dz = np.std(dz) * 1000
        
        f.write(f"| **{labels[p]}** | {mean_2d:.2f} mm | {std_2d:.2f} mm | {mean_abs_dz:.2f} mm | {std_dz:.2f} mm |\n")
        
    f.write("\n")
    f.write("### 用語の解説\n")
    f.write("- **水平方向 平均誤差**: 各測位点の基準座標からの水平距離（2D誤差）の平均値です。\n")
    f.write("- **水平方向 標準偏差**: 水平誤差のバラツキの大きさを示します。\n")
    f.write("- **高さ方向 平均絶対誤差**: 基準となる高さからどれだけ上下にズレているか（絶対値）の平均値です。\n")
    f.write("- **高さ方向 標準偏差**: 高さのズレのバラツキ（不安定さ）を示します。GNSSの特性上、一般的に水平方向よりも大きくなります。\n")

    f.write("\n\n## 誤差分布のヒストグラム\n\n")
    f.write("以下のグラフは、各観測時間（5分・20分・60分）における誤差の分布（相対度数）を示しています。データの件数に依存せず純粋な形状を比較できるよう、縦軸は確率（相対度数）で統一し、グラフのスケールも揃えています。\n\n")
    f.write("### 水平方向誤差\n")
    f.write("この分布の平均値が上記の「水平方向 平均誤差」に相当します。\n\n")
    f.write(f"![水平方向誤差](./hist_horizontal_{timestamp}.png)\n\n")
    f.write("### 高さ方向誤差（符号付き）\n")
    f.write("高さ方向のズレ（上方向が正、下方向が負）の分布です。この分布の絶対値の平均が「高さ方向 平均絶対誤差」に相当します。\n\n")
    f.write(f"![高さ方向誤差](./hist_height_{timestamp}.png)\n")
    
    f.write("\n\n### 補足：データの分解能（ヒストグラムの形状）について\n")
    f.write("ヒストグラムの分布が滑らかな曲線ではなく、離散的な（隙間が空いたような）形状になっているのは、GNSS受信機から出力される**元データの分解能（ログの丸め精度）**に起因しています。\n\n")
    f.write("- **水平方向（緯度・経度）**: ログ出力が小数点以下7桁（度）となっており、距離換算で **約9〜11 mm間隔** の離散値となっています。\n")
    f.write("- **高さ方向（高度）**: ログ出力が小数点以下2桁（メートル）となっており、厳密に **10 mm間隔** の離散値となっています。\n\n")
    f.write("このように、データ自体が約1cm刻みのグリッド状に量子化されて記録されているため、グラフ上でも数ミリ単位の隙間が生じる結果となっています。これは分析手法の問題ではなく、機器の出力フォーマットによる正常な仕様です。\n")

print("Report generated.")
