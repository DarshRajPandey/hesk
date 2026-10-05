import sys

from hesk.bench import analyze, run

USAGE = "usage: python -m hesk.bench {run|report} ..."

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in ("run", "report"):
        sys.exit(USAGE)
    cmd, rest = sys.argv[1], sys.argv[2:]
    (run.main if cmd == "run" else analyze.main)(rest)
