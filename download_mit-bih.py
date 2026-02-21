import wfdb
import os

output_dir = "data/raw/ecg/mit-bih"
if not os.path.exists(output_dir):
    os.makedirs(output_dir)
    
print("Downloading MIT-BIH Database...")

wfdb.dl_database('mitdb', output_dir)
print("Download Complete.")