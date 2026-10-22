# download_exam_papers
## Description
Downloads Singapore primary school exam papers (PDF) from testpapersfree.com. Thanks to that website.

## Install
```
pip install -r requirements.txt
```

## Usage
```
python exam_pdf_download.py --grades P5 --subjects English --years 2015-2025
python exam_pdf_download.py --grades P5 --subjects English --years 2024 --stages CA1,SA1 --dry-run
```

Options:
* `--grades`: P1–P6, comma-separated.
* `--subjects`: English, Chinese, Maths, Science, ... comma-separated.
* `--years`: a range (`2015-2025`) or a list (`2023,2024`). Years before 2015 are refused.
* `--stages`: `CA1` (WA1), `SA1` (WA2 / SA1), `CA2` (WA3), `SA2` (SA2 / EOY). Default: all four.
* `--out`: download folder (default `~/Downloads/testpapersfree`); files go into `<out>/<grade>/<subject>/`.
* `--delay`: seconds between requests (default 1.5).

Files already in the target folder are skipped, so re-running only fetches new papers.
Each folder gets a `_manifest.json` recording where every file came from.
