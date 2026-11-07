r"""Download retail datasets from public URLs — no account, no API key.

These are direct-download CSV files hosted on GitHub (raw). Stdlib only, so it
works even before `pip install -r requirements.txt`.

Usage:
    python -m app.data.download_public                 # curated retail set
    python -m app.data.download_public --list          # show sources
    python -m app.data.download_public --dest data/raw # change destination
    python -m app.data.download_public <name> <url>    # add an ad-hoc source
"""

from __future__ import annotations

import argparse
import sys
import urllib.request
from pathlib import Path

# Friendly name -> direct-download CSV URL (no auth required).
SOURCES: dict[str, str] = {
    "sample_superstore": "https://raw.githubusercontent.com/leonism/sample-superstore/master/data/superstore.csv",
    "global_superstore": "https://raw.githubusercontent.com/yannie28/Global-Superstore/master/Global_Superstore(CSV).csv",
    "superstore_orders": "https://raw.githubusercontent.com/sumit0072/Superstore-Data-Analysis/main/Sample%20-%20Superstore.csv",
}

_UA = {"User-Agent": "conv-analytics-downloader/1.0"}


def _download(url: str, dest: Path) -> int:
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 (trusted URLs)
        data = resp.read()
    dest.write_bytes(data)
    return len(data)


def download(sources: dict[str, str], dest_root: Path) -> dict[str, int]:
    dest_root.mkdir(parents=True, exist_ok=True)
    results: dict[str, int] = {}
    for name, url in sources.items():
        out = dest_root / f"{name}.csv"
        try:
            size = _download(url, out)
            print(f"  {name:<22} OK  ({size:,} bytes)")
            results[name] = size
        except Exception as exc:  # noqa: BLE001
            print(f"  {name:<22} FAILED  ({exc})")
            results[name] = 0
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Download retail datasets from public URLs (no key needed)."
    )
    parser.add_argument(
        "extra",
        nargs="*",
        help="Optional ad-hoc source: <name> <url>.",
    )
    parser.add_argument("--dest", default="data/raw/public", help="Destination folder.")
    parser.add_argument("--list", action="store_true", help="List sources and exit.")
    args = parser.parse_args(argv)

    if args.list:
        print("Public retail datasets (no account required):")
        for name, url in SOURCES.items():
            print(f"  {name:<22} {url}")
        return 0

    sources = dict(SOURCES)
    if len(args.extra) == 2:
        sources = {args.extra[0]: args.extra[1]}
    elif args.extra:
        parser.error("Ad-hoc source needs exactly two values: <name> <url>")

    dest_root = Path(args.dest).resolve()
    print(f"Downloading into {dest_root} ...")
    results = download(sources, dest_root)

    ok = sum(1 for v in results.values() if v)
    print(f"\n{ok}/{len(results)} file(s) downloaded.")
    print("Next: load into PostgreSQL with  load_data.bat data\\raw")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
