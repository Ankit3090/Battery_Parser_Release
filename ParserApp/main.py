import pandas as pd
import numpy as np
import sys
import math
import os
import cantools
import re
from datetime import datetime, timedelta
import glob
import tkinter as tk
from tkinter import filedialog
import warnings
import requests
import subprocess
import time

# =============================================================================
# --- 0. TERMINAL CLEANUP (Professional Output) ---
# =============================================================================
warnings.simplefilter(action='ignore', category=pd.errors.PerformanceWarning)
warnings.simplefilter(action='ignore', category=FutureWarning)
warnings.simplefilter(action='ignore', category=UserWarning)
warnings.filterwarnings("ignore", message=".*The copy keyword is deprecated.*")

# --- 1. CONFIGURATION ---
# Increment this when you are ready to publish a new version on GitHub
CURRENT_VERSION = "v1.7" 
# Format: "YourGitHubUsername/YourRepoName" (e.g., "ankit-negi/telemetry-parser")
REPO = "Ankit023090/Battery_Parser_Release" 

# --- 2. AUTO-UPDATER FUNCTIONS ---
def check_for_updates():
    print("Checking for updates...")
    try:
        response = requests.get(f"https://api.github.com/repos/{REPO}/releases/latest", timeout=5)
        
        # If no internet or no releases yet, just skip and launch the app normally
        if response.status_code != 200:
            print("No updates found or unable to connect.")
            return
            
        latest_release = response.json()
        latest_version = latest_release.get("tag_name", "")

        if latest_version and latest_version != CURRENT_VERSION:
            print(f"New update found: {latest_version}. Downloading in the background...")
            
            for asset in latest_release.get("assets", []):
                if asset["name"].endswith(".exe"):
                    download_url = asset["browser_download_url"]
                    download_update(download_url)
                    break
    except Exception as e:
        print(f"Update check failed: {e}. Launching current version.")

