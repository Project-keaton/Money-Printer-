"""Allow ``python -m backtests``."""

import sys

from backtests.main import main

sys.exit(main())
