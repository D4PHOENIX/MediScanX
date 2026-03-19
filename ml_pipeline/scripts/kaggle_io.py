"""
High-speed data transfer utilities for Kaggle environments.
Bypasses standard OS-level directory scanning to rapidly cache datasets to local NVMe storage.
"""
import os
import shutil
import pandas as pd
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor
from src.cxr.config import CXRTrainingConfig

CFG = CXRTrainingConfig()
# Config constants
SOURCE_ROOT = CFG.kaggle_dataset_root
DEST_ROOT = CFG.kaggle_data_root
NUM_WORKERS = 64

def csv_guided_nvme_transfer(
    source_root: str = SOURCE_ROOT,
    dest_root: str = DEST_ROOT,
    num_workers: int = NUM_WORKERS
) -> None:
    """
    Transfer CheXpert dataset form Kaggle Servers to local Kaggle Notebook NVMe storages
    using CSV guides.
    
        Reads the train.csv and valid.csv files to get a list of image paths, then uses
    parallel threads to copy all the images and CSV files to the destination directory.

    Args:
        source_root (str): Path to the Kaggle dataset directory. Defaults to SOURCE_ROOT.
        dest_root (str): Destination path on local NVMe storage. Defaults to DEST_ROOT.
        num_workers (int): Number of parallel threads for copying files. Defaults to NUM_WORKERS.

    Returns:
        None
    """
    if os.path.exists(dest_root):
        print(f"Dataset already exists at {dest_root}. Skipping transfer.")
        return
    
    print("Bypassing network scan by reading CSV map...")
    
    # Read the maps
    train_df = pd.read_csv(f"{source_root}/train.csv")
    # Load valid.csv if it exists in that dataset structure
    valid_csv_path = f"{source_root}/valid.csv"
    if os.path.exists(valid_csv_path):
        valid_df = pd.read_csv(valid_csv_path)
        all_paths = pd.concat([train_df['Path'], valid_df['Path']]).values()
    else:
        all_paths = train_df['Path'].values
    
    copy_tasks = []
    
    # Build exact file paths in memory
    for path in all_paths:
        cleaned_path = path.replace("CheXpert-v1.0-small/", "")
        src = os.path.join(source_root, cleaned_path)
        dst = os.path.join(dest_root, cleaned_path)
        copy_tasks.append((src, dst))
        
    total_files = len(copy_tasks)
    print(f"Mapped {total_files:,} files. Copying to NVMe with 64 threads...")
    
    def copy_worker(task):
        """Copy a single file and create parent directories if needed."""
        src, dst = task
        # Create the parent directory
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        # Copy the image if it exists
        if os.path.exists(src):
            shutil.copy2(src, dst)
        return True
    
    # Spawn 64 threads to saturate Kaggle's network bandwidth
    with ThreadPoolExecutor(max_workers=64) as executor:
        list(tqdm(executor.map(copy_worker, copy_tasks), total=total_files, desc="Copying to /tmp/", unit="file"))
        
    # Finally, copy the CSV files themselves over to the SSD
    shutil.copy2(f"{source_root}/train.csv", f"{dest_root}/train.csv")
    if os.path.exists(valid_csv_path):
        shutil.copy2(valid_csv_path, f"{dest_root}/valid.csv")
        
    print("Transfer complete! Data is now cached on the local SSD for faster I/O.")

# Execute the hyper-fast transfer using our global configuration
csv_guided_nvme_transfer(CFG)