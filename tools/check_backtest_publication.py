"""Fail closed before committing backtest summaries; inspect the actual Git index."""

import subprocess
import sys


SUMMARY_PATHS = frozenset({
    "reports/backtest.csv",
    "reports/backtest_tech_summary.csv",
})
MAX_BLOB_BYTES = 10 * 1024 * 1024


def git(*args):
    return subprocess.check_output(["git", *args])


def check_staged(max_bytes=MAX_BLOB_BYTES):
    """Return all publication errors, including unexpected paths and deletions."""
    changed = git("diff", "--cached", "--name-only", "--no-renames", "-z").split(b"\0")
    entries = {}
    for entry in git("ls-files", "--stage", "-z").split(b"\0"):
        if entry:
            metadata, path = entry.split(b"\t", 1)
            mode, oid, stage = metadata.split()
            entries.setdefault(path, []).append((mode, oid, stage))
    errors = []
    for path in filter(None, changed):
        name = path.decode("utf-8", errors="replace")
        if name not in SUMMARY_PATHS:
            errors.append(f"Unexpected staged path: {name!r}; only backtest summaries may be committed.")
            continue
        records = entries.get(path, [])
        if len(records) != 1 or records[0][0] != b"100644" or records[0][2] != b"0":
            errors.append(f"{name}: expected a regular staged summary, not a deletion, symlink, or conflict.")
            continue
        size = int(git("cat-file", "-s", records[0][1].decode("ascii")))
        if size > max_bytes:
            errors.append(f"{name}: staged blob is {size} bytes, exceeding {max_bytes} bytes; keep large results in the Actions artifact.")
    return errors


def main():
    try:
        errors = check_staged()
    except (subprocess.CalledProcessError, ValueError) as exc:
        print(f"Backtest publication check failed: {exc}", file=sys.stderr)
        return 1
    if errors:
        print("Backtest publication blocked:\n" + "\n".join(errors), file=sys.stderr)
        return 1
    print("Backtest publication check passed: only size-limited summaries are staged.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
