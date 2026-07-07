#!/usr/bin/env python3
"""
=============================================================
  Tool Labeling EKG Interaktif untuk Tugas Akhir
=============================================================

Cara pakai:
  1. Jalankan dari terminal:  python3 labeling_tool.py
  2. Akan muncul plot sinyal EKG per window (10 detik)
  3. Klik tombol [Normal] atau [AFib] atau [Tidak Terdeteksi] untuk memberi label
  4. Klik [Skip] jika sinyal tidak jelas / noisy
  5. Klik [Kembali] untuk koreksi label sebelumnya
  6. Progress otomatis tersimpan ke CSV — bisa dilanjutkan kapan saja

Hasil tersimpan di: labels_primer.csv
"""

import os
import glob
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('TkAgg')  # Backend interaktif untuk macOS
import matplotlib.pyplot as plt
from matplotlib.widgets import Button
from scipy.signal import butter, filtfilt
import pywt

# ============ KONFIGURASI ============
FS = 250
WINDOW_SECONDS = 10
WINDOW_SIZE = FS * WINDOW_SECONDS  # 2500 sampel

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIRS = [os.path.join(PROJECT_DIR, "Data Wearable EKG-Nano (Berhasil)")]
LABEL_CSV = os.path.join(PROJECT_DIR, "dataekglabel_nano_berhasil.csv")

# ============ PREPROCESSING ============
def bandpass_filter(signal_data, lowcut=0.5, highcut=40, fs=FS, order=3):
    nyquist = 0.5 * fs
    low = lowcut / nyquist
    high = highcut / nyquist
    b, a = butter(order, [low, high], btype='band')
    return filtfilt(b, a, signal_data)

def denoise(signal_data, wavelet='db5', level=5):
    coeffs = pywt.wavedec(signal_data, wavelet=wavelet, level=level)
    coeffs[0] = np.zeros_like(coeffs[0])
    detail_highest = coeffs[-1]
    sigma = np.median(np.abs(detail_highest)) / 0.6745
    n = len(signal_data)
    universal_threshold = sigma * np.sqrt(2 * np.log(n))
    for i in range(1, len(coeffs)):
        coeffs[i] = pywt.threshold(coeffs[i], value=universal_threshold, mode='soft')
    reconstructed = pywt.waverec(coeffs, wavelet=wavelet)
    return reconstructed[:len(signal_data)]

def preprocess_window(window):
    filtered = bandpass_filter(window)
    denoised = denoise(filtered)
    return denoised

# ============ LOAD & SEGMENT DATA ============
def load_all_windows():
    """Load semua file CSV dan potong jadi window 10 detik."""
    all_windows = []
    
    for data_dir in DATA_DIRS:
        if not os.path.exists(data_dir):
            continue
        csv_files = sorted(glob.glob(os.path.join(data_dir, "*.csv")))
        
        for csv_path in csv_files:
            filename = os.path.basename(csv_path)
            if filename == ".DS_Store":
                continue
            
            try:
                df = pd.read_csv(csv_path)
                # Kolom voltage ada di index 2
                ekg = df.iloc[:, 2].dropna().values
            except Exception as e:
                print(f"  [SKIP] Error baca {filename}: {e}")
                continue
            
            # Potong jadi window 10 detik
            n_windows = len(ekg) // WINDOW_SIZE
            for w in range(n_windows):
                start = w * WINDOW_SIZE
                end = start + WINDOW_SIZE
                segment = ekg[start:end]
                
                window_id = f"{filename}|w{w+1}"
                all_windows.append({
                    'window_id': window_id,
                    'filename': filename,
                    'window_num': w + 1,
                    'signal': segment
                })
    
    return all_windows

# ============ LOAD/SAVE PROGRESS ============
def load_existing_labels():
    """Load label yang sudah ada (untuk melanjutkan sesi sebelumnya)."""
    if os.path.exists(LABEL_CSV):
        df = pd.read_csv(LABEL_CSV)
        return dict(zip(df['window_id'], df['label']))
    return {}

