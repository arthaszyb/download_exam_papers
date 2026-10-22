"""Download Singapore primary school exam papers from free test-paper sites.

Sources (``--sources``, default both):

* ``testpapersfree`` — www.testpapersfree.com. Crawl path: /<level>/ index (filtered by
  year, subject and exam type, paginated) -> show.php detail page -> .pdf link. The
  per-type pages (/ca1/, /ca2/) return an empty response, so the level index is used.
* ``sgexam`` — sgexam.com, a WordPress site. Posts are listed through its REST API
  (category ``primary-<n>``); each post links its PDF on Google Drive, which is then
  downloaded from drive.google.com.

Exam types are normalised to CA1 (WA1), SA1 (WA2 / SA1), CA2 (WA3), SA2 (SA2 / EOY);
anything else (practice papers, class tests, topical reviews) is OTHER.

A paper whose year, type and school already came from another source is skipped, so
running both sources does not fetch the same paper twice.

Usage:
    python exam_pdf_download.py --grades P5 --subjects English --years 2015-2025
    python exam_pdf_download.py --sources sgexam --years 2024 --dry-run
    python exam_pdf_download.py --sources sgexam --list-json papers.json   # list only
"""

import argparse
import html
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Optional
from urllib.parse import unquote, urljoin

import requests
from bs4 import BeautifulSoup
from requests.exceptions import RequestException

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

USER_AGENT = "exam-paper-downloader/2.1 (personal study use)"

#: Older papers follow a different syllabus and question format.
MIN_YEAR = 2015

ALL_STAGES = ["CA1", "SA1", "CA2", "SA2", "OTHER"]
ALL_SOURCES = ["testpapersfree", "sgexam"]

TPF_DOMAIN = "https://www.testpapersfree.com"
SGEXAM_DOMAIN = "https://sgexam.com"

#: Same school, different spellings across the two sites.
SCHOOL_ALIASES = {
    "anglochinese": "acs",
    "acsprimary": "acs",
    "acsp": "acs",
    "acsjunior": "acsj",
    "catholichigh": "catholic",
    # In primary-school paper lists a bare "CHIJ" is CHIJ St Nicholas Girls'.
    "chij": "chijnicholas",
    "chijstnicholas": "chijnicholas",
    "chijstnicholasgirls": "chijnicholas",
    "stnicholas": "chijnicholas",
    "marisstellahigh": "marisstella",
    "methodistgirls": "mgs",
    "payalebarmethodist": "plmgs",
    "payalebarmethodistgirls": "plmgs",
    "payalebarmgs": "plmgs",
    "mgspayalebar": "plmgs",
    # Raffles Girls' Primary is the only Raffles primary school.
    "raffles": "rgps",
    "rafflesgirls": "rgps",
    "singaporechinesegirls": "scgs",
    "sthildas": "sthilda",
}


@dataclass
class DownloadConfig:
    subjects: List[str] = field(default_factory=lambda: ["English"])
    grades: List[str] = field(default_factory=lambda: ["P5"])
    years: List[str] = field(default_factory=lambda: ["2024", "2025"])
    stages: List[str] = field(default_factory=lambda: list(ALL_STAGES))
    sources: List[str] = field(default_factory=lambda: list(ALL_SOURCES))
    download_root: str = os.path.join(os.path.expanduser("~"), "Downloads", "testpapersfree")
    delay: float = 1.5
    dry_run: bool = False
    list_json: Optional[str] = None


@dataclass
class Paper:
    source: str
    grade: str
    subject: str
    year: str
    stage: str
    school: str
    title: str
    page_url: str
    filename: str = ""
    pdf_url: str = ""
    drive_id: str = ""

    def key(self) -> str:
        return f"{self.grade}|{self.subject}|{self.year}|{self.stage}|{school_key(self.school)}"


class Fetcher:
    """One request at a time, with a pause between them."""

    def __init__(self, delay: float):
        self.delay = delay
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT

    def get(self, url: str, timeout: int = 30, **kwargs) -> Optional[requests.Response]:
        try:
            response = self.session.get(url, timeout=timeout, **kwargs)
            response.raise_for_status()
            return response
        except RequestException as exc:
            logging.error("Failed to fetch %s: %s", url, exc)
            return None
        finally:
            time.sleep(self.delay)


