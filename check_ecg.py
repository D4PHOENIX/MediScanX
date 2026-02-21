import wfdb
import matplotlib.pyplot as plt
import pandas as pd
import os

def check_mit_bih():
    print("\n--- Checking MIT-BIH ---")
    path = 'data/raw/ecg/mit-bih/100'
    
    try:
        record = wfdb.rdrecord(path)
        annotation = wfdb.rdann(path, 'atr')
        
        print(f"Loaded Record: {record.record_name}")
        print(f"Sampling Frequency: {record.fs} Hz")
        print(f"Signal Length: {record.sig_len}")
        
        plt.figure(figsize=(10, 4))
        plt.plot(record.p_signal[:1000,0])
        plt.title(f"MIT_BIH Record 100 (Lead {record.sig_name[0]})")
        plt.xlabel("Samples")
        plt.ylabel("Amplitude (mV)")
        plt.show()
        print("MIT_BIH Verified")
    except Exception as e:
        print((f"MIT-BIH Failed: {e}"))
        
def check_ptb_xl():
    print("\n--- Checking PTB-XL ---")
    base_path = "data/raw/ecg/ptb-xl"
    csv_path = os.path.join(base_path, "ptbxl_database.csv")
    
    try:
        df = pd.read_csv(csv_path, index_col='ecg_id')
        print(f"Metadata Loaded. Total Records: {len(df)}")
        
        first_record_file = df.iloc[0]['filename_lr']
        full_signal_path = os.path.join(base_path, first_record_file)
        
        record = wfdb.rdrecord(full_signal_path)
        print(f"Loaded Record: {record.record_name}")
        print(f"Diagnosis: {df.iloc[0]['scp_codes']}")
        
        plt.figure(figsize=(10,4))
        plt.plot(record.p_signal[:,0])
        plt.title(f"PTB-XL Record {record.record_name} (Lead I)")
        plt.show()
        print("PTB-XL Verified")
        
    except Exception as e:
        print(f"PTB-XL Failed: {e}")



check_mit_bih()