def save_labels(labels_dict):
    """Simpan semua label ke CSV."""
    rows = []
    for window_id, label in labels_dict.items():
        parts = window_id.split('|')
        filename = parts[0]
        window_num = parts[1].replace('w', '')
        rows.append({
            'window_id': window_id,
            'filename': filename,
            'window_num': int(window_num),
            'label': label,
            'label_text': {0: 'Normal', 1: 'AFib', -1: 'Skip', -2: 'Tidak Terdeteksi'}.get(label, 'Unknown')
        })
    
    df = pd.DataFrame(rows)
    df = df.sort_values(['filename', 'window_num'])
    df.to_csv(LABEL_CSV, index=False)

# ============ INTERACTIVE LABELING ============
class LabelingTool:
    def __init__(self, windows, existing_labels):
        self.windows = windows
        self.labels = existing_labels.copy()
        self.current_idx = 0
        
        # Cari window pertama yang belum dilabeli
        for i, w in enumerate(windows):
            if w['window_id'] not in self.labels:
                self.current_idx = i
                break
        else:
            # Semua sudah dilabeli, mulai dari awal
            self.current_idx = 0
        
        self.fig = None
        self.ax_signal = None
        self.result = None
    
    def count_labels(self):
        n_normal = sum(1 for v in self.labels.values() if v == 0)
        n_afib = sum(1 for v in self.labels.values() if v == 1)
        n_skip = sum(1 for v in self.labels.values() if v == -1)
        n_nodet = sum(1 for v in self.labels.values() if v == -2)
        return n_normal, n_afib, n_skip, n_nodet
    
    def show_window(self, idx):
        """Tampilkan satu window dan tunggu input user."""
        if idx < 0 or idx >= len(self.windows):
            return None
        
        w = self.windows[idx]
        signal = w['signal']
        
        # Preprocess untuk tampilan
        try:
            processed = preprocess_window(signal)
        except Exception:
            processed = signal
        
        time_axis = np.arange(len(processed)) / FS
        
        # Buat figure
        self.fig = plt.figure(figsize=(16, 7))
        
        # Plot area
        self.ax_signal = self.fig.add_axes([0.06, 0.25, 0.88, 0.65])
        self.ax_signal.plot(time_axis, processed, color='#1a73e8', linewidth=0.8)
        self.ax_signal.set_xlabel('Waktu (detik)', fontsize=11)
        self.ax_signal.set_ylabel('Amplitudo', fontsize=11)
        self.ax_signal.grid(True, alpha=0.3)
        self.ax_signal.set_xlim(0, WINDOW_SECONDS)
        
        # Status info
        n_normal, n_afib, n_skip, n_nodet = self.count_labels()
        existing = self.labels.get(w['window_id'], None)
        existing_text = {0: '→ Normal', 1: '→ AFib', -1: '→ Skip', -2: '→ Tidak Terdeteksi'}.get(existing, '→ Belum')
        
        title = (
            f"File: {w['filename']}  |  Window: {w['window_num']}  |  "
            f"Progress: {idx+1}/{len(self.windows)}  |  "
            f"Label saat ini: {existing_text}\n"
            f"Total terlabeli: {len(self.labels)} "
            f"(Normal: {n_normal}, AFib: {n_afib}, Skip: {n_skip}, Tidak Terdeteksi: {n_nodet})"
        )
        self.ax_signal.set_title(title, fontsize=11, fontweight='bold')
        
        # Tombol-tombol
        self.result = None
        
        ax_normal = self.fig.add_axes([0.05, 0.05, 0.14, 0.07])
        ax_afib = self.fig.add_axes([0.22, 0.05, 0.14, 0.07])
        ax_nodet = self.fig.add_axes([0.39, 0.05, 0.18, 0.07])
        ax_skip = self.fig.add_axes([0.60, 0.05, 0.14, 0.07])
        ax_back = self.fig.add_axes([0.77, 0.05, 0.14, 0.07])
        
        btn_normal = Button(ax_normal, '✓ Normal', color='#4caf50', hovercolor='#66bb6a')
        btn_afib = Button(ax_afib, '⚡ AFib', color='#f44336', hovercolor='#ef5350')
        btn_nodet = Button(ax_nodet, '✗ Tdk Terdeteksi', color='#7b1fa2', hovercolor='#9c27b0')
        btn_skip = Button(ax_skip, '⏭ Skip', color='#9e9e9e', hovercolor='#bdbdbd')
        btn_back = Button(ax_back, '← Kembali', color='#ff9800', hovercolor='#ffa726')
        
        for btn in [btn_normal, btn_afib, btn_nodet, btn_skip, btn_back]:
            btn.label.set_fontsize(11)
            btn.label.set_fontweight('bold')
        
        def on_normal(event):
            self.result = 0
            plt.close(self.fig)
        
        def on_afib(event):
            self.result = 1
            plt.close(self.fig)
        
        def on_nodet(event):
            self.result = -2
            plt.close(self.fig)
        
        def on_skip(event):
            self.result = -1
            plt.close(self.fig)
        
        def on_back(event):
            self.result = 'back'
            plt.close(self.fig)
        
        btn_normal.on_clicked(on_normal)
        btn_afib.on_clicked(on_afib)
        btn_nodet.on_clicked(on_nodet)
        btn_skip.on_clicked(on_skip)
        btn_back.on_clicked(on_back)
        
        # Keyboard shortcuts
        def on_key(event):
            if event.key == 'n' or event.key == '0':
                on_normal(event)
            elif event.key == 'a' or event.key == '1':
                on_afib(event)
            elif event.key == 'x' or event.key == '2':
                on_nodet(event)
            elif event.key == 's':
                on_skip(event)
            elif event.key == 'b' or event.key == 'backspace':
                on_back(event)
            elif event.key == 'q' or event.key == 'escape':
                self.result = 'quit'
                plt.close(self.fig)
        
        self.fig.canvas.mpl_connect('key_press_event', on_key)
        
        plt.show()
        return self.result
    
    def run(self):
        """Jalankan labeling loop."""
        print("\n" + "="*60)
        print("  LABELING EKG  ")
        print("="*60)
        print(f"  Total window  : {len(self.windows)}")
        print(f"  Sudah dilabeli: {len(self.labels)}")
        print(f"  Mulai dari    : Window ke-{self.current_idx + 1}")
        print()
        print("  Shortcut keyboard:")
        print("    [N] atau [0] = Normal")
        print("    [A] atau [1] = AFib")
        print("    [X] atau [2] = Sinyal Tidak Terdeteksi")
        print("    [S]          = Skip")
        print("    [B]          = Kembali ke sebelumnya")
        print("    [Q] atau [Esc] = Simpan & Keluar")
        print("="*60 + "\n")
        
        idx = self.current_idx
        
        while 0 <= idx < len(self.windows):
            w = self.windows[idx]
            result = self.show_window(idx)
            
            if result == 'quit' or result is None:
                break
            elif result == 'back':
                idx = max(0, idx - 1)
                continue
            elif result in [0, 1, -1, -2]:
                self.labels[w['window_id']] = result
                label_text = {0: 'Normal', 1: 'AFib', -1: 'Skip', -2: 'Tidak Terdeteksi'}[result]
                print(f"  [{idx+1}/{len(self.windows)}] {w['window_id']} → {label_text}")
                
                # Auto-save setiap 5 label
                if len(self.labels) % 5 == 0:
                    save_labels(self.labels)
                
                idx += 1
        
        # Final save
        save_labels(self.labels)
        n_normal, n_afib, n_skip, n_nodet = self.count_labels()
        print(f"\n{'='*60}")
        print(f"  SELESAI! Hasil tersimpan di: {LABEL_CSV}")
        print(f"  Total: {len(self.labels)} label")
        print(f"    Normal           : {n_normal}")
        print(f"    AFib             : {n_afib}")
        print(f"    Tidak Terdeteksi : {n_nodet}")
        print(f"    Skip             : {n_skip}")
        print(f"{'='*60}\n")

# ============ MAIN ============
if __name__ == '__main__':
    print("Memuat data EKG...")
    windows = load_all_windows()
    print(f"  Ditemukan {len(windows)} window dari {len(set(w['filename'] for w in windows))} file\n")
    
    if len(windows) == 0:
        print("[ERROR] Tidak ada data ditemukan!")
        exit(1)
    
    existing = load_existing_labels()
    if existing:
        print(f"  Melanjutkan sesi sebelumnya: {len(existing)} label sudah ada\n")
    
    tool = LabelingTool(windows, existing)
    tool.run()
