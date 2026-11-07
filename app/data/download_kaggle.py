r"""Download retail-style datasets from Kaggle as CSV files into data/raw/.

Requires Kaggle API credentials. Set them up one of two ways:

  1. Environment variables:
        set KAGGLE_USERNAME=your_username
        set KAGGLE_KEY=your_api_key
  2. Token file: download kaggle.json from
        https://www.kaggle.com/settings  ->  "Create New Token"
     and place it at  %USERPROFILE%\.kaggle\kaggle.json

Usage:
    python -m app.data.download_kaggle                 # curated retail set
    python -m app.data.download_kaggle --list          # show curated datasets
    python -m app.data.download_kaggle owner/dataset   # a specific dataset ref
    python -m app.data.download_kaggle --dest data/raw # change destination
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

from loguru import logger

# Curated, well-known retail / e-commerce datasets that publish CSV files.
CURATED: dict[str, str] = {
    "superstore": "vivek468/superstore-dataset-final",
    "online_retail": "carrie1/ecommerce-data",
    "sales_forecasting": "rohitsahoo/sales-forecasting",
    "retail_analysis": "manjeetsingh/retaildataset",
    "brazilian_ecommerce": "olistbr/brazilian-ecommerce",
}


def _safe(name: str) -> str:
    return re.sub(r"[^0-9a-zA-Z]+", "_", name.strip().lower()).strip("_") or "dataset"


def _copy_csvs(src: Path, dest_dir: Path) -> int:
    dest_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for csv in Path(src).rglob("*.csv"):
        shutil.copy2(csv, dest_dir / csv.name)
        count += 1
    return count


def download(refs: dict[str, str], dest_root: Path) -> dict[str, int]:
    import kagglehub  # imported lazily so --list works without the package

    results: dict[str, int] = {}
    for friendly, ref in refs.items():
        logger.info("Downloading {} ({}) ...", friendly, ref)
        try:
            cached = kagglehub.dataset_download(ref)
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to download {}: {}", ref, exc)
            results[friendly] = 0
            continue
        n = _copy_csvs(Path(cached), dest_root / _safe(friendly))
        logger.info("  -> {} CSV file(s) copied", n)
        results[friendly] = n
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download Kaggle retail datasets as CSV.")
    parser.add_argument(
        "datasets",
        nargs="*",
        help="Kaggle dataset refs (owner/name). Defaults to the curated retail set.",
    )
    parser.add_argument("--dest", default="data/raw", help="Destination folder.")
    parser.add_argument("--list", action="store_true", help="List curated datasets and exit.")
    args = parser.parse_args(argv)

    if args.list:
        print("Curated retail datasets:")
        for friendly, ref in CURATED.items():
            print(f"  {friendly:<22} {ref}")
        return 0

    if args.datasets:
        refs = {_safe(r.split("/")[-1]): r for r in args.datasets}
    else:
        refs = CURATED

    dest_root = Path(args.dest).resolve()
    results = download(refs, dest_root)

    total = sum(results.values())
    print(f"\nDownloaded {total} CSV file(s) into {dest_root}:")
    for friendly, n in results.items():
        status = f"{n} csv" if n else "FAILED (check Kaggle credentials / dataset ref)"
        print(f"  {friendly:<22} {status}")
    print("\nNext: load into PostgreSQL with  load_data.bat data\\raw")
    return 0 if total else 1


if __name__ == "__main__":
    sys.exit(main())