def school_key(name: str) -> str:
    key = re.sub(r"[^a-z0-9]", "", name.lower())
    key = re.sub(r"(primary|school|pdf)$", "", key)
    return SCHOOL_ALIASES.get(key, key)


def normalise_stage(label: str, year: str) -> str:
    """Map a paper's exam label to CA1 / SA1 / CA2 / SA2 / OTHER."""
    text = label.lower()
    wa = re.search(r"\b(?:weighted assessment|wa)\s*([123])\b", text)
    if wa:
        return {"1": "CA1", "2": "SA1", "3": "CA2"}[wa.group(1)]
    sa = re.search(r"\b(?:semestral assessment|sa)\s*([12])\b", text)
    if sa:
        return f"SA{sa.group(1)}"
    ca = re.search(r"\b(?:continual assessment|ca)\s*([12])\b", text)
    if ca:
        return f"CA{ca.group(1)}"
    if re.search(r"\b(end of year|eoy|final)\b", text):
        return "SA2"
    return "OTHER"


# --------------------------------------------------------------------------- #
# testpapersfree.com
# --------------------------------------------------------------------------- #

TPF_STAGE_PARAM = {"CA1": "CA1", "SA1": "SA1", "CA2": "CA2", "SA2": "SA2"}


def tpf_index_url(grade: str, year: str, subject: str, stage: str, page: int) -> str:
    return (
        f"{TPF_DOMAIN}/{grade.lower()}/index.php?level={grade}&year={year}&subject={subject}"
        f"&type={stage}&school=%25&Submit=Show+Test+Papers&page={page}"
    )


def tpf_list(fetcher: Fetcher, grade: str, subject: str, year: str, stage: str) -> List[Paper]:
    papers: List[Paper] = []
    seen = set()
    page = 1
    while True:
        response = fetcher.get(tpf_index_url(grade, year, subject, stage, page))
        if response is None:
            break
        soup = BeautifulSoup(response.text, "html.parser")
        new = 0
        for form in soup.find_all("form", action=lambda x: x and "show.php" in x):
            detail = urljoin(TPF_DOMAIN, form["action"].lstrip("."))
            if detail in seen:
                continue
            seen.add(detail)
            row = form.find_parent("tr")
            title = row.get_text(" | ", strip=True).split(" | ")[0] if row else ""
            school = title.split(" - ", 1)[1] if " - " in title else ""
            papers.append(Paper("testpapersfree", grade, subject, year, stage, school, title, detail))
            new += 1
        has_next = soup.find("a", href=lambda x: x and f"page={page + 1}" in x)
        if not new or not has_next:
            break
        page += 1
    return papers


def tpf_papers(fetcher: Fetcher, config: DownloadConfig, grade: str, subject: str) -> Iterator[Paper]:
    for year in config.years:
        for stage in config.stages:
            if stage not in TPF_STAGE_PARAM:
                continue
            papers = tpf_list(fetcher, grade, subject, year, stage)
            logging.info("testpapersfree %s %s %s %s: %d paper(s)", grade, subject, year, stage, len(papers))
            yield from papers


def tpf_resolve(fetcher: Fetcher, paper: Paper) -> bool:
    response = fetcher.get(paper.page_url)
    if response is None:
        return False
    soup = BeautifulSoup(response.text, "html.parser")
    link = soup.find("a", href=lambda x: x and x.lower().endswith(".pdf"))
    if not link:
        logging.warning("No PDF link on %s", paper.page_url)
        return False
    paper.pdf_url = urljoin(TPF_DOMAIN, link["href"])
    name = paper.pdf_url.rsplit("/", 1)[-1]
    if paper.year not in name:
        # Older files are named without a year and collide across years.
        name = f"{paper.year}_{name}"
    paper.filename = name
    return True


# --------------------------------------------------------------------------- #
# sgexam.com
# --------------------------------------------------------------------------- #

DRIVE_ID_RE = re.compile(r"drive\.google\.com/(?:uc\?[^\"'<>\s]*?id=|file/d/|open\?id=)([\w-]{20,})")


