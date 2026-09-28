"""Allow ``python -m faultline <process>``."""

import sys

from faultline.cli import main

if __name__ == "__main__":
    sys.exit(main())
