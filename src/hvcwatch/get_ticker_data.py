"""Download SEC company tickers data file."""

import gzip
import json
import sys
import urllib.error
import urllib.request

from hvcwatch.utils import SEC_DATA_PATH


def main() -> int:
    """Download and save SEC company tickers JSON data."""
    SEC_DATA_PATH.parent.mkdir(parents=True, exist_ok=True)

    url = "https://www.sec.gov/files/company_tickers.json"
    headers = {
        "User-Agent": "Major Hayden major@mhtx.net",
        "Accept-Encoding": "gzip, deflate",
    }

    print(f"Downloading SEC company tickers from {url}")

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=60) as response:
            raw_data = response.read()

            # Decompress if gzipped
            if raw_data[:2] == b"\x1f\x8b":
                data = gzip.decompress(raw_data)
            else:
                data = raw_data

            # Validate JSON
            tickers = json.loads(data)
            print(f"Downloaded {len(data):,} bytes with {len(tickers):,} companies")

            # Save to file
            with open(SEC_DATA_PATH, "wb") as f:
                f.write(data)

            print(f"Saved to {SEC_DATA_PATH}")
            return 0

    except urllib.error.HTTPError as e:
        print(f"HTTP Error: {e.code} - {e.reason}", file=sys.stderr)
        return 1
    except urllib.error.URLError as e:
        print(f"URL Error: {e.reason}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as e:
        print(f"Invalid JSON: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
