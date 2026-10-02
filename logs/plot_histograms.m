% plot_histograms.m
clear; close all; clc;

[script_dir, ~, ~] = fileparts(mfilename('fullpath'));
mat_file = fullfile(script_dir, '20261001_181637', 'rtk_evaluation.mat');
if ~exist(mat_file, 'file')
    error('ファイルが見つかりません: %s', mat_file);
end

data = load(mat_file);
% 単位変換 (m -> mm)
err_5min  = data.x5min_err2d * 1000;
err_20min = data.x20min_err2d * 1000;
err_60min = data.x60min_err2d * 1000;

% 高さ方向誤差 (符号付き)
dz_5min  = data.x5min_dz * 1000;
dz_20min = data.x20min_dz * 1000;
dz_60min = data.x60min_dz * 1000;

bin_width = 1.0; 

%% Figure 1: 水平方向誤差のヒストグラム (この分布の平均値が「水平方向 平均誤差」)
figure('Name', 'Figure 1: 水平方向誤差 ヒストグラム', 'Position', [100, 100, 1200, 400]);
max_err = max([err_5min(:); err_20min(:); err_60min(:)]);
x_lim = [0, ceil(max_err) + 2];

% 5分間
ax1 = subplot(1, 3, 1);
histogram(err_5min, 'BinWidth', bin_width, 'Normalization', 'probability', 'FaceColor', [0 0.4470 0.7410], 'EdgeColor', 'k');
title('水平方向誤差 (5分間)'); xlabel('誤差 (mm)'); ylabel('相対度数'); xlim(x_lim); grid on;
text(x_lim(2)*0.40, 0.9, sprintf('平均誤差: %.2f mm\n標準偏差: %.2f mm', mean(err_5min), std(err_5min)), 'Units', 'normalized', 'BackgroundColor', 'w');

% 20分間
ax2 = subplot(1, 3, 2);
histogram(err_20min, 'BinWidth', bin_width, 'Normalization', 'probability', 'FaceColor', [0.8500 0.3250 0.0980], 'EdgeColor', 'k');
title('水平方向誤差 (20分間)'); xlabel('誤差 (mm)'); ylabel('相対度数'); xlim(x_lim); grid on;
text(x_lim(2)*0.40, 0.9, sprintf('平均誤差: %.2f mm\n標準偏差: %.2f mm', mean(err_20min), std(err_20min)), 'Units', 'normalized', 'BackgroundColor', 'w');

% 60分間
ax3 = subplot(1, 3, 3);
histogram(err_60min, 'BinWidth', bin_width, 'Normalization', 'probability', 'FaceColor', [0.9290 0.6940 0.1250], 'EdgeColor', 'k');
title('水平方向誤差 (60分間)'); xlabel('誤差 (mm)'); ylabel('相対度数'); xlim(x_lim); grid on;
text(x_lim(2)*0.40, 0.9, sprintf('平均誤差: %.2f mm\n標準偏差: %.2f mm', mean(err_60min), std(err_60min)), 'Units', 'normalized', 'BackgroundColor', 'w');

linkaxes([ax1, ax2, ax3], 'y'); % 縦軸のスケールを揃える

%% Figure 2: 高さ方向誤差のヒストグラム (符号付き)
figure('Name', 'Figure 2: 高さ方向誤差 ヒストグラム', 'Position', [150, 150, 1200, 400]);
% 符号付き誤差をプロットするため、X軸はプラスマイナス両方向に広げます
max_dz = max(abs([dz_5min(:); dz_20min(:); dz_60min(:)]));
z_lim = [-ceil(max_dz) - 2, ceil(max_dz) + 2];

% 高さ方向は誤差が広範囲に散らばるため、ビン幅（棒の太さ）を2.0 mmに広げて見やすくします
bin_width_z = 2.0; 

% 5分間
az1 = subplot(1, 3, 1);
histogram(dz_5min, 'BinWidth', bin_width_z, 'Normalization', 'probability', 'FaceColor', [0 0.4470 0.7410], 'EdgeColor', 'k');
title('高さ方向誤差 (5分間)'); xlabel('誤差 (mm)'); ylabel('相対度数'); xlim(z_lim); grid on;
text(0.05, 0.9, sprintf('平均絶対誤差: %.2f mm\n標準偏差: %.2f mm', mean(abs(dz_5min)), std(dz_5min)), 'Units', 'normalized', 'BackgroundColor', 'w');

% 20分間
az2 = subplot(1, 3, 2);
histogram(dz_20min, 'BinWidth', bin_width_z, 'Normalization', 'probability', 'FaceColor', [0.8500 0.3250 0.0980], 'EdgeColor', 'k');
title('高さ方向誤差 (20分間)'); xlabel('誤差 (mm)'); ylabel('相対度数'); xlim(z_lim); grid on;
text(0.05, 0.9, sprintf('平均絶対誤差: %.2f mm\n標準偏差: %.2f mm', mean(abs(dz_20min)), std(dz_20min)), 'Units', 'normalized', 'BackgroundColor', 'w');

% 60分間
az3 = subplot(1, 3, 3);
histogram(dz_60min, 'BinWidth', bin_width_z, 'Normalization', 'probability', 'FaceColor', [0.9290 0.6940 0.1250], 'EdgeColor', 'k');
title('高さ方向誤差 (60分間)'); xlabel('誤差 (mm)'); ylabel('相対度数'); xlim(z_lim); grid on;
text(0.05, 0.9, sprintf('平均絶対誤差: %.2f mm\n標準偏差: %.2f mm', mean(abs(dz_60min)), std(dz_60min)), 'Units', 'normalized', 'BackgroundColor', 'w');

linkaxes([az1, az2, az3], 'y'); % 縦軸のスケールを揃える

%% 3. 画像の自動保存 (PNG と PDF)
% 保存先を、読み込んだmatデータと同じフォルダに指定します
[mat_dir, ~, ~] = fileparts(mat_file);

% VS Codeですぐに見るためのプレビュー用 (PNG)
fig1_png = fullfile(mat_dir, 'hist_horizontal.png');
fig2_png = fullfile(mat_dir, 'hist_height.png');

% 論文やレポート用のベクター画像 (PDF)
fig1_pdf = fullfile(mat_dir, 'hist_horizontal.pdf');
fig2_pdf = fullfile(mat_dir, 'hist_height.pdf');

% 最新のMATLAB(R2020a以降)であれば exportgraphics で綺麗に保存できます
try
    exportgraphics(figure(1), fig1_png, 'Resolution', 300);
    exportgraphics(figure(2), fig2_png, 'Resolution', 300);
    exportgraphics(figure(1), fig1_pdf, 'ContentType', 'vector');
    exportgraphics(figure(2), fig2_pdf, 'ContentType', 'vector');
catch
    % 古いバージョンのMATLAB用の代替処理
    saveas(figure(1), fig1_png);
    saveas(figure(2), fig2_png);
    saveas(figure(1), fig1_pdf);
    saveas(figure(2), fig2_pdf);
end
fprintf('画像を保存しました:\n - プレビュー用: .png\n - レポート用: .pdf\n');
