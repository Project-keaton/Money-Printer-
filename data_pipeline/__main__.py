"""Allow ``python -m data_pipeline``."""

import sys

from data_pipeline.main import main

sys.exit(main())
