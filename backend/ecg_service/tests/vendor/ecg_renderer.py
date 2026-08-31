import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import cv2
import io

def generate_ecg_image(
    signal: np.ndarray, 
    layout: str = '3-band', 
    dpi: int = 150, 
    trace_thickness: float = 1.0,
    include_footer: bool = False
) -> np.ndarray:
    """
    Generates a realistic ECG image from a (12, 5000) numpy array at 500Hz (10 seconds).
    
    Args:
        signal: (12, N) array, typical N=5000 (10s at 500Hz).
        layout: '3-band' (3 rows, 4 cols) or '4-band' (3 rows, 4 cols + 1 rhythm strip).
        dpi: Resolution of the output image.
        trace_thickness: Thickness of the black trace.
        include_footer: Whether to include text footer at the bottom.
        
    Returns:
        np.ndarray: BGR image.
    """
    sample_rate = 500
    duration = signal.shape[1] / sample_rate # usually 10s
    
    # 25mm/s speed, 10mm/mV scale
    mm_per_sec = 25
    mm_per_mV = 10
    
    # Calculate figure size in inches. 
    # Width = 250mm for 10s. 1 inch = 25.4mm
    fig_width_in = (duration * mm_per_sec) / 25.4
    
    # Height depends on rows
    num_rows = 4 if layout == '4-band' else 3
    # typically each row gets about 40mm of vertical space
    fig_height_in = (num_rows * 40) / 25.4
    
    if include_footer:
        fig_height_in += 1.0 # 1 inch for footer
        
    fig, ax = plt.subplots(figsize=(fig_width_in, fig_height_in), dpi=dpi)
    fig.subplots_adjust(left=0.05, right=0.98, top=0.95, bottom=0.15 if include_footer else 0.05)
    
    # Grid properties
    # Major grid: 5mm (0.2s horizontal, 0.5mV vertical)
    # Minor grid: 1mm (0.04s horizontal, 0.1mV vertical)
    x_max = duration
    y_min = -1.5 * num_rows
    y_max = 1.5
    
    ax.set_xlim(0, x_max)
    ax.set_ylim(y_min, y_max)
    
    # Draw minor grid (1mm)
    x_minor = np.arange(0, x_max, 0.04)
    y_minor = np.arange(y_min, y_max, 0.1)
    
    # Instead of full grid plotting which is slow, we use matplotlib grid
    ax.set_xticks(x_minor, minor=True)
    ax.set_yticks(y_minor, minor=True)
    ax.set_xticks(np.arange(0, x_max + 0.2, 0.2))
    ax.set_yticks(np.arange(y_min, y_max + 0.5, 0.5))
    
    ax.grid(which='minor', color='#ffb3b3', linestyle='-', linewidth=0.5)
    ax.grid(which='major', color='#ff6666', linestyle='-', linewidth=1.0)
    
    ax.set_xticklabels([])
    ax.set_yticklabels([])
    ax.tick_params(axis='both', which='both', length=0)
    
    # Plotting leads
    leads = [
        ['I', 'aVR', 'V1', 'V4'],
        ['II', 'aVL', 'V2', 'V5'],
        ['III', 'aVF', 'V3', 'V6']
    ]
    lead_idx_map = {
        'I': 0, 'II': 1, 'III': 2,
        'aVR': 3, 'aVL': 4, 'aVF': 5,
        'V1': 6, 'V2': 7, 'V3': 8,
        'V4': 9, 'V5': 10, 'V6': 11
    }
    
    cols = 4
    segment_duration = duration / cols
    
    def plot_segment(lead_name, row, col):
        idx = lead_idx_map[lead_name]
        start_t = col * segment_duration
        end_t = (col + 1) * segment_duration
        
        start_samp = int(start_t * sample_rate)
        end_samp = int(end_t * sample_rate)
        
        t = np.linspace(start_t, end_t, end_samp - start_samp)
        y = signal[idx, start_samp:end_samp]
        
        # offset row by -2.5 mV per row
        y_offset = -(row * 1.5)
        
        ax.plot(t, y + y_offset, color='black', linewidth=trace_thickness)
        # Lead label
        ax.text(start_t + 0.05, y_offset + 0.8, lead_name, fontsize=12, fontweight='bold', color='black')
        
        # Calibration pulse (1mV high, 0.2s wide) at the end of the last column
        if col == cols - 1:
            pulse_x = [end_t - 0.25, end_t - 0.2, end_t - 0.2, end_t - 0.1, end_t - 0.1, end_t - 0.05]
            pulse_y = [y_offset, y_offset, y_offset + 1.0, y_offset + 1.0, y_offset, y_offset]
            ax.plot(pulse_x, pulse_y, color='black', linewidth=trace_thickness)
            
    for row in range(3):
        for col in range(4):
            plot_segment(leads[row][col], row, col)
            
    if layout == '4-band':
        # Plot full rhythm strip (lead II usually)
        row = 3
        y_offset = -(row * 1.5)
        t = np.linspace(0, duration, signal.shape[1])
        ax.plot(t, signal[1] + y_offset, color='black', linewidth=trace_thickness)
        ax.text(0.05, y_offset + 0.8, 'II', fontsize=12, fontweight='bold', color='black')

    if include_footer:
        fig.text(0.1, 0.05, "25mm/s 10mm/mV 150Hz Filter On", fontsize=10, color='black')
        fig.text(0.8, 0.05, "MediScanX Diagnostic", fontsize=10, color='black')

    # Convert to cv2 image
    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight', pad_inches=0.1)
    buf.seek(0)
    plt.close(fig)
    
    img_arr = np.frombuffer(buf.getvalue(), dtype=np.uint8)
    img = cv2.imdecode(img_arr, cv2.IMREAD_COLOR)
    return img
