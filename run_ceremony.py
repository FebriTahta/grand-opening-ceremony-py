"""Entry script for PyInstaller (it can't start from a package's __main__ with relative imports)."""

import sys

from ceremony.app import main

if __name__ == "__main__":
    sys.exit(main())
