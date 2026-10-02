import scipy.io
import numpy as np

mat_path = 'logs/20261001_181637/rtk_evaluation.mat'
data = scipy.io.loadmat(mat_path)

periods = ['5min', '20min', '60min']
labels = {'5min': '5分', '20min': '20分', '60min': '60分'}

report_path = 'logs/20261001_181637/accuracy_report.md'

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

print("Report generated.")
