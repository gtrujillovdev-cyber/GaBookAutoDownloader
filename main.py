#!/usr/bin/env python3
"""
Main application entry point for GaBookAutoDownloader.
"""
import sys
from pathlib import Path

# Add src to sys.path so gabook package is discoverable
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from gabook.bot import main

if __name__ == "__main__":
    main()