def download_update(url):
    try:
        response = requests.get(url, stream=True, timeout=10)
        new_exe_name = "parser_update_temp.exe"
        
        with open(new_exe_name, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
                
        apply_update(new_exe_name)
    except Exception as e:
        print(f"Failed to download update: {e}")

def apply_update(new_exe_path):
    current_exe = sys.executable  
    bat_path = "updater.bat"
    
    # This batch script waits 2 seconds, deletes the old EXE, renames the new one, and restarts it.
    bat_script = f"""@echo off
timeout /t 2 /nobreak > NUL
del "{current_exe}"
ren "{new_exe_path}" "{os.path.basename(current_exe)}"
start "" "{current_exe}"
del "%~f0"
"""
    with open(bat_path, "w") as f:
        f.write(bat_script)
        
    # Execute the batch script in a new background process
    subprocess.Popen([bat_path], shell=True)
    # Immediately exit this Python script so Windows releases the file lock on the EXE
    sys.exit(0)


# --- 3. YOUR MAIN APPLICATION LOGIC ---
def launch_telemetry_dashboard():
    """
    This is where your actual application lives. 
    Put your GUI initialization, drive cycle telemetry processing, 
    and CSV log parsing in here.
    """
    print(f"--- High-Performance Data Visualization Dashboard ({CURRENT_VERSION}) ---")
    print("Loading drive cycle telemetry...")
    # Your custom GUI code goes here...


# --- 4. EXECUTION SEQUENCE ---
if __name__ == "__main__":
    # getattr(sys, 'frozen', False) checks if we are running as a compiled .exe
    # We only want to trigger the updater if it's the actual .exe, not while you are testing raw Python code
    if getattr(sys, 'frozen', False): 
        check_for_updates()
        
    # If no updates were found (or if the update check finished), launch the main app
    launch_telemetry_dashboard()


# =============================================================================
# --- 1. GUI FILE SELECTION HELPERS (Unified using tkinter) ---
# =============================================================================
def get_root():
    """Create or get the main hidden tkinter root to prevent multiple window spawns."""
    root = tk.Tk()
    root.withdraw()
    return root

def select_trc_files(root):
    files = filedialog.askopenfilenames(
        parent=root, title="Select TRC Files", filetypes=[("TRC Files", "*.trc")]
    )
    return root.tk.splitlist(files) if files else []

def select_dbc_file(root):
    return filedialog.askopenfilename(
        parent=root, title="Select DBC File", filetypes=[("DBC Files", "*.dbc")]
    )

# =============================================================================
# --- 2. PARSER FUNCTIONS ---
# =============================================================================
def extract_headers(lines):
    file_version = None
    col_map = {}
    start_time_str = None
    
    for line in lines:
        l = line.strip()
        if l.startswith(';$FILEVERSION='):
            file_version = l.split('=')[1]
        elif l.startswith(';$COLUMNS='):
            cols = l.split('=')[1].split(',')
            for i, c in enumerate(cols):
                col_map[c] = i
        elif l.startswith(';   Start time:'):
            start_time_str = l.split(':', 1)[1].strip()
            
        if l.startswith(';---') or (l and not l.startswith(';') and re.match(r'^\d', l)):
            break
            
    return file_version, col_map, start_time_str

def alignment(src, reference_length):
    n = len(src)
    target = reference_length
    if n == 0:
        src.extend([None] * target)
        return
    if n >= target:
        step = n / target
        new_variable = [src[int(i * step)] for i in range(target)]
        src.clear()
        src.extend(new_variable)
        return
        
    inserts_needed = target - n
    gap = n / inserts_needed 
    block = inserts_needed / n
    new_variable = []
    if gap <= 1:
        y = round(block) + 1
        for i in range(0,n,1):
            new_variable.extend([src[i]]*y)
        src.clear()
        src.extend(new_variable)
        new_variable.clear()
    pos = 0.0
    inserted = 0
    for i, val in enumerate(src):
        new_variable.append(val)
        while inserted < inserts_needed and pos <= i:
            new_variable.append(val)
            inserted += 1
            pos += gap      
    src.clear()
    src.extend(new_variable)

def extract_number(fname):
    match = re.search(r'(\d+)(?!.*\d)', fname) 
    return int(match.group(1)) if match else 0

def decode_trc_file(trc_path, dbc, dbc_signal_order):
    with open(trc_path, 'r', errors='ignore') as f:
        lines = f.readlines()

    print(f"\n--- Processing: {os.path.basename(trc_path)} ---")
    
    file_version, col_map, start_time_str = extract_headers(lines)
    
    start_time = datetime.now()
    if start_time_str:
        formats_to_try = [
            "%d-%m-%Y %H:%M:%S.%f", "%d-%m-%Y %H:%M:%S.%f.0",
            "%m/%d/%Y %H:%M:%S.%f", "%m/%d/%Y %H:%M:%S.%f.0",
            "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S.%f.0",
            "%d/%m/%Y %H:%M:%S.%f", "%d/%m/%Y %H:%M:%S.%f.0"
        ]
        for fmt in formats_to_try:
            try:
                start_time = datetime.strptime(start_time_str, fmt)
                break
            except ValueError:
                continue

    if not col_map:
        if file_version and file_version.startswith('1.'):
            col_map = {'O': 1, 'd': 2, 'I': 3, 'l': 4, 'D': 5}
        else:
            col_map = {'O': 1, 'T': 2, 'B': 3, 'I': 4, 'd': 5, 'r': 6, 'l': 7, 'D': 8}

    idx_O = col_map.get('O')
    idx_I = col_map.get('I')
    idx_d = col_map.get('d')
    idx_l = col_map.get('l', col_map.get('L'))
    idx_D = col_map.get('D')

    if None in [idx_O, idx_I, idx_d, idx_l, idx_D]:
        print("  -> CRITICAL ERROR: Unable to map columns from TRC header.")
        return 0.0, 0.0, 0.0, 0.0

    signal_store = {sig.name: [] for msg in dbc.messages for sig in msg.signals}
    timestamp_store = {sig.name: [] for msg in dbc.messages for sig in msg.signals}
            
    flag_start_time = 0
    start_time_ms = 0
    time_offset_ms = 0

    stats_total_lines = 0
    stats_matched_ids = 0
    stats_decoded = 0
    debug_errors = []
    
    for line in lines:
        line = line.strip()
        if not line or line.startswith(';') or line.startswith('---'): continue
        if not re.match(r'^\d', line): continue

        stats_total_lines += 1
        parts = re.split(r'\s+', line)

        try:
            if len(parts) <= idx_d: continue
            if parts[idx_d].lower() not in ['rx', 'tx']: continue

            time_offset_ms = float(parts[idx_O])
            can_id = int(parts[idx_I].replace('x', '').replace('X', ''), 16)
            dlc = int(parts[idx_l])
            
            actual_dlc = min(dlc, len(parts) - idx_D)
            if actual_dlc <= 0: continue
            
            data_hex = parts[idx_D : idx_D + actual_dlc]
            data = bytes(int(b, 16) for b in data_hex)

            if flag_start_time == 0:
                start_time_ms = time_offset_ms
                flag_start_time = 1
            
            msg = None
            possible_ids = [
                can_id,
                can_id & 0x1FFFFFFF,                 
                can_id & 0x7FF,                      
                can_id | 0x80000000,                 
                (can_id & 0x1FFFFFFF) | 0x80000000   
            ]
            
            for pid in possible_ids:
                try:
                    msg = dbc.get_message_by_frame_id(pid)
                    break
                except KeyError:
                    pass
            
            if not msg: continue
            stats_matched_ids += 1
            
            try:
                decoded = msg.decode(data, decode_choices=False)
            except Exception:
                try:
                    if msg.length > len(data):
                        padded = data + b'\x00' * (msg.length - len(data))
                        decoded = msg.decode(padded, decode_choices=False)
                    elif msg.length < len(data):
                        truncated = data[:msg.length]
                        decoded = msg.decode(truncated, decode_choices=False)
                    else: continue
                except Exception: continue

            stats_decoded += 1

            for name, value in decoded.items():
                if name in signal_store:
                    timestamp_store[name].append(time_offset_ms)
                    if isinstance(value, (int, float)) and not math.isnan(value):
                        name_lower = name.lower()
                        if 'marvel' in name_lower or 'stark' in name_lower or name_lower.endswith('_fw') or 'manifest' in name_lower:
                            val_int = int(value)
                            hex_str = f"{val_int:06X}"
                            signal_store[name].append(f"{hex_str[0:2]}.{hex_str[2:4]}.{hex_str[4:6]}")
                        elif 'config' in name_lower and ('id' in name_lower or 'version' in name_lower):
                            signal_store[name].append(f"{int(value):X}")
                        elif msg.frame_id == 0x706 and ('gear' in name_lower or 'mode' in name_lower) and 'mcu' not in name_lower:
                            gear_map = {1: "Neutral", 2: "ECO", 4: "Reverse", 8: "Thunder"}
                            signal_store[name].append(gear_map.get(int(value), f"Unknown Mode: {int(value)}"))
                        
                        elif 'mcu_gear' in name_lower:
                            if len(data) >= 8:
                                raw_gear_val = data[7] & 0x0F 
                            else:
                                raw_gear_val = int(value) 
                                
                            gear_map = {0: "Neutral", 1: "Thunder", 2: "Reverse", 3: "Eco", 4: "Rhino"}
                            signal_store[name].append(gear_map.get(raw_gear_val, "Z"))

                        elif msg.frame_id == 0x0C0AA7F0 and 'shutdown' in name_lower:
                            shutdown_map = {0: "No Request", 1: "Shutdown Requested"}
                            signal_store[name].append(shutdown_map.get(int(value), f"Unknown State: {int(value)}"))
                        else:
                            signal_store[name].append(value)
                    else:
                        signal_store[name].append(value)
        except Exception as e:
            if len(debug_errors) < 5:
                debug_errors.append(f"Row Error: {e} -> on line: {line}")
            continue

    print(f"  -> Valid CAN Rows Found: {stats_total_lines}")
    print(f"  -> Rows Matched to DBC:  {stats_matched_ids}")
    print(f"  -> Rows Fully Decoded:   {stats_decoded}")

    if stats_decoded == 0:
        print("\n[CRITICAL ERROR] Failed to decode any rows.")
        return 0.0, 0.0, 0.0, 0.0
            
    # --- EXACT CAPACITY & ENERGY INTEGRATION ---
    curr_col = next((k for k in signal_store.keys() if 'Pack_Current' in k), None)
    volt_col = next((k for k in signal_store.keys() if 'Pack_Voltage' in k), None)

    final_pos_ah, final_neg_ah, final_drive_wh, final_regen_wh = 0.0, 0.0, 0.0, 0.0

    if curr_col and volt_col:
        cur_times = timestamp_store[curr_col]
        cur_vals = signal_store[curr_col]
        vol_times = timestamp_store[volt_col]
        vol_vals = signal_store[volt_col]

        cum_pos_ah, cum_neg_ah, cum_drive_wh, cum_regen_wh = 0.0, 0.0, 0.0, 0.0
        v_idx = 0
        last_v = 0.0
        
        if vol_vals:
            for v in vol_vals:
                try:
                    temp = float(v)
                    if not math.isnan(temp):
                        last_v = temp
                        break
                except: continue

        if cur_times and cur_vals:
            for i in range(1, len(cur_times)):
                t0, t1 = cur_times[i-1] / 1000.0, cur_times[i] / 1000.0
                try: 
                    I0 = float(cur_vals[i-1])
                    if math.isnan(I0): I0 = 0.0
                except: I0 = 0.0

                dt = t1 - t0
                if dt <= 0 or dt > 0.5: dt = 0.3

                while v_idx < len(vol_times) and (vol_times[v_idx]/1000.0) <= t1:
                    try: 
                        temp_v = float(vol_vals[v_idx])
                        if not math.isnan(temp_v) and temp_v > 0: last_v = temp_v
                    except: pass
                    v_idx += 1

                if I0 >= 0:
                    cum_pos_ah += (I0 * dt) / 3600.0
                    cum_regen_wh += (I0 * last_v * dt) / 3600.0
                else:
                    cum_neg_ah += (I0 * dt) / 3600.0
                    cum_drive_wh += (abs(I0) * last_v * dt) / 3600.0

            final_pos_ah, final_neg_ah, final_drive_wh, final_regen_wh = cum_pos_ah, cum_neg_ah, cum_drive_wh, cum_regen_wh
    
    difference_time_ms = time_offset_ms - start_time_ms
    
    # 1. Calculate the exact, true number of 100ms rows needed
    expected_samples = math.ceil(difference_time_ms / 100.0) + 1
    if expected_samples <= 0: expected_samples = 1

    # 2. Create a perfect 100ms grid (FORCE TO FLOAT)
    time_grid = np.arange(0, expected_samples * 100, 100, dtype=float)
    df = pd.DataFrame({'Time_ms': time_grid})
    
    # 3. Slot every single CAN message into its exact temporal bucket
    for sig_name in dbc_signal_order:
        if sig_name in signal_store and len(signal_store[sig_name]) > 0:
            temp_df = pd.DataFrame({
                'Time_ms': (np.array(timestamp_store[sig_name]) - start_time_ms).astype(float),
                sig_name: signal_store[sig_name]
            })
            
            # Clean up raw signal data so it can be merged safely
            temp_df = temp_df.dropna(subset=['Time_ms'])
            temp_df = temp_df.sort_values('Time_ms')
            # If multiple frames arrived in the exact same millisecond, keep the most recent one
            temp_df = temp_df.drop_duplicates(subset=['Time_ms'], keep='last')
            
            # merge_asof perfectly slots the most recent CAN frame into the 100ms grid
            df = pd.merge_asof(df, temp_df, on='Time_ms', direction='backward')
        else:
            # If the DBC has a signal but it never fired in this TRC, fill it with blanks
            df[sig_name] = np.nan

    df = df.drop(columns=['Time_ms'])
    
    reference_length = expected_samples

    
    cols_to_drop = ['hour', 'minute', 'second', 'date', 'month', 'year', 'day']
    df = df.drop(columns=[col for col in cols_to_drop if col in df.columns], errors='ignore')
    
    date_array, time_array = [], []
    for i in range(reference_length):
        dt = start_time + timedelta(milliseconds=(start_time_ms + i * 100))
        date_array.append('="' + dt.strftime("%d-%m-%Y") + '"')
        time_array.append('="' + dt.strftime("%H:%M:%S.%f")[:-3] + '"')
    
    if reference_length > 0:
        df.insert(0, 'Date', date_array)
        df.insert(1, 'Time', time_array)
    
    df = df.replace("", np.nan)
    df = df.bfill().fillna(0)
    df = df.infer_objects()
    df = df.copy()
    
    output_csv = trc_path.replace(".trc", "_pcan.csv")
    df.to_csv(output_csv, index=False)
    
    return final_pos_ah, final_neg_ah, final_drive_wh, final_regen_wh

# =============================================================================
# --- 3. SUMMARIZER LOGIC ---
# =============================================================================
def generate_summary(df, target_dir):
    print("\n--- Starting Summary Generation ---")
    
    # --- FIXED SCOPE: Initialize safe metrics defaults ---
    initial_soc_val = "N/A"
    final_soc_val = "N/A"
    start_capacity_ah_val = "N/A"
    end_capacity_ah_val = "N/A"
    start_energy_wh_val = "N/A"
    end_energy_wh_val = "N/A"
    est_full_pack_ah_val = "N/A"
    est_full_pack_wh_val = "N/A"
    start_odo_val = "N/A"
    end_odo_val = "N/A"
    total_range_km = 0.0
    range_below_0_val = 0.0
    range_till_10_val = "N/A"
    max_soc_jump_val = "None"
    max_soc_drop_val = "None"
    dominant_mode_val = "N/A"
    
    # --- CONFIGURATION (Column Names) ---
    current_col        = 'Pack_Current' 
    voltage_col        = 'Pack_Voltage' 
    soc_col            = 'SoC'          
    bms_soc_col        = 'SoC'      
    
    if 'Odometer' in df.columns: odo_col = 'Odometer'
    elif 'Vehicle_range' in df.columns: odo_col = 'Vehicle_range'
    else: odo_col = 'Odometer' 
        
    cell_vmax_col      = 'Voltage_Max'
    cell_vmin_col      = 'Voltage_Min'
    imbalance_col      = 'Voltage_Delta'
    temp_max_col       = 'Ext_Temp_Max'
    temp_min_col       = 'Ext_Temp_Min'
    temp_delta_col     = 'Ext_Temp_Delta'
    bms_state_col      = 'BMS_State'    
    precharge_fail_col = 'PRECHARGE_FAIL'
    gear_mode_col      = 'Gear_Mode'    
    vcu_cmd_col        = 'Shutdown_command'       
    bms_ack_col        = 'Shutdown_ack_flag'  
    efuse_col          = 'EFUSE_DISCHG_ERROR' 
    
    date_col           = 'Date'
    time_col           = 'Time'
    pcb_temp_min_col   = 'Int_Temp_Min'
    pcb_temp_max_col   = 'Int_Temp_Max'
    pcb_temp_delta_col = 'Int_Temp_Delta'
    cycle_count_col    = 'BMS_cycleCount'
    mcu_count_col      = 'mcu_counter'
    aux_voltage_col    = 'Aux_voltage'
    stark_fw_col       = 'Stark_FW_in_HEX'
    marvel_fw_col      = 'Marvel_FW_in_HEX'
    gitsha_col         = 'gitsha'
    config_col         = 'ConfigID_in_HEX'
    flag_full_chg_col  = 'Flag_Fully_Charged'
    flag_balance_col   = 'Flag_Balancing_Active'
    vehicle_state_col  = 'Vehicle_state'
    manifest_col       = 'Manifest' 

    error_columns_to_check = [
        'OCC_ERROR', 'HIGH_IMBALANCE_ERROR', 'PCB_TEMP_ERROR', 'EXT_TEMP_ERROR', 
        'EFUSE_DISCHG_ERROR', 'EFUSE_CHG_ERROR', 'UV_ERROR', 'OV_ERROR', 'OCD_ERROR', 
        'FLASH_WRITE_FAIL', 'EEPROM_WRITE_FAIL', 'EEPROM_READ_FAIL', 'PERMANENT_FAIL', 
        'PRECHARGE_FAIL', 'EEPROM_CORRUPTED', 'EEPROM_COMM_FAIL', 'StartupSanityFail', 
        'THERMAL_RUNAWAY', 'SCD_ERROR', 'EEPROM_SHADOW_WRITE_FAIL', 'EEPROM_META_WRITE_FAIL', 
        'EEPROM_SHADOW_READ_FAIL', 'EEPROM_META_READ_FAIL', 'CCM_FAIL', 'CMU_FAIL', 
        'HardFaultPresent', 'Config_Update_warning', 'Isolation_warning', 'Isolation_Failure',
        'contactorCommandMissing', 'SD_Power_off_Pending', 'History_ActiveErrorGroup1', 'History_ActiveErrorGroup2'
    ]

    true_empty_mv_threshold = 3100.0 
    
    if current_col not in df.columns or voltage_col not in df.columns:
        print(f"\nERROR: Essential columns ('{current_col}' or '{voltage_col}') not found! Skipping summary.")
        return

    # --- CAPACITY & ENERGY ---
    total_capacity_ah = 0.0
    regen_capacity_ah = 0.0
    battery_capacity_ah = 0.0
    drive_energy_wh = 0.0
    regen_energy_wh = 0.0
    consumed_energy_wh = 0.0

    if not df.empty:
        if 'Total_Neg_Ah' in df.columns and pd.notna(df.loc[0, 'Total_Neg_Ah']):
            total_capacity_ah = abs(float(df.loc[0, 'Total_Neg_Ah']))
        if 'Total_Pos_Ah' in df.columns and pd.notna(df.loc[0, 'Total_Pos_Ah']):
            regen_capacity_ah = float(df.loc[0, 'Total_Pos_Ah'])
            
        battery_capacity_ah = total_capacity_ah - regen_capacity_ah

        if 'Total_Drive_Wh' in df.columns and pd.notna(df.loc[0, 'Total_Drive_Wh']):
            drive_energy_wh = abs(float(df.loc[0, 'Total_Drive_Wh']))
        if 'Total_Regen_Wh' in df.columns and pd.notna(df.loc[0, 'Total_Regen_Wh']):
            regen_energy_wh = float(df.loc[0, 'Total_Regen_Wh'])
            
        consumed_energy_wh = drive_energy_wh - regen_energy_wh

    # --- DATE / TIME / D vs N LOGIC ---
    date_val = ""
    if date_col in df.columns and not df.empty:
        base_date = str(df[date_col].iloc[0]).replace('="', '').replace('"', '').strip()
        if time_col in df.columns:
            first_time = str(df[time_col].iloc[0]).replace('="', '').replace('"', '').strip()
            try:
                hour = pd.to_datetime(first_time).hour
                if 8 <= hour < 18:
                    date_val = f"{base_date}D"
                elif hour >= 19 or hour < 6:
                    date_val = f"{base_date}N"
                else:
                    date_val = base_date 
            except Exception:
                date_val = base_date 
        else:
            date_val = base_date

    # --- FW & VERSIONS ---
    stark_fw_val = str(df[stark_fw_col].dropna().iloc[0]) if stark_fw_col in df.columns and not df[stark_fw_col].dropna().empty else ""
    marvel_fw_val = str(df[marvel_fw_col].dropna().iloc[0]) if marvel_fw_col in df.columns and not df[marvel_fw_col].dropna().empty else ""
    config_val = str(df[config_col].dropna().iloc[0]) if config_col in df.columns and not df[config_col].dropna().empty else ""
    gitsha_val = str(df[gitsha_col].dropna().iloc[0]).replace('.0', '') if gitsha_col in df.columns and not df[gitsha_col].dropna().empty else ""
    manifest_val = str(df[manifest_col].dropna().iloc[0]) if manifest_col in df.columns and not df[manifest_col].dropna().empty else ""

    # ==========================================
    # --- CYCLE & MCU COUNTERS ---
    # ==========================================
    
    
    if cycle_count_col in df.columns:
        valid_cycles = df[df[cycle_count_col] != 0][cycle_count_col]
        
        if not valid_cycles.empty:
            cycle_count_val = int(valid_cycles.iloc[-1])
        else:
            cycle_count_val = "No Data"
    else:
        cycle_count_val = "Column Not Found"

    if mcu_count_col in df.columns:
        valid_mcu = df[df[mcu_count_col] != 0][mcu_count_col]
        
        if not valid_mcu.empty:
            mcu_count_val = int(valid_mcu.iloc[-1])
        else:
            mcu_count_val = "No Data"
    else:
        mcu_count_val = "Column Not Found"
    vehicle_state_val = str(df[vehicle_state_col].mode()[0]) if vehicle_state_col in df.columns and not df[vehicle_state_col].empty else ""
    
    balancing_val = "1" if flag_balance_col in df.columns and (df[flag_balance_col] == 1).any() else "0"
    flag_full_charged_val = "1" if flag_full_chg_col in df.columns and (df[flag_full_chg_col] == 1).any() else "0"

    # --- START & END VOLTAGE ---
    start_voltage_val = "N/A"
    end_voltage_val = "N/A"
    if voltage_col in df.columns and not df.empty:
        valid_v = df[voltage_col].replace(0, pd.NA).dropna()
        if not valid_v.empty:
            start_voltage_val = round(float(valid_v.iloc[0]), 2)
            end_voltage_val = round(float(valid_v.iloc[-1]), 2)

    # --- BMS STATE LOGIC ---
    bms_state_val = "N/A"
    if bms_state_col in df.columns and not df[bms_state_col].dropna().empty:
        condensed_states = []
        prev_state = None
        for s in df[bms_state_col].dropna().astype(int):
            if s != prev_state:
                condensed_states.append(s)
                prev_state = s
                
        seq_str = "->".join(map(str, condensed_states))
        
        if "1->2->3" in seq_str:
            bms_state_val = "Correct (Discharging)"
        elif "1->2->4" in seq_str:
            bms_state_val = "Precharge Fail (1->2->4)"
        else:
            bms_state_val = "->".join(map(str, condensed_states[:4]))

    # --- CURRENT STATS ---
    avg_discharge_current_val = 0.0
    peak_discharge_current_val = 0.0
    max_regen_current_val = 0.0
    peak_discharge_ready_val = "Battery didn't go to state '2'"

    orig_discharge_mask = df[current_col] < 0
    orig_regen_mask = df[current_col] > 0
    

    if orig_discharge_mask.any():
        avg_discharge_current_val = df.loc[orig_discharge_mask,current_col].mean()
        peak_discharge_current_val = df.loc[orig_discharge_mask, current_col].min()

    if orig_regen_mask.any():
        max_regen_current_val = df.loc[orig_regen_mask, current_col].max()
        
    if bms_state_col in df.columns:
        ready_mask = df[bms_state_col] == 2
        if ready_mask.any():
            ready_df = df[ready_mask]
            min_val = ready_df[current_col].min()
            if pd.notna(min_val) and min_val < 0:
                min_idx = ready_df[current_col].idxmin()
                soc_at_min = df.loc[min_idx, soc_col] if soc_col in df.columns else 0
                peak_discharge_ready_val = f"{round(min_val, 2)}A @ {soc_at_min:.1f}%"

    # --- RANGE, ODO & SOC EXTRACTION ---
    if odo_col in df.columns and not df[odo_col].dropna().empty:
        valid_odo = df[odo_col].dropna()
        start_odo_val = round(valid_odo.iloc[0], 2)
        end_odo_val = round(valid_odo.iloc[-1], 2)
        total_range_km = end_odo_val - start_odo_val
        
    if 'Gear_Mode' in df.columns:
        mode_counts_pct = df['Gear_Mode'].value_counts(normalize=True) * 100
        if not mode_counts_pct.empty:
            dominant_mode_val = f"{mode_counts_pct.index[0]} ({mode_counts_pct.iloc[0]:.1f}%)"
            
    if "Unknown" in dominant_mode_val or dominant_mode_val == "N/A":
        if 'MCU_gear' in df.columns:
            mcu_counts_pct = df['MCU_gear'].value_counts(normalize=True) * 100
            if not mcu_counts_pct.empty:
                dominant_mode_val = f"{mcu_counts_pct.index[0]}"

    if bms_soc_col in df.columns and not df.empty:
        clean_bms_soc = df[bms_soc_col].rolling(window=10, min_periods=1).median()
        initial_soc_val = f"{clean_bms_soc.iloc[0]:.2f}"
        final_soc_val = f"{clean_bms_soc.iloc[-1]:.2f}"
        soc_diff = clean_bms_soc.diff()
        
        max_jump = soc_diff.max()
        if pd.notna(max_jump) and max_jump > 0.1:
            jump_idx = soc_diff.idxmax()
            idx_pos = clean_bms_soc.index.get_loc(jump_idx)
            val_to = clean_bms_soc.loc[jump_idx]
            val_from = clean_bms_soc.iloc[idx_pos - 1] if idx_pos > 0 else 0
            max_soc_jump_val = f"{max_jump:.1f}% ({val_from:.1f}% -> {val_to:.1f}%)"

        max_drop = soc_diff.min()
        if pd.notna(max_drop) and max_drop < -0.1:
            drop_idx = soc_diff.idxmin()
            idx_pos = clean_bms_soc.index.get_loc(drop_idx)
            val_to = clean_bms_soc.loc[drop_idx]
            val_from = clean_bms_soc.iloc[idx_pos - 1] if idx_pos > 0 else 0
            max_soc_drop_val = f"{abs(max_drop):.1f}% ({val_from:.1f}% -> {val_to:.1f}%)"

    # --- DIRECT PACK CAPACITY EXTRACTION ---
    if 'PackCapacity' in df.columns and not df['PackCapacity'].dropna().empty:
        valid_pack_cap = df['PackCapacity'].dropna()
        start_capacity_ah_val = round(float(valid_pack_cap.iloc[0]), 2)
        end_capacity_ah_val = round(float(valid_pack_cap.iloc[-1]), 2)

        if battery_capacity_ah > 0:
            avg_pack_voltage = consumed_energy_wh / battery_capacity_ah
     
            start_energy_wh_val = round(start_capacity_ah_val * avg_pack_voltage, 2)
            end_energy_wh_val = round(end_capacity_ah_val * avg_pack_voltage, 2)
    
 
    
    
    if soc_col in df.columns and odo_col in df.columns:
        # 1. Clean the SOC signal
        soc_series = pd.to_numeric(df[soc_col], errors='coerce')
        clean_soc = soc_series.rolling(window=10, min_periods=1).median()
        
        # 2. Extract BMS State once so we can reuse it for both calculations
        if bms_state_col in df.columns:
            bms_state_series = pd.to_numeric(df[bms_state_col], errors='coerce')
        else:
            bms_state_series = None
        
        # Initialize defaults
        range_till_10_val = "Did not reach 10%"
        range_below_0_val = 0.0

        # ==========================================================
        # --- 1. RANGE TILL 10% SOC ---
        # ==========================================================
        # Explicitly ensure mask_10 only triggers in Drive State (3)
        if bms_state_series is not None:
            mask_10 = (clean_soc <= 10) & (bms_state_series == 3)
        else:
            mask_10 = (clean_soc <= 10)
        
        # Safety: check if it's a Series and has at least one True value
        if isinstance(mask_10, pd.Series) and mask_10.any():
            first_idx_10 = mask_10[mask_10].index[0]
            
            valid_odo = pd.to_numeric(df[odo_col], errors='coerce').dropna()
            if not valid_odo.empty:
                start_odo = valid_odo.iloc[0]
                odo_at_10 = pd.to_numeric(df.loc[first_idx_10, odo_col], errors='coerce')
                range_till_10_val = round(float(odo_at_10) - float(start_odo), 2)

      # ==========================================================
        # --- 2. RANGE BELOW 0% SOC (BMS State 3 Only) ---
        # ==========================================================
        
        # 1. Define the mask: SOC <= 0 AND BMS State is 3
        # We ensure bms_state_col is numeric to avoid string-matching crashes
        if bms_state_col in df.columns:
            bms_state_series = pd.to_numeric(df[bms_state_col], errors='coerce')
            mask_0 = (clean_soc <= 0) & (bms_state_series == 3)

        # 2. Safety check: ensure mask is valid
        if isinstance(mask_0, pd.Series) and mask_0.any():
            # Get all index numbers where SOC <= 0 AND state == 3
            zero_indices = mask_0[mask_0].index
            
            first_idx_0 = zero_indices[0]  
            last_idx_0 = zero_indices[-1]
            
            odo_at_first_0 = pd.to_numeric(df.loc[first_idx_0, odo_col], errors='coerce')
            odo_at_last_0 = pd.to_numeric(df.loc[last_idx_0, odo_col], errors='coerce')
            
            range_below_0_val = round(float(odo_at_last_0) - float(odo_at_first_0), 2)


# --- 1st Vmin & corresponding Vmax (@SOC) 2700mV ---
    first_vmin_2700_val = "UV not hit"
    first_vmax_2700_val = "UV not hit" 
    first_vmax_2700_val_vmax = "UV not hit"
    first_vmin_2700_val_vmin = "UV not hit" 
    first_soc_2700_val_soc = "UV not hit"
    
    if cell_vmin_col in df.columns and cell_vmax_col in df.columns and soc_col in df.columns:
        mask_2700 = (df[cell_vmin_col] <= 2700.0) & (df[cell_vmin_col] > 500.0)
        
        if mask_2700.any():
            first_idx = df[mask_2700].index[0]
            
            vmin_mv = df.loc[first_idx, cell_vmin_col]
            vmax_mv = df.loc[first_idx, cell_vmax_col]
            val_soc = df.loc[first_idx, soc_col]
            
            vmin_str = ""
            vmax_str = ""
            cell_cols = [c for c in df.columns if c.startswith('CellVoltage_')]
            
            if cell_cols:
                row_cells = df.loc[first_idx, cell_cols]
                valid_cells = row_cells[row_cells > 500.0] 

                matching_vmin = valid_cells[valid_cells == vmin_mv]
                if not matching_vmin.empty:
                    vmin_num = str(matching_vmin.index[0]).split('_')[-1]
                else:
                    vmin_num = str(valid_cells.astype(float).idxmin()).split('_')[-1]
                vmin_str = f"Cell {vmin_num}"

                matching_vmax = valid_cells[valid_cells == vmax_mv]
                if not matching_vmax.empty:
                    vmax_num = str(matching_vmax.index[0]).split('_')[-1]
                else:
                    vmax_num = str(valid_cells.astype(float).idxmax()).split('_')[-1]
                vmax_str = f"Cell {vmax_num}"
                
            first_vmin_2700_val = f"{vmin_mv}"
            first_vmin_2700_val_vmin = vmin_str
            first_vmax_2700_val = f"{vmax_mv}"
            first_vmax_2700_val_vmax = vmax_str
            first_soc_2700_val_soc = val_soc



    # --- HEALTH, TEMPS & FAULTS ---
    avg_imbalance_val = "N/A"
    cycle_min_temp_val = "N/A"
    cycle_max_temp_val = "N/A"
    avg_temp_val = "N/A"
    max_delta_val = "N/A"
    max_delta_val_soc = "N/A"
    
    vmax_at_peak_imb_val = "N/A"
    vmin_at_peak_imb_val = "N/A" 
    contactor_weld_val = "No"
    precharge_fail_val = "No"
    shutdown_comm_val  = "N/A"
    
    max_aux_val = "N/A"
    min_aux_val = "N/A"
    max_aux_val_soc="N/A"
    min_aux_val_soc="N/A"
    pcb_temp_min_val = "N/A"
    pcb_temp_max_val = "N/A"
    pcb_temp_delta_val = "N/A"

    if aux_voltage_col in df.columns:
        max_aux_raw = df[aux_voltage_col].max()
        min_aux_raw = df[aux_voltage_col].min()
        
        if pd.notna(max_aux_raw) and pd.notna(min_aux_raw):
            if soc_col in df.columns:
                min_idx = df[aux_voltage_col].idxmin() 
                soc_at_min = df.loc[min_idx, soc_col]
                min_aux_val = f"{round(min_aux_raw, 2)}"
                min_aux_val_soc = soc_at_min
                
                max_idx = df[aux_voltage_col].idxmax()
                soc_at_max = df.loc[max_idx, soc_col]
                max_aux_val = f"{round(max_aux_raw, 2)}"
                max_aux_val_soc = soc_at_max

            else:
                min_aux_val = f"{round(min_aux_raw, 2)}V"
                max_aux_val = f"{round(max_aux_raw, 2)}V"
        
    if pcb_temp_min_col in df.columns and pcb_temp_max_col in df.columns:
        valid_pcb_mask = ~df[pcb_temp_min_col].isin([0, -99]) & ~df[pcb_temp_max_col].isin([0, -99])
        valid_pcb = df[valid_pcb_mask]
        if not valid_pcb.empty:
            pcb_temp_min_val = valid_pcb[pcb_temp_min_col].min()
            pcb_temp_max_val = valid_pcb[pcb_temp_max_col].max()
            if pcb_temp_delta_col in df.columns:
                pcb_temp_delta_val = valid_pcb[pcb_temp_delta_col].max()

    # --- IMBALANCE METRICS ---
    if imbalance_col in df.columns and bms_soc_col in df.columns:
        low_soc_df = df[df[bms_soc_col] < 99.8]
        if not low_soc_df.empty:
            max_imb_low_soc = low_soc_df[imbalance_col].max()
            if pd.notna(max_imb_low_soc):
                if cell_vmax_col in df.columns:
                    first_vmax = low_soc_df.loc[low_soc_df[imbalance_col] == max_imb_low_soc, cell_vmax_col].iloc[0]
                    vmax_at_peak_imb_val = f"{first_vmax}"
                if cell_vmin_col in df.columns:
                    first_vmin = low_soc_df.loc[low_soc_df[imbalance_col] == max_imb_low_soc, cell_vmin_col].iloc[0]
                    vmin_at_peak_imb_val = f"{first_vmin}"
            else:
                vmax_at_peak_imb_val = "N/A"
                vmin_at_peak_imb_val = "N/A"
        else:
            vmax_at_peak_imb_val = "N/A (SOC never < 85 %)"
            vmin_at_peak_imb_val = "N/A (SOC never < 85 %)"
            
    if 'Voltage_Delta' in df.columns:
        avg_imbalance_val = round(df['Voltage_Delta'].mean(), 4)

    if temp_max_col in df.columns and temp_min_col in df.columns:
        valid_ext = df[~df[temp_max_col].isin([0, -99]) & ~df[temp_min_col].isin([0, -99])]
        if not valid_ext.empty:
            cycle_min_temp_val = valid_ext[temp_min_col].min()
            cycle_max_temp_val = valid_ext[temp_max_col].max()
            avg_temp_val = round(((valid_ext[temp_max_col] + valid_ext[temp_min_col]) / 2.0).mean(), 2)
            if temp_delta_col in df.columns:
                max_d = valid_ext[temp_delta_col].max()
                soc_at_d = valid_ext.loc[valid_ext[temp_delta_col] == max_d, soc_col].iloc[0]
                max_delta_val = f"{max_d}"
                max_delta_val_soc = soc_at_d

    if bms_state_col in df.columns:
        weld_mask = (df[bms_state_col] == 1) & (df[current_col].abs() > 150)
        contactor_weld_val = "Yes" if weld_mask.any() else "No"
        
    if precharge_fail_col in df.columns:
        fail_mask = (df[precharge_fail_col] == 1) | (df[precharge_fail_col] == True)
        precharge_fail_val = "Yes" if fail_mask.any() else "No"

    if vcu_cmd_col in df.columns:
        if (df[vcu_cmd_col] == 1).any():
            if bms_ack_col in df.columns and ((df[vcu_cmd_col] == 1) & (df[bms_ack_col] == 1)).any():
                shutdown_comm_val = "OK"
            else:
                shutdown_comm_val = "Failed"

    # --- DCLO vs PACK CURRENT LOGIC ---
    dclo_vs_pack_current_val = "EFUSE not triggered"
    if efuse_col in df.columns:
        mask = (df[efuse_col] == 1) | (df[efuse_col] == '1') | (df[efuse_col] == True)
        if mask.any():
            first_error_idx = df[mask].index[0]
            if soc_col in df.columns:
                soc_at_error = df.loc[first_error_idx, soc_col]
                dclo_vs_pack_current_val = f"EFUSE triggered @ {soc_at_error:.1f}% SOC"

    # --- BMS STATE TRANSITION ---
    transition_val = "N/A"
    if bms_state_col in df.columns and soc_col in df.columns:
        condensed_states = []
        condensed_socs = []
        prev_state = None
        for idx, row in df.iterrows():
            s = row[bms_state_col]
            soc_v = row[soc_col]
            if pd.notna(s):
                s_int = int(s)
                if s_int != prev_state:
                    condensed_states.append(s_int)
                    condensed_socs.append(soc_v)
                    prev_state = s_int
        if condensed_states:
            transition_val = "1->2->3 Not Attempted"
            for i in range(len(condensed_states)):
                if condensed_states[i] == 1:
                    if i + 1 < len(condensed_states) and condensed_states[i+1] == 2:
                        if i + 2 < len(condensed_states) and condensed_states[i+2] == 3:
                            transition_val = "Valid (1->2->3)"
                            break 
                        elif i + 2 < len(condensed_states):
                            transition_val = f"Failed (1->2->{condensed_states[i+2]}) @ {condensed_socs[i+2]:.1f}% SOC"
                    elif i + 1 < len(condensed_states):
                        transition_val = f"Failed (1->{condensed_states[i+1]}) @ {condensed_socs[i+1]:.1f}% SOC"

    # --- ALL ERRORS ---
    active_errors = []
    for err_col in error_columns_to_check:
        if err_col in df.columns:
            if (df[err_col] == 1).any() or (df[err_col] == True).any() or (df[err_col] == '1').any():
                active_errors.append(err_col)
                
    if 'CMU_openwire_error' in df.columns and 'CMU_OW_Index' in df.columns:
        mask = (df['CMU_openwire_error'] == 1) | (df['CMU_openwire_error'] == '1')
        if mask.any():
            first_idx = df[mask].index[0]
            cmu_num = int(float(df.loc[first_idx, 'CMU_OW_Index']))
            active_errors.append(f"Open Wire Fault (@ CMU #{cmu_num})")

    if 'CMU_internal_NTC_error' in df.columns and 'CMU_Int_NTC_Index' in df.columns:
        mask = (df['CMU_internal_NTC_error'] == 1) | (df['CMU_internal_NTC_error'] == '1')
        if mask.any():
            first_idx = df[mask].index[0]
            cmu_num = int(float(df.loc[first_idx, 'CMU_Int_NTC_Index']))
            active_errors.append(f"Internal NTC Fault (@ CMU #{cmu_num})")

    if 'CMU_external_NTC_error' in df.columns and 'CMU_Ext_NTC_Index' in df.columns:
        mask = (df['CMU_external_NTC_error'] == 1) | (df['CMU_external_NTC_error'] == '1')
        if mask.any():
            first_idx = df[mask].index[0]
            cmu_num = int(float(df.loc[first_idx, 'CMU_Ext_NTC_Index']))
            active_errors.append(f"External NTC Fault (@ CMU #{cmu_num})")

    all_errors_val = ", ".join(active_errors) if active_errors else "None"

    # --- PRINT CONSOLE SUMMARY ---
    print("\n" + "="*55)
    print("                  CAPACITY & ENERGY SUMMARY                ")
    print("="*55)
    print(f"Start Capacity (@ {initial_soc_val}%):  {start_capacity_ah_val} Ah")
    print(f"End Capacity   (@ {final_soc_val}%):  {end_capacity_ah_val} Ah")
    print("-" * 55)
    print(f"Total Capacity (Discharge < 0A):  {total_capacity_ah:.4f} Ah")
    print(f"Regen Capacity (Charge > 0A):     {regen_capacity_ah:.4f} Ah")
    print(f"Battery Capacity (Net Used):      {battery_capacity_ah:.4f} Ah")
    print("-" * 55)
    print(f"Drive Energy Spent (< 0A):        {drive_energy_wh:.2f} Wh")
    print(f"Regen Energy (> 0A):              {regen_energy_wh:.2f} Wh")
    print(f"Consumed Energy (Net from Pack):  {consumed_energy_wh:.2f} Wh")
    
    print("\n" + "="*55)
    print("                    CURRENT STATISTICS                     ")
    print("="*55)
    print(f"Start Voltage:                    {start_voltage_val} V")
    print(f"End Voltage:                      {end_voltage_val} V")
    print(f"Average Discharge Current:        {avg_discharge_current_val:.2f} A")
    print(f"Peak Discharge Current (Entire):  {peak_discharge_current_val:.2f} A")
    print(f"Max Regen Current (Entire):       {max_regen_current_val:.2f} A")
    print(f"Peak Discharge (Ready Mode):      {peak_discharge_ready_val}")
    
    print("\n" + "="*55)
    print("               RANGE, SOC & DRIVE MODE METRICS             ")
    print("="*55)
    if gear_mode_col in df.columns or 'MCU_gear' in df.columns:
        print(f"Dominant Drive Mode:              {dominant_mode_val}")
        print("-" * 55)
    if bms_soc_col in df.columns:
        print(f"Initial BMS SoC:                  {initial_soc_val} %")
        print(f"Final BMS SoC:                    {final_soc_val} %")
        print(f"Max BMS SoC Jump:                 {max_soc_jump_val}")
        print(f"Max BMS SoC Drop:                 {max_soc_drop_val}")
        print("-" * 55)
    if odo_col in df.columns:
        print(f"Start Odometer:                   {start_odo_val} km")
        print(f"End Odometer:                     {end_odo_val} km")
        print(f"Total Range:                      {total_range_km:.2f} km")
        print("-" * 55)
    if soc_col in df.columns and odo_col in df.columns:
        print(f"Range till 10% SOC:               {range_till_10_val} km")
        print(f"Range below 0% SOC:               {range_below_0_val} km")
        
    print("\n" + "="*55)
    print("           HEALTH, TEMPERATURE & FAULT ALERTS             ")
    print("="*55)
    print(f"BMS Dominant State:               {bms_state_val}")
    print(f"State Transition (1->2->3):       {transition_val}")
    print(f"1st Vmin Hit (2700mV):            {first_vmin_2700_val}")
    print("-" * 55)
    print(f"Average Imbalance:                {avg_imbalance_val} mV")
    print(f"Vmax @ Peak Imbalance (Low SOC):  {vmax_at_peak_imb_val}")
    print(f"Vmin @ Peak Imbalance (Low SOC):  {vmin_at_peak_imb_val}")
    print("-" * 55)
    print(f"Minimum Temperature:              {cycle_min_temp_val} °C")
    print(f"Maximum Temperature:              {cycle_max_temp_val} °C")
    print(f"Average Temperature:              {avg_temp_val} °C")
    print(f"Max Temp Delta @ SoC:             {max_delta_val} °C")
    print("-" * 55)
    print(f"Active Errors (Entire Cycle):     {all_errors_val}")
    print(f"Contactor Weld Detected:          {contactor_weld_val}")
    print(f"Precharge Fail @ BMS SoC:         {precharge_fail_val}")
    print(f"Shutdown VCU-BMS Comm:            {shutdown_comm_val}")
    print("="*55 + "\n")

    # --- SUB-STRING EXTRACTION FOR PEAK IMBALANCE ---
    peak_imb_val = "N/A"
    if vmax_at_peak_imb_val != "N/A" and "Delta" in vmax_at_peak_imb_val:
        try: peak_imb_val = vmax_at_peak_imb_val
        except: peak_imb_val = "N/A"

    # =========================================================================
    # --- EXACT 65-COLUMN SHUFFLED EXCEL STRUCTURE ---
    # =========================================================================
    summary_data_horizontal = {
        "Date": [date_val],
        "Vehicle Name": [""],
        "FW": [marvel_fw_val],
        "Config": [config_val],
        "MODE": [dominant_mode_val],
        "PayLoad": [""],
        "Total Consumed Capacity(Ah)": [round(total_capacity_ah, 4)],
        "Consumed Energy (Regen included) (Wh)": [round(drive_energy_wh, 2)],
        "Vehicle Range (km)": [round(total_range_km, 2) if isinstance(total_range_km, (int, float)) else total_range_km],
        "Peak Imbalance (mV)": [max_imb_low_soc],
        "High Imbalance Vmin (mV)": [vmin_at_peak_imb_val],
        "Avg Imbalance (mV)": [avg_imbalance_val],
        "Temp Delta (deg C)": [max_delta_val],
        "Temp Delta @ SOC (%)": [max_delta_val_soc],
        "Range below 0% SOC (km)": [range_below_0_val],
        "Range 100% to 10% SoC (km)": [range_till_10_val],
        "Start Capacity (Ah)": [start_capacity_ah_val],
        "End Capacity (Ah)": [end_capacity_ah_val],
        "Start Energy (Wh)": [start_energy_wh_val], 
        "End Energy (Wh)": [end_energy_wh_val],   
        "Battery Capacity (Ah)": [round(battery_capacity_ah, 4)],
        "Regen Capacity (Ah)": [round(regen_capacity_ah, 4)],
        "Total Capacity (Ah)": [round(total_capacity_ah, 4)],
        "Actual Consumed Energy (only Battery pack) (Wh)": [round(consumed_energy_wh, 2)],
        "Regen Energy (Wh)": [round(regen_energy_wh, 2)],
        "Start Voltage (V)": [start_voltage_val],
        "End Voltage (V)": [end_voltage_val],
        "Start Display SoC (%)": [f"{initial_soc_val}" if initial_soc_val != "N/A" else "N/A"],
        "End Display SoC (%)": [f"{final_soc_val}" if final_soc_val != "N/A" else "N/A"],
        "Start Odo (km)": [start_odo_val],
        "End Odo (km)": [end_odo_val],
        "Max Current (A)": [round(-1*peak_discharge_current_val, 2)],
        "Average Current (A)": [round(-1*avg_discharge_current_val, 2)],
        "Max Battery Temp (deg C)": [cycle_max_temp_val],
        "Min Battery Temp (deg C)": [cycle_min_temp_val],
        "Average Battery Temp (deg C)": [avg_temp_val],
        "Max Cell Voltage at UV (mV)": [first_vmax_2700_val],
        "Max Cell Voltage at UV (Cell Number)":[first_vmax_2700_val_vmax],
        "Min Cell Voltage at UV (mV)": [first_vmin_2700_val],
        "Min Cell Voltage at UV (Cell Number)":[first_vmin_2700_val_vmin],
        "SOC @ UV Triggered (%)":[first_soc_2700_val_soc],
        "MANIFEST": [manifest_val],
        "GITSHA": [gitsha_val], 
        "Tmp Range (ENTIRE CYCLE)": [f"{cycle_min_temp_val} to {cycle_max_temp_val}" if cycle_min_temp_val != "N/A" else "N/A"],
        "Avg Temp (deg C)": [avg_temp_val],
        "BMS STATE": [bms_state_val],
        "Flag Full Charged": [flag_full_charged_val],
        "SoC Delta (Max jump/drop)": [f"Jump: {max_soc_jump_val} / Drop: {max_soc_drop_val}"],
        "Shutdown Routine Sec": [shutdown_comm_val],
        "Precharge Process Check": [precharge_fail_val],
        "1st Vmin(@SOC) 2700mV": [first_soc_2700_val_soc],
        "Contactor Weld": [contactor_weld_val],
        "State Transition BMS Behaviour": [transition_val],
        "Cycle Count BMS (cycles)": [cycle_count_val],
        "MCU Count (cycles)": [mcu_count_val],
        "BALANCING": [balancing_val],
        "Max Current in Ready Mode (A)": [peak_discharge_ready_val],
        "DCLOvsPackCurrent": [dclo_vs_pack_current_val],
        "Avg Discharge Current (A)": [round(-1*avg_discharge_current_val, 2)],
        "Peak Discharge Current (A)": [round(-1*peak_discharge_current_val, 2)],
        "Max Regen Current (A)": [round(max_regen_current_val, 2)],
        "Max Aux (V)": [max_aux_val],
        "Max Aux_SoC (%)": [max_aux_val_soc],
        "Min AUX (V)": [min_aux_val],
        "Min AUX_SoC (%)": [min_aux_val_soc],
        "PCB Temperature MIN (deg C)": [pcb_temp_min_val],
        "PCB Temperature MAX (deg C)": [pcb_temp_max_val],
        "PCB Temp Delta on Same Instance (deg C)": [pcb_temp_delta_val],
        "All Error Efuse Validation": [all_errors_val],
        "Vehicle State": [vehicle_state_val],
        "STARK F/W": [stark_fw_val]
    }
    
    summary_df = pd.DataFrame(summary_data_horizontal)
    
    # --- AUTOMATIC SAVE LOGIC ---
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"Battery_Analysis_Summary_{timestamp}.xlsx"
    save_path = os.path.join(target_dir, filename)

    try:
        summary_df.to_excel(save_path, sheet_name='Summary', index=False)
        print(f"SUCCESS! Summary automatically saved to: {save_path}\n")
    except Exception as e:
        print(f"ERROR: Could not save the summary file. Is the file open? Details: {e}")

# =============================================================================
# --- 4. MAIN ORCHESTRATOR ---
# =============================================================================
def main():
    root = get_root()
    
    # 1. Select inputs
    trc_files = select_trc_files(root)
    if not trc_files: 
        print("No TRC files selected. Exiting.")
        return

    #dbc_file = select_dbc_file(root)

    # 2. AUTO-LOAD DBC FILE (Bundled inside the EXE)
    if getattr(sys, 'frozen', False):
        # When running as compiled .exe, look in PyInstaller's hidden temp folder
        base_dir = sys._MEIPASS 
    else:
        # When running as a normal .py script, look in the same folder as the script
        base_dir = os.path.dirname(os.path.abspath(__file__))
        
    dbc_files = glob.glob(os.path.join(base_dir, "*.dbc"))
    
    if not dbc_files:
        print(f"\n[CRITICAL ERROR] No .dbc file found!")
        print("Make sure the .dbc file is bundled when compiling with PyInstaller. Exiting.")
        return
    #Remove below line for attaching DBC in exe.
    dbc_file = dbc_files[0]
    print(f"\nAuto-loaded DBC file: {os.path.basename(dbc_file)}")


    if not dbc_file: 
        print("No DBC file selected. Exiting.")
        return

    target_dir = os.path.dirname(trc_files[0])
    try:
        dbc = cantools.database.load_file(dbc_file)
    except Exception as e:
        print(f"Failed to load DBC file: {e}")
        return

    dbc_signal_order = [sig.name for msg in dbc.messages for sig in msg.signals]
            
    grand_pos_ah, grand_neg_ah, grand_drive_wh, grand_regen_wh = 0.0, 0.0, 0.0, 0.0

     

    # 2. Parse all TRC files
    for trc in trc_files:
        p_ah, n_ah, d_wh, r_wh = decode_trc_file(trc, dbc, dbc_signal_order)
        grand_pos_ah += p_ah
        grand_neg_ah += n_ah
        grand_drive_wh += d_wh
        grand_regen_wh += r_wh

    # 3. Merge parsed CSV data
    search_pattern = os.path.join(target_dir, "*_pcan.csv")
    full_files = glob.glob(search_pattern)

    if not full_files: 
        print("\n[CRITICAL ERROR] No intermediate CSV files were generated.")
        return
        
    full_files.sort(key=extract_number)

    try:
        print("\nMerging parsed data...")
        csv_merged_full = pd.concat([pd.read_csv(f) for f in full_files], ignore_index=True)

        # Inject global capacities into the first row
        csv_merged_full['Total_Pos_Ah'] = np.nan
        csv_merged_full['Total_Neg_Ah'] = np.nan
        csv_merged_full['Total_Drive_Wh'] = np.nan
        csv_merged_full['Total_Regen_Wh'] = np.nan

        if not csv_merged_full.empty:
            csv_merged_full.at[0, 'Total_Pos_Ah'] = round(grand_pos_ah, 4)
            csv_merged_full.at[0, 'Total_Neg_Ah'] = round(grand_neg_ah, 4)
            csv_merged_full.at[0, 'Total_Drive_Wh'] = round(grand_drive_wh, 4)
            csv_merged_full.at[0, 'Total_Regen_Wh'] = round(grand_regen_wh, 4)

        final_output_path = os.path.join(target_dir, "pcan_merged_full.csv")
        csv_merged_full.to_csv(final_output_path, index=False)
        print(f"Merged full log saved to: {final_output_path}")

        generate_summary(csv_merged_full, target_dir)

    except Exception as e:
        print(f"CRITICAL ERROR merging or summarizing data: {e}")
    finally:
        root.destroy()

    
   

if __name__ == "__main__":
    main()