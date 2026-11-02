"""Bundle KB + seed data into the deploy directory before Vercel packages the function."""

from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PARENT = ROOT.parent
SRC_KB = PARENT / "kb"
DST_KB = ROOT / "kb"
SEED = ROOT / "seed"
LOCAL_DATA = ROOT / "data"

SEED_FILES = (
    "catalogue_primer.txt",
    "kb_index.json",
    "golden.jsonl",
)


def _copy_tree(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def main() -> None:
    if SRC_KB.is_dir():
        print(f"Copying KB {SRC_KB} -> {DST_KB}")
        _copy_tree(SRC_KB, DST_KB)
    elif DST_KB.is_dir():
        print(f"Using existing bundled KB at {DST_KB}")
    else:
        raise SystemExit(
            "Knowledge base missing. Expected ../kb (local) or ./kb (already bundled)."
        )

    SEED.mkdir(parents=True, exist_ok=True)
    for name in SEED_FILES:
        src = LOCAL_DATA / name
        if not src.is_file():
            # On Vercel the local data/ folder is gitignored and usually absent;
            # seed may already have been uploaded from a prior prepare run.
            if (SEED / name).is_file():
                print(f"Keeping existing seed/{name}")
                continue
            print(f"WARNING: missing {src}; skipping")
            continue
        dest = SEED / name
        shutil.copy2(src, dest)
        print(f"Seeded {dest}")

    print("Vercel prepare complete.")


if __name__ == "__main__":
    main()
