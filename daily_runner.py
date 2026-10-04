"""
Optional convenience runner.

Run this once per day from cron/Task Scheduler/launchd.
It intentionally invokes scanner.py only once, because the Light plan
has a 10 requests/minute and 2,000 requests/day limit.
"""

import subprocess
import sys

if __name__ == "__main__":
    raise SystemExit(subprocess.call([sys.executable, "scanner.py"]))
