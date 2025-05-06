import os
import logging
from dataclasses import dataclass, field
from typing import List
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
from requests.exceptions import RequestException

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

@dataclass
class DownloadConfig:
    subjects: List[str] = field(default_factory=lambda: ["Maths", "Chinese", "English", "Science"])
    grades: List[str] = field(default_factory=lambda: ["P4", "P5", "P6"])
    years: List[str] = field(default_factory=lambda: ["2019", "2020", "2021"])
    stages: List[str] = field(default_factory=lambda: ["ca1", "sa1", "ca2", "sa2"])
    domain_name: str = "https://www.testpapersfree.com"
    download_root: str = os.path.join(os.path.expanduser("~"), "Downloads", "testpapersfree")

def download_pdf(url: str, save_dir: str) -> None:
    """
    Download a PDF from the given URL and save it to the specified directory.
    Create the directory if it does not exist.
    """
    os.makedirs(save_dir, exist_ok=True)
    filename = url.split("/")[-1]
    file_path = os.path.join(save_dir, filename)
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        with open(file_path, "wb") as pdf_file:
            pdf_file.write(response.content)
        logging.info("PDF downloaded: %s", file_path)
    except RequestException as exc:
        logging.error("Failed to download %s: %s", url, exc)

def parse_html(url: str) -> BeautifulSoup:
    """
    Parse the HTML content of the given URL using BeautifulSoup and return the parsed content.
    """
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return BeautifulSoup(response.text, "html.parser")
    except RequestException as exc:
        logging.error("Failed to fetch %s: %s", url, exc)
        return BeautifulSoup("", "html.parser")

def get_paper_detail_urls(soup: BeautifulSoup, domain_name: str) -> List[str]:
    """
    Extract all paper detail URLs from the soup object.
    """
    forms = soup.find_all("form", action=lambda x: x and "show.php" in x)
    return [urljoin(domain_name, form["action"].lstrip("..")) for form in forms]

def main(config: DownloadConfig) -> None:
    """
    Main function to download exam papers.
    """
    for grade in config.grades:
        for subject in config.subjects:
            for year in config.years:
                for stage in config.stages:
                    download_dir = os.path.join(config.download_root, grade, subject)
                    paper_list_url = (
                        f"{config.domain_name}/{stage}/?level={grade}&year={year}"
                        f"&subject={subject}&type={stage}&school=%25&Submit=Show+Test+Papers"
                    )
                    soup = parse_html(paper_list_url)
                    paper_detail_urls = get_paper_detail_urls(soup, config.domain_name)
                    if not paper_detail_urls:
                        logging.warning("No exam paper found for %s", paper_list_url)
                        continue
                    for detail_url in paper_detail_urls:
                        soup_detail = parse_html(detail_url)
                        pdf_link = soup_detail.find("a", href=lambda x: x and x.endswith(".pdf"))
                        if pdf_link:
                            pdf_url = urljoin(config.domain_name, pdf_link["href"])
                            logging.info("Found PDF: %s", pdf_url)
                            download_pdf(pdf_url, download_dir)
                        else:
                            logging.warning("No PDF link found for %s", detail_url)

if __name__ == "__main__":
    # 可根据需要自定义参数
    config = DownloadConfig(
        subjects=["Chinese", "English", "Science"],
        grades=["P3"],
        years=["2023"],
        stages=["sa2"]
    )
    main(config)