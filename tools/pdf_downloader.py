from pathlib import Path
from urllib.parse import urlparse

import pymupdf
import requests


def download_paper(paper: dict, output_dir=None):
    paper_id = paper["id"].split("/")[-1]

    output_dir = Path(output_dir or "data/papers")
    output_dir.mkdir(parents=True, exist_ok=True)

    pdf_path = output_dir / f"{paper_id}.pdf"
    text_path = output_dir / f"{paper_id}.txt"
    temp_path = output_dir / f"{paper_id}.part"

    # Avoid downloading already processed papers
    if pdf_path.exists() and text_path.exists() and text_path.stat().st_size > 0:
        print("Already downloaded.")
        return str(text_path)

    urls = [url for url in paper.get("pdf_urls", []) if urlparse(url).scheme == "https"]
    if paper_id.startswith("W") and not urls:
        response = requests.get(
            f"https://api.openalex.org/works/{paper_id}", timeout=30
        )
        response.raise_for_status()
        work = response.json()
    elif paper.get("doi") and not urls:
        response = requests.get(
            "https://api.openalex.org/works",
            params={"filter": f"doi:{paper['doi']}", "per_page": 1},
            timeout=30,
        )
        response.raise_for_status()
        work = next(iter(response.json().get("results", [])), {})
    else:
        work = {}
    for location in [work.get("best_oa_location"), *work.get("locations", [])]:
        if location and location.get("is_oa"):
            url = location.get("pdf_url")
            if url and urlparse(url).scheme == "https" and url not in urls:
                urls.append(url)

    if not urls:
        print("No open-access PDF URL found.")
        return None

    print(f"Found {len(urls)} PDF candidate(s).", flush=True)

    for index, url in enumerate(urls, start=1):
        print(f"Trying source {index}/{len(urls)}...", flush=True)

        try:
            with requests.get(
                url,
                timeout=30,
                stream=True,
                headers={"User-Agent": "AgenticReview/0.1"},
            ) as response:
                response.raise_for_status()

                size = 0

                with temp_path.open("wb") as file:
                    for chunk in response.iter_content(8192):
                        size += len(chunk)

                        if size > 30 * 1024 * 1024:
                            raise ValueError("File too large")

                        file.write(chunk)

            # Validate PDF before processing
            with temp_path.open("rb") as file:
                if not file.read(5).startswith(b"%PDF-"):
                    raise ValueError("Response is not a PDF")

            with pymupdf.open(temp_path) as doc:
                text = "\n".join(page.get_text() for page in doc)

            if not text.strip():
                raise ValueError("PDF contains no extractable text")

            temp_path.replace(pdf_path)
            text_path.write_text(text, encoding="utf-8")

            print(f"Success: {pdf_path.name}")
            return str(text_path)

        except (requests.RequestException, ValueError, RuntimeError, OSError) as error:
            print(f"Source failed: {error}")
            temp_path.unlink(missing_ok=True)

    print(f"No usable PDF found for {paper_id}.")
    return None
