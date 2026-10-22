# download_exam_papers
## Description
Downloads Singapore primary school exam papers (PDF) from free test-paper sites. Thanks to those websites.

Sources:
* **testpapersfree** — www.testpapersfree.com
* **sgexam** — sgexam.com (PDFs are hosted on Google Drive, so `drive.google.com` must be reachable)

A paper with the same year, exam type and school from both sites is downloaded only once
(school spellings are normalised, e.g. "St Nicholas" = "CHIJ St Nicholas", "Raffles" = "Raffles Girls").

## Install
```
pip install -r requirements.txt
```

## Usage
```
python exam_pdf_download.py --grades P5 --subjects English --years 2015-2025
python exam_pdf_download.py --sources sgexam --years 2024 --dry-run
python exam_pdf_download.py --sources sgexam --list-json papers.json   # list only, no download
```

Options:
* `--sources`: `testpapersfree`, `sgexam`, comma-separated (default: both, in that order).
* `--grades`: P1–P6, comma-separated.
* `--subjects`: English, Chinese, Maths, Science, ... comma-separated.
* `--years`: a range (`2015-2025`) or a list (`2023,2024`). Years before 2015 are refused.
* `--stages`: `CA1` (WA1), `SA1` (WA2 / SA1), `CA2` (WA3), `SA2` (SA2 / EOY), `OTHER`
  (practice papers, class tests, reviews). Default: all.
* `--out`: download folder (default `~/Downloads/testpapersfree`); files go into `<out>/<grade>/<subject>/`.
* `--delay`: seconds between requests (default 1.5).
* `--list-json`: write what would be fetched (with Drive IDs for sgexam) to a JSON file instead of downloading.

Files already in the target folder are skipped, so re-running only fetches new papers.
Each folder gets a `_manifest.json` recording the source of every file; it is saved after each download.
