"""YouTube Navigator package."""

import importlib.metadata
import os
from pathlib import Path

# Try to get version from version.txt when in development
# or from package metadata when installed
try:
    # First try to get version from package metadata (when installed)
    __version__ = importlib.metadata.version("yt_navigator")
except importlib.metadata.PackageNotFoundError:
    # If not installed, read from version.txt (next to the package in the Android app)
    version_files = [Path(__file__).parent.parent / "version.txt", Path(__file__).parent / "version.txt"]
    version_file = next((f for f in version_files if f.exists()), None)
    __version__ = version_file.read_text().strip() if version_file else "unknown"
