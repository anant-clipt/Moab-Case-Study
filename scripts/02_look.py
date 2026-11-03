"""Print a short picture of what the prepare step decided.

Does not call Keystone. Run this after the download.
"""

import importlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
decide = importlib.import_module("03_prepare").decide

def main():
    _ready, _reviews, summary = decide()
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
