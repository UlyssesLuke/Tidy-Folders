"""Run every click-through check (check_*.py) and say which passed.

    python tests\\gui\\run_all.py              all of them (about 3 minutes)
    python tests\\gui\\run_all.py courses      just the ones with "courses" in their name

Windows open and close by themselves while it runs: leave the mouse and keyboard alone until it's
done. Each check uses its own temporary folders and settings, never your real ones. Screenshots are
saved in tests\\gui\\shots so you can look at them afterwards.

After building the .exe, also run:  powershell -File tests\\gui\\check_exe_tray.ps1
"""
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> int:
    wanted = [a.lower() for a in sys.argv[1:]]
    checks = [p for p in sorted(HERE.glob("check_*.py")) if not wanted or any(w in p.name for w in wanted)]
    failed = []
    for path in checks:
        start = time.time()
        print(f"\n--- {path.stem} ---", flush=True)
        result = subprocess.run([sys.executable, str(path)], cwd=HERE)
        took = time.time() - start
        if result.returncode == 0:
            print(f"    ok ({took:.0f}s)", flush=True)
        else:
            print(f"    FAILED ({took:.0f}s)", flush=True)
            failed.append(path.stem)
    print(f"\n{len(checks) - len(failed)} of {len(checks)} checks passed.")
    if failed:
        print("Failed: " + ", ".join(failed))
    print(f"Screenshots: {HERE / 'shots'}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
