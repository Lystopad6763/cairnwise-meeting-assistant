"""Озвучити ВСІ скрипти діалогів у data/projects/**/meetings/<id>.json.

Пропускає ті, де вже є <id>.wav (якщо без --force). Для кожного викликає synthesize_dialogue.py,
що дає <id>.wav + <id>.rttm (ground-truth) + <id>.ref.json (еталон тексту).

  python scripts/synthesize_all.py
  python scripts/synthesize_all.py --force        # перезаписати наявні
"""
from __future__ import annotations

import argparse
import glob
import os
import subprocess
import sys


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--force", action="store_true", help="перезаписати наявні .wav")
    ap.add_argument("--root", default="data/projects")
    args = ap.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    synth = os.path.join(here, "synthesize_dialogue.py")

    scripts = sorted(glob.glob(os.path.join(args.root, "*", "meetings", "*.json")))
    scripts = [s for s in scripts if not s.endswith(".ref.json")]  # ref-файли — не скрипти

    todo = [s for s in scripts
            if args.force or not os.path.exists(os.path.splitext(s)[0] + ".wav")]
    print(f"{len(scripts)} scripts, {len(todo)} to voice")

    failed = []
    for i, s in enumerate(todo, 1):
        print(f"\n=== [{i}/{len(todo)}] {s} ===")
        if subprocess.run([sys.executable, synth, s]).returncode != 0:
            print(f"FAIL {s}", file=sys.stderr)
            failed.append(s)

    print(f"\nDone. {len(todo) - len(failed)}/{len(todo)} voiced"
          + (f", {len(failed)} failed" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
