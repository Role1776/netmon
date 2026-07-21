
import os
import matplotlib
from typing import Final
matplotlib.use('Agg')  
import matplotlib.pyplot as plt
from typing import List
from models import NetworkMetric
from matplotlib.ticker import MultipleLocator, FormatStrFormatter, FuncFormatter
import matplotlib.dates as mdates

GRAPHS_DIR: Final[str] = "graphs"

class NetmonGraph:
    def __init__(self, data: List[NetworkMetric], device_counts: List[int]):
        self.data = data
        self.device_counts = device_counts

    def plot(self) -> str:
        timestamps: List[float] = []
        downloads: List[float] = []
        uploads: List[float] = []
        pings: List[float] = []

        for d in self.data:
            timestamps.append(float(mdates.date2num(d.timestamp)))
            downloads.append(d.download / 10**6)
            uploads.append(d.upload / 10**6)
            pings.append(d.ping)

        plt.figure(figsize=(10, 6))

        ax = plt.gca()
        ax.yaxis.set_major_locator(MultipleLocator(50))
        ax.yaxis.set_minor_locator(MultipleLocator(10))
        
        ax.yaxis.set_major_formatter(FormatStrFormatter('%g'))
        ax.yaxis.set_minor_formatter(FuncFormatter(lambda x, pos: "" if x % 50 == 0 else f"{x:g}"))
        
        ax.tick_params(axis='y', which='major', labelsize=10)
        ax.tick_params(axis='y', which='minor', labelsize=7)    

        ax.xaxis.set_major_locator(mdates.HourLocator(interval=2))
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%d-%m %H:%M'))
        ax.xaxis.set_minor_locator(mdates.HourLocator(interval=1))

        ax.grid(True, which='major', linestyle='--', alpha=0.6, color='gray')
        ax.grid(True, which='minor', linestyle=':', alpha=0.3, color='gray')
        plt.plot(timestamps, downloads, label='Download', color='blue', linewidth=2)
        plt.plot(timestamps, uploads, label='Upload', color='green', linewidth=2)
        plt.plot(timestamps, pings, label='Ping', color='red', linewidth=2, linestyle=':')
        plt.plot(timestamps, self.device_counts, label='Devices', color='purple', linewidth=2)

        plt.xlabel('Time')
        plt.ylabel('Speed (Mbps)')
        plt.title('Network Speed Test Results')
        plt.legend()
        plt.gcf().autofmt_xdate()

        os.makedirs(GRAPHS_DIR, exist_ok=True)
        
        fname = f"{GRAPHS_DIR}/network_speed_test.png"
        plt.savefig(fname)

        plt.close()
        
        return fname


    