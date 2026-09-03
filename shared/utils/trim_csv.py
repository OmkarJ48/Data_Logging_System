import pandas as pd
import sys
from pathlib import Path

# Add project root to sys.path to ensure we can import the central config
root = Path(__file__).resolve().parent.parent
if str(root) not in sys.path:
    sys.path.append(str(root))

from shared_config import HISTORICAL_CSV

def trim_csv(path=HISTORICAL_CSV, max_rows=30000):
    df = pd.read_csv(path, header=None)
    if len(df) > max_rows:
        df.tail(max_rows).to_csv(path, index=False, header=False)

if __name__ == "__main__":
    trim_csv()
