"""
Downloads all Census Bureau CES (Center for Economic Studies) working papers
into year-numbered subfolders of this backup repo.

Papers live at:
    https://www2.census.gov/ces/wp/<year>/CES-WP-<yy>-<nn>.pdf
with revised versions posted alongside the original under an "R" suffix,
e.g. CES-WP-23-13R.pdf. The series goes back to 1988.

Rather than guessing paper numbers, this script reads each year's directory
listing (which Census leaves browsable) and downloads every file matching
the CES-WP-##-##[R].pdf pattern it finds. This automatically picks up gaps
in numbering and any revised versions.

Safe to re-run: existing files whose size already matches the remote file
are skipped, so re-running later only fetches new papers or newly posted
revisions.
"""

import datetime
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE_URL_TEMPLATE = "https://www2.census.gov/ces/wp/{year}/"
FILENAME_RE = re.compile(r'href="(CES-WP-\d{2}-\d+R?\.pdf)"', re.IGNORECASE)
USER_AGENT = "Mozilla/5.0 (compatible; CES-WP-backup-script/1.0)"

# The CES-WP series begins in 1988; years without papers simply 404 and are skipped.
START_YEAR = 1988
END_YEAR = datetime.date.today().year + 1

# Pace requests and back off on 429s so a full run of 1000+ files doesn't get
# rate-limited by the server midway through.
REQUEST_DELAY_SECONDS = 0.3
MAX_RETRIES = 5

DESTINATION = Path(__file__).resolve().parent


def fetch(url, method="GET"):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT}, method=method)
    for attempt in range(MAX_RETRIES):
        try:
            response = urllib.request.urlopen(request, timeout=30)
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < MAX_RETRIES - 1:
                retry_after = e.headers.get("Retry-After")
                wait = float(retry_after) if retry_after and retry_after.isdigit() else 2 ** (attempt + 1)
                time.sleep(wait)
                continue
            raise
        time.sleep(REQUEST_DELAY_SECONDS)
        return response


def list_papers_for_year(year):
    url = BASE_URL_TEMPLATE.format(year=year)
    try:
        with fetch(url) as response:
            html = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return []
        raise
    return sorted(set(FILENAME_RE.findall(html)))


def remote_size(url):
    with fetch(url, method="HEAD") as response:
        content_length = response.headers.get("Content-Length")
        return int(content_length) if content_length is not None else None


def download_file(url, dest_path):
    with fetch(url) as response:
        data = response.read()
    if not data.startswith(b"%PDF"):
        raise ValueError("response is not a PDF (got an error/rejection page instead)")
    dest_path.write_bytes(data)


def main():
    total_found = 0
    total_downloaded = 0
    total_skipped = 0
    total_errors = 0

    for year in range(START_YEAR, END_YEAR + 1):
        year_url = BASE_URL_TEMPLATE.format(year=year)

        try:
            filenames = list_papers_for_year(year)
        except (urllib.error.URLError, TimeoutError) as e:
            print(f"WARNING: failed to list {year_url}: {e}")
            total_errors += 1
            continue

        if not filenames:
            continue

        print(f"{year}: found {len(filenames)} paper(s)")
        year_dir = DESTINATION / str(year)
        year_dir.mkdir(parents=True, exist_ok=True)

        for filename in filenames:
            total_found += 1
            file_url = year_url + filename
            dest_path = year_dir / filename

            try:
                size = remote_size(file_url)
            except (urllib.error.URLError, TimeoutError) as e:
                print(f"  WARNING: could not check {filename}: {e}")
                total_errors += 1
                continue

            if dest_path.exists() and size is not None and dest_path.stat().st_size == size:
                total_skipped += 1
                continue

            try:
                download_file(file_url, dest_path)
                print(f"  downloaded {filename}")
                total_downloaded += 1
            except (urllib.error.URLError, TimeoutError, ValueError) as e:
                print(f"  WARNING: failed to download {filename}: {e}")
                total_errors += 1

    print()
    print(
        f"Done. {total_found} paper(s) found, {total_downloaded} downloaded, "
        f"{total_skipped} already up to date, {total_errors} error(s)."
    )


if __name__ == "__main__":
    main()
