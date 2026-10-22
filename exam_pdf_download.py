"""Download Singapore primary school exam papers from testpapersfree.com.

Crawl path: /<level>/ index (filtered by year, subject and exam type, paginated)
-> show.php detail page -> .pdf link.

The per-type pages (/ca1/, /ca2/) return an empty response from the server, so the
level index (/p5/ etc.) is used instead. Its exam-type filter maps as:
CA1 = WA1, SA1 = WA2 (or SA1 in older years), CA2 = WA3, SA2 = SA2/EOY.

Usage:
    python exam_pdf_download.py --grades P5 --subjects English --years 2015-2025
    python exam_pdf_download.py --grades P5 --subjects English --years 2024 --dry-run
"""

import argparse
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from requests.exceptions import RequestException

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

DOMAIN = "https://www.testpapersfree.com"
USER_AGENT = "exam-paper-downloader/2.0 (personal study use)"

#: Older papers follow a different syllabus and question format.
MIN_YEAR = 2015

ALL_STAGES = ["CA1", "SA1", "CA2", "SA2"]


@dataclass
class DownloadConfig:
    subjects: List[str] = field(default_factory=lambda: ["English"])
    grades: List[str] = field(default_factory=lambda: ["P5"])
    years: List[str] = field(default_factory=lambda: ["2024", "2025"])
    stages: List[str] = field(default_factory=lambda: list(ALL_STAGES))
    download_root: str = os.path.join(os.path.expanduser("~"), "Downloads", "testpapersfree")
    delay: float = 1.5
    dry_run: bool = False


class Fetcher:
    """One request at a time, with a pause between them."""

    def __init__(self, delay: float):
        self.delay = delay
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT

    def get(self, url: str, timeout: int = 30) -> Optional[requests.Response]:
        try:
            response = self.session.get(url, timeout=timeout)
            response.raise_for_status()
            return response
        except RequestException as exc:
            logging.error("Failed to fetch %s: %s", url, exc)
            return None
        finally:
            time.sleep(self.delay)


def index_url(grade: str, year: str, subject: str, stage: str, page: int) -> str:
    return (
        f"{DOMAIN}/{grade.lower()}/index.php?level={grade}&year={year}&subject={subject}"
        f"&type={stage}&school=%25&Submit=Show+Test+Papers&page={page}"
    )


def list_papers(fetcher: Fetcher, grade: str, year: str, subject: str, stage: str) -> List[Dict]:
    """Return [{title, detail_url}] for every page of one index listing."""
    papers: List[Dict] = []
    seen = set()
    page = 1
    while True:
        response = fetcher.get(index_url(grade, year, subject, stage, page))
        if response is None:
            break
        soup = BeautifulSoup(response.text, "html.parser")
        new = 0
        for form in soup.find_all("form", action=lambda x: x and "show.php" in x):
            detail = urljoin(DOMAIN, form["action"].lstrip("."))
            if detail in seen:
                continue
            seen.add(detail)
            row = form.find_parent("tr")
            title = row.get_text(" | ", strip=True).split(" | ")[0] if row else ""
            papers.append({"title": title, "detail_url": detail})
            new += 1
        has_next = soup.find("a", href=lambda x: x and f"page={page + 1}" in x)
        if not new or not has_next:
            break
        page += 1
    return papers


def pdf_link(fetcher: Fetcher, detail_url: str) -> Optional[str]:
    response = fetcher.get(detail_url)
    if response is None:
        return None
    soup = BeautifulSoup(response.text, "html.parser")
    link = soup.find("a", href=lambda x: x and x.lower().endswith(".pdf"))
    return urljoin(DOMAIN, link["href"]) if link else None


def main(config: DownloadConfig) -> None:
    too_old = [y for y in config.years if int(y) < MIN_YEAR]
    if too_old:
        raise SystemExit(f"Years before {MIN_YEAR} are not supported: {', '.join(too_old)}")

    fetcher = Fetcher(config.delay)
    downloaded = skipped = 0
    for grade in config.grades:
        for subject in config.subjects:
            save_dir = os.path.join(config.download_root, grade, subject)
            os.makedirs(save_dir, exist_ok=True)
            manifest_path = os.path.join(save_dir, "_manifest.json")
            manifest = {}
            if os.path.isfile(manifest_path):
                with open(manifest_path, encoding="utf-8") as fh:
                    manifest = json.load(fh)
            existing = {name.lower() for name in os.listdir(save_dir)}

            for year in config.years:
                for stage in config.stages:
                    papers = list_papers(fetcher, grade, year, subject, stage)
                    logging.info("%s %s %s %s: %d paper(s)", grade, subject, year, stage, len(papers))
                    for paper in papers:
                        url = pdf_link(fetcher, paper["detail_url"])
                        if not url:
                            logging.warning("No PDF link on %s", paper["detail_url"])
                            continue
                        name = url.rsplit("/", 1)[-1]
                        if year not in name:
                            # Older files are named without a year and collide across years.
                            name = f"{year}_{name}"
                        if name.lower() in existing:
                            skipped += 1
                            continue
                        if config.dry_run:
                            logging.info("Would download %s", name)
                            downloaded += 1
                            continue
                        response = fetcher.get(url, timeout=60)
                        if response is None:
                            continue
                        with open(os.path.join(save_dir, name), "wb") as fh:
                            fh.write(response.content)
                        existing.add(name.lower())
                        manifest[name] = {
                            "title": paper["title"],
                            "detail_url": paper["detail_url"],
                            "pdf_url": url,
                            "grade": grade,
                            "subject": subject,
                            "year": year,
                            "stage": stage,
                            "bytes": len(response.content),
                        }
                        downloaded += 1
                        logging.info("Downloaded %s (%d KB)", name, len(response.content) // 1024)

            if manifest and not config.dry_run:
                with open(manifest_path, "w", encoding="utf-8") as fh:
                    json.dump(manifest, fh, indent=2, ensure_ascii=False)

    logging.info("Done: %d downloaded, %d already present", downloaded, skipped)


def _years(spec: str) -> List[str]:
    years: List[str] = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            start, end = part.split("-")
            years.extend(str(y) for y in range(int(start), int(end) + 1))
        elif part:
            years.append(part)
    return years


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--grades", default="P5", help="comma-separated, e.g. P4,P5")
    ap.add_argument("--subjects", default="English", help="comma-separated, e.g. English,Science")
    ap.add_argument("--years", default="2024-2025", help="e.g. 2015-2025 or 2023,2024")
    ap.add_argument("--stages", default=",".join(ALL_STAGES), help="CA1,SA1,CA2,SA2")
    ap.add_argument("--out", default=DownloadConfig().download_root)
    ap.add_argument("--delay", type=float, default=1.5, help="seconds between requests")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    main(
        DownloadConfig(
            subjects=[s.strip() for s in args.subjects.split(",") if s.strip()],
            grades=[g.strip().upper() for g in args.grades.split(",") if g.strip()],
            years=_years(args.years),
            stages=[s.strip().upper() for s in args.stages.split(",") if s.strip()],
            download_root=os.path.expanduser(args.out),
            delay=args.delay,
            dry_run=args.dry_run,
        )
    )