def sgexam_category_id(fetcher: Fetcher, grade: str) -> Optional[int]:
    slug = f"primary-{grade[1:]}"
    response = fetcher.get(f"{SGEXAM_DOMAIN}/wp-json/wp/v2/categories", params={"slug": slug})
    if response is None or not response.json():
        logging.error("sgexam: no category %s", slug)
        return None
    return response.json()[0]["id"]


def sgexam_papers(fetcher: Fetcher, config: DownloadConfig, grade: str, subject: str) -> Iterator[Paper]:
    category = sgexam_category_id(fetcher, grade)
    if category is None:
        return
    title_re = re.compile(
        rf"^(20\d\d)-{grade}-{re.escape(subject)}-(.+?)-([^-]+?)(?:\.pdf)?$", re.IGNORECASE
    )
    page, pages, count = 1, 1, 0
    while page <= pages:
        response = fetcher.get(
            f"{SGEXAM_DOMAIN}/wp-json/wp/v2/posts",
            params={"categories": category, "per_page": 100, "page": page,
                    "_fields": "title,link,content"},
        )
        if response is None:
            break
        pages = int(response.headers.get("X-WP-TotalPages", "1"))
        for post in response.json():
            title = html.unescape(post["title"]["rendered"]).strip()
            match = title_re.match(title)
            if not match:
                continue
            year, label, school = match.groups()
            if year not in config.years:
                continue
            stage = normalise_stage(label, year)
            if stage not in config.stages:
                continue
            # Page-builder shortcodes store the link URL-encoded.
            content = unquote(html.unescape(post["content"]["rendered"]))
            drive = DRIVE_ID_RE.search(content)
            if not drive:
                logging.warning("sgexam: no Drive link on %s", post["link"])
                continue
            filename = re.sub(r"[^\w.\- ]", "", title)
            if not filename.lower().endswith(".pdf"):
                filename += ".pdf"
            count += 1
            yield Paper(
                "sgexam", grade, subject, year, stage, school.strip(), title, post["link"],
                filename=filename, drive_id=drive.group(1),
                pdf_url=f"https://drive.google.com/uc?export=download&id={drive.group(1)}",
            )
        page += 1
    logging.info("sgexam %s %s: %d paper(s) in range", grade, subject, count)


def drive_download(fetcher: Fetcher, url: str) -> Optional[bytes]:
    """Download a public Drive file, passing the large-file confirmation page if shown."""
    response = fetcher.get(url, timeout=120)
    if response is None:
        return None
    if response.content[:5] == b"%PDF-":
        return response.content
    soup = BeautifulSoup(response.text, "html.parser")
    form = soup.find("form", id="download-form") or soup.find("form")
    if form is None:
        logging.error("Drive returned no file and no confirmation form for %s", url)
        return None
    params = {i["name"]: i.get("value", "") for i in form.find_all("input") if i.get("name")}
    confirmed = fetcher.get(form.get("action", url), timeout=120, params=params)
    if confirmed is not None and confirmed.content[:5] == b"%PDF-":
        return confirmed.content
    logging.error("Drive download did not return a PDF for %s", url)
    return None


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #

SOURCES = {
    "testpapersfree": (tpf_papers, tpf_resolve),
    "sgexam": (sgexam_papers, lambda fetcher, paper: True),
}


