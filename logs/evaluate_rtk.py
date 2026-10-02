import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import scipy.io
import datetime
import os

print("Loading data...")
df = pd.read_csv('logs/rtk_status_60min_complete.csv')

df['time'] = pd.to_datetime(df['utc_time'], format='%H:%M:%S').dt.time
dummy_date = datetime.date(2023, 1, 1)
df['dt'] = df['time'].apply(lambda t: datetime.datetime.combine(dummy_date, t))

start_dt = datetime.datetime.combine(dummy_date, datetime.time(18, 16, 40))
df = df[df['dt'] >= start_dt].copy()

# Reference position is the mean of the 60min data
mean_lat = df['lat'].mean()
mean_lon = df['lon'].mean()
mean_alt = df['alt'].mean()

R_earth = 6378137.0
df['dx'] = np.radians(df['lon'] - mean_lon) * np.cos(np.radians(mean_lat)) * R_earth
df['dy'] = np.radians(df['lat'] - mean_lat) * R_earth
df['dz'] = df['alt'] - mean_alt
df['err_2d'] = np.sqrt(df['dx']**2 + df['dy']**2)
df['err_3d'] = np.sqrt(df['err_2d']**2 + df['dz']**2)

periods = {'5min': 5, '20min': 20, '60min': 60}
results = {}
mat_data = {}

for name, mins in periods.items():
    end_dt = start_dt + datetime.timedelta(minutes=mins)
    sub_df = df[df['dt'] < end_dt]
    
    std_x = sub_df['dx'].std()
    std_y = sub_df['dy'].std()
    std_z = sub_df['dz'].std()
    
    mean_err_2d = sub_df['err_2d'].mean()
    rms_2d = np.sqrt(np.mean(sub_df['err_2d']**2))
    
    results[name] = {
        'std_x': std_x, 'std_y': std_y, 'std_z': std_z,
        'mean_err_2d': mean_err_2d, 'rms_2d': rms_2d
    }
    
    mat_data[f'{name}_dx'] = sub_df['dx'].values
    mat_data[f'{name}_dy'] = sub_df['dy'].values
    mat_data[f'{name}_dz'] = sub_df['dz'].values
    mat_data[f'{name}_err2d'] = sub_df['err_2d'].values
    
    # Save a quick histogram
    fig, axs = plt.subplots(1, 3, figsize=(15, 4))
    axs[0].hist(sub_df['dx'], bins=30, color='r', alpha=0.7)
    axs[0].set_title(f'Easting Error (m) - {name}')
    axs[1].hist(sub_df['dy'], bins=30, color='g', alpha=0.7)
    axs[1].set_title(f'Northing Error (m) - {name}')
    axs[2].hist(sub_df['err_2d'], bins=30, color='b', alpha=0.7)
    axs[2].set_title(f'2D Error (m) - {name}')
    plt.tight_layout()
    plt.savefig(f'logs/hist_{name}.png')
    plt.close()

scipy.io.savemat('logs/rtk_evaluation.mat', mat_data)
print("Saved logs/rtk_evaluation.mat")

for k, v in results.items():
    print(f"[{k}]")
    print(f"  標準偏差 (East, North, Up): {v['std_x']:.4f}m, {v['std_y']:.4f}m, {v['std_z']:.4f}m")
    print(f"  平均誤差 (2D): {v['mean_err_2d']:.4f}m")
    print(f"  RMS誤差 (2D): {v['rms_2d']:.4f}m")
