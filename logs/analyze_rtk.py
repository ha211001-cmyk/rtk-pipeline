import pandas as pd
import numpy as np
import scipy.io as sio
import matplotlib.pyplot as plt

# Load the data
csv_file = '/Users/taitai0123/rtk-pipeline/logs/rtk_status_60min_complete.csv'
df = pd.read_csv(csv_file)

# We need to filter only RTK_FIXED if necessary, but assuming all are valid or we just take the data.
# Let's check how many non-RTK_FIXED there are.
# print(df['fix_name'].value_counts())

# Ground truth: mean of the 60 min data (assuming it's a static test)
mean_lat = df['lat'].mean()
mean_lon = df['lon'].mean()
mean_alt = df['alt'].mean()

print(f"Reference Point: Lat={mean_lat:.8f}, Lon={mean_lon:.8f}, Alt={mean_alt:.3f}")

# Convert to local ENU (East, North, Up) in meters
# 1 deg lat = 111319.9 m
# 1 deg lon = 111319.9 * cos(lat) m
lat_to_m = 111319.9
lon_to_m = 111319.9 * np.cos(np.radians(mean_lat))

df['E'] = (df['lon'] - mean_lon) * lon_to_m
df['N'] = (df['lat'] - mean_lat) * lat_to_m
df['U'] = df['alt'] - mean_alt

# Horizontal and 3D error
df['H_err'] = np.sqrt(df['E']**2 + df['N']**2)
df['3D_err'] = np.sqrt(df['E']**2 + df['N']**2 + df['U']**2)

# Time slices
durations = [5, 20, 60]
results = {}
mat_data = {}

for m in durations:
    # Get data within the first m minutes
    df_slice = df[df['elapsed_sec'] <= m * 60]
    
    std_E = df_slice['E'].std()
    std_N = df_slice['N'].std()
    std_U = df_slice['U'].std()
    
    mean_H_err = df_slice['H_err'].mean()
    mean_3D_err = df_slice['3D_err'].mean()
    
    results[m] = {
        'std_E': std_E,
        'std_N': std_N,
        'std_U': std_U,
        'mean_H_err': mean_H_err,
        'mean_3D_err': mean_3D_err,
        'count': len(df_slice)
    }
    
    print(f"--- {m} minutes ({len(df_slice)} samples) ---")
    print(f"Std Dev (m) - East: {std_E:.4f}, North: {std_N:.4f}, Up: {std_U:.4f}")
    print(f"Mean Error (m) - Horizontal: {mean_H_err:.4f}, 3D: {mean_3D_err:.4f}")
    
    # Save data for mat file
    mat_data[f'E_{m}min'] = df_slice['E'].values
    mat_data[f'N_{m}min'] = df_slice['N'].values
    mat_data[f'U_{m}min'] = df_slice['U'].values
    mat_data[f'Herr_{m}min'] = df_slice['H_err'].values
    mat_data[f'err3D_{m}min'] = df_slice['3D_err'].values

# Save to .mat file
sio.savemat('/Users/taitai0123/rtk-pipeline/logs/rtk_evaluation_data.mat', mat_data)
print("Saved .mat file to /Users/taitai0123/rtk-pipeline/logs/rtk_evaluation_data.mat")

# Plotting Histogram
fig, axs = plt.subplots(3, 1, figsize=(8, 12))
colors = {5: 'blue', 20: 'orange', 60: 'green'}
for i, m in enumerate(durations):
    axs[i].hist(mat_data[f'Herr_{m}min'], bins=50, color=colors[m], alpha=0.7)
    axs[i].set_title(f'Horizontal Error Distribution ({m} min)')
    axs[i].set_xlabel('Error (m)')
    axs[i].set_ylabel('Frequency')
    axs[i].grid(True)

plt.tight_layout()
plt.savefig('/Users/taitai0123/rtk-pipeline/logs/rtk_histograms.png')
print("Saved histograms to /Users/taitai0123/rtk-pipeline/logs/rtk_histograms.png")