def main(config: DownloadConfig) -> None:
    too_old = [y for y in config.years if int(y) < MIN_YEAR]
    if too_old:
        raise SystemExit(f"Years before {MIN_YEAR} are not supported: {', '.join(too_old)}")

    fetcher = Fetcher(config.delay)
    listed: List[Dict] = []
    downloaded = skipped = duplicates = 0
    for grade in config.grades:
        for subject in config.subjects:
            save_dir = os.path.join(config.download_root, grade, subject)
            os.makedirs(save_dir, exist_ok=True)
            manifest_path = os.path.join(save_dir, "_manifest.json")
            manifest: Dict[str, Dict] = {}
            if os.path.isfile(manifest_path):
                with open(manifest_path, encoding="utf-8") as fh:
                    manifest = json.load(fh)
            existing = {name.lower() for name in os.listdir(save_dir)}
            for entry in manifest.values():
                # Entries written before the key existed (testpapersfree only).
                if not entry.get("key") and entry.get("year") and " - " in entry.get("title", ""):
                    school = entry["title"].split(" - ", 1)[1]
                    entry["key"] = f"{grade}|{subject}|{entry['year']}|{entry['stage']}|{school_key(school)}"
                    entry.setdefault("source", "testpapersfree")
            keys = {entry["key"]: entry.get("source", "testpapersfree")
                    for entry in manifest.values() if entry.get("key")}

            for source in config.sources:
                list_papers, resolve = SOURCES[source]
                for paper in list_papers(fetcher, config, grade, subject):
                    # Within one source, several OTHER papers can share a key.
                    other_source = keys.get(paper.key())
                    if paper.stage != "OTHER" and other_source and other_source != source:
                        logging.info("Duplicate of %s paper, skipping: %s", other_source, paper.title)
                        duplicates += 1
                        continue
                    if not resolve(fetcher, paper):
                        continue
                    if config.list_json is not None:
                        if paper.filename.lower() in existing:
                            continue
                        existing.add(paper.filename.lower())
                        listed.append({**paper.__dict__, "key": paper.key()})
                        keys.setdefault(paper.key(), source)
                        continue
                    if paper.filename.lower() in existing:
                        keys.setdefault(paper.key(), source)
                        skipped += 1
                        continue
                    if config.dry_run:
                        logging.info("Would download %s", paper.filename)
                        downloaded += 1
                        continue
                    if source == "sgexam":
                        content = drive_download(fetcher, paper.pdf_url)
                    else:
                        response = fetcher.get(paper.pdf_url, timeout=60)
                        content = response.content if response is not None else None
                    if not content:
                        continue
                    with open(os.path.join(save_dir, paper.filename), "wb") as fh:
                        fh.write(content)
                    existing.add(paper.filename.lower())
                    keys[paper.key()] = source
                    manifest[paper.filename] = {
                        "source": source, "key": paper.key(), "title": paper.title,
                        "page_url": paper.page_url, "pdf_url": paper.pdf_url,
                        "grade": grade, "subject": subject, "year": paper.year,
                        "stage": paper.stage, "school": paper.school, "bytes": len(content),
                    }
                    # Saved after every file so an interrupted run keeps its record.
                    with open(manifest_path, "w", encoding="utf-8") as fh:
                        json.dump(manifest, fh, indent=2, ensure_ascii=False)
                    downloaded += 1
                    logging.info("Downloaded %s (%d KB)", paper.filename, len(content) // 1024)

    if config.list_json is not None:
        with open(config.list_json, "w", encoding="utf-8") as fh:
            json.dump(listed, fh, indent=1, ensure_ascii=False)
        logging.info("Listed %d paper(s) to %s, %d duplicate(s) skipped",
                     len(listed), config.list_json, duplicates)
        return
    logging.info("Done: %d downloaded, %d already present, %d duplicate(s) across sources",
                 downloaded, skipped, duplicates)


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


def _csv(value: str, upper: bool = False) -> List[str]:
    items = [v.strip() for v in value.split(",") if v.strip()]
    return [v.upper() for v in items] if upper else items


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sources", default=",".join(ALL_SOURCES), help="testpapersfree,sgexam")
    ap.add_argument("--grades", default="P5", help="comma-separated, e.g. P4,P5")
    ap.add_argument("--subjects", default="English", help="comma-separated, e.g. English,Science")
    ap.add_argument("--years", default="2024-2025", help="e.g. 2015-2025 or 2023,2024")
    ap.add_argument("--stages", default=",".join(ALL_STAGES), help="CA1,SA1,CA2,SA2,OTHER")
    ap.add_argument("--out", default=DownloadConfig().download_root)
    ap.add_argument("--delay", type=float, default=1.5, help="seconds between requests")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--list-json", help="write the papers found to this JSON file; download nothing")
    args = ap.parse_args()
    unknown = set(_csv(args.sources)) - set(ALL_SOURCES)
    if unknown:
        ap.error(f"unknown source(s): {', '.join(sorted(unknown))}")
    main(
        DownloadConfig(
            subjects=_csv(args.subjects),
            grades=_csv(args.grades, upper=True),
            years=_years(args.years),
            stages=_csv(args.stages, upper=True),
            sources=_csv(args.sources),
            download_root=os.path.expanduser(args.out),
            delay=args.delay,
            dry_run=args.dry_run,
            list_json=args.list_json,
        )
    )
