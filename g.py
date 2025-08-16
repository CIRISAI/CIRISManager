#!/usr/bin/env python3
"""
Grace - CIRISManager quick access script.
Put this in your PATH or alias it.
"""

import os
import sys

# Get the directory of this script
script_dir = os.path.dirname(os.path.abspath(__file__))

# Add the parent directory to Python path so we can import tools
sys.path.insert(0, script_dir)

# Now import after path is set
from tools.grace.__main__ import main  # noqa: E402

if __name__ == "__main__":
    main()
