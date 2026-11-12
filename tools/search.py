"""Paginated public academic APIs, provenance, retries and cross-source deduplication."""

import hashlib
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from tools.openalex import reconstruct_abstract


def session():
    client = requests.Session()
    client.headers.update({"User-Agent": "FolioReview/0.2 (academic review prototype)"})
    client.mount(
        "https://",
        HTTPAdapter(
            max_retries=Retry(
                total=2,
                backoff_factor=1,
                status_forcelist=[429, 500, 502, 503, 504],
                respect_retry_after_header=True,
            )
        ),
    )
    return client


class SearchPageError(requests.RequestException):
    def __init__(self, records, pages, message):
        super().__init__(message)
        self.records = list(records)
        self.pages = list(pages)


def fetch(client, url, params, records, pages):
    try:
        response = client.get(url, params=params, timeout=30)
        response.raise_for_status()
        return response
    except requests.RequestException as error:
        status = (
            error.response.status_code if error.response is not None else "unavailable"
        )
        safe = {k: v for k, v in params.items() if k != "api_key"}
        raise SearchPageError(
            records,
            pages + [{"params": safe, "error": f"HTTP {status}"}],
            f"{type(error).__name__}: source request failed (HTTP {status})",
        ) from error


def payload(response, records, pages, xml=False):
    try:
        return ET.fromstring(response.text) if xml else response.json()
    except (ValueError, ET.ParseError) as error:
        raise SearchPageError(
            records, pages, "Invalid source response; partial records retained"
        ) from error


def text(element, path):
    node = element.find(path)
    return " ".join(node.itertext()).strip() if node is not None else ""


def openalex(client, query, protocol):
    cursor, records, pages = "*", [], []
    while cursor and len(records) < protocol.max_records_per_query:
        params = {
            "search": query,
            "per_page": min(100, protocol.max_records_per_query - len(records)),
            "cursor": cursor,
        }
        filters = []
        if protocol.date_from:
            filters.append(f"from_publication_date:{protocol.date_from}")
        if protocol.date_to:
            filters.append(f"to_publication_date:{protocol.date_to}")
        if filters:
            params["filter"] = ",".join(filters)
        if os.getenv("OPENALEX_API_KEY"):
            params["api_key"] = os.environ["OPENALEX_API_KEY"]
        response = fetch(
            client, "https://api.openalex.org/works", params, records, pages
        )
        data = payload(response, records, pages)
        pages.append(
            {
                "params": {k: v for k, v in params.items() if k != "api_key"},
                "returned": len(data.get("results", [])),
                "total_matches": data.get("meta", {}).get("count"),
            }
        )
        for work in data.get("results", []):
            records.append(
                {
                    "id": work["id"],
                    "title": work.get("title") or "Untitled",
                    "year": work.get("publication_year"),
                    "doi": work.get("doi"),
                    "authors": [
                        a.get("author", {}).get("display_name", "")
                        for a in work.get("authorships", [])
                    ],
                    "abstract": reconstruct_abstract(
                        work.get("abstract_inverted_index")
                    ),
                    "pdf_urls": list(
                        dict.fromkeys(
                            loc["pdf_url"]
                            for loc in work.get("locations", [])
                            if loc and loc.get("is_oa") and loc.get("pdf_url")
                        )
                    ),
                    "source": "openalex",
                }
            )
        next_cursor = data.get("meta", {}).get("next_cursor")
        if not data.get("results") or next_cursor == cursor:
            break
        cursor = next_cursor
    return records, pages


def pubmed(client, query, protocol):
    records, pages, start = [], [], 0
    while len(records) < protocol.max_records_per_query:
        params = {
            "db": "pubmed",
            "term": query,
            "retmode": "json",
            "retstart": start,
            "retmax": min(100, protocol.max_records_per_query - len(records)),
            "datetype": "pdat",
        }
        if protocol.date_from:
            params["mindate"] = str(protocol.date_from).replace("-", "/")
        if protocol.date_to:
            params["maxdate"] = str(protocol.date_to).replace("-", "/")
        r = fetch(
            client,
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
            params,
            records,
            pages,
        )
        data = payload(r, records, pages)["esearchresult"]
        ids = data.get("idlist", [])
        pages.append(
            {
                "params": {k: v for k, v in params.items() if k != "api_key"},
                "returned": len(ids),
                "total_matches": int(data.get("count", 0)),
            }
        )
        if not ids:
            break
        time.sleep(0.35)
        r = fetch(
            client,
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
            {"db": "pubmed", "id": ",".join(ids), "retmode": "xml"},
            records,
            pages,
        )
        for article in payload(r, records, pages, xml=True).findall(".//PubmedArticle"):
            pmid = text(article, ".//PMID")
            doi = next(
                (
                    n.text
                    for n in article.findall(".//ArticleId")
                    if n.get("IdType") == "doi"
                ),
                None,
            )
            records.append(
                {
                    "id": f"P{pmid}",
                    "landing_url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                    "title": text(article, ".//ArticleTitle"),
                    "year": int(text(article, ".//PubDate/Year") or 0) or None,
                    "doi": doi,
                    "authors": [
                        " ".join(
                            filter(None, [text(a, "ForeName"), text(a, "LastName")])
                        )
                        for a in article.findall(".//Author")
                    ],
                    "abstract": " ".join(
                        " ".join(n.itertext())
                        for n in article.findall(".//AbstractText")
                    )
                    or None,
                    "source": "pubmed",
                    "pdf_urls": [],
                }
            )
        start += len(ids)
        if start >= int(data.get("count", 0)):
            break
        time.sleep(0.35)
    return records, pages


def arxiv(client, query, protocol):
    records, pages, start = [], [], 0
    if protocol.date_from or protocol.date_to:
        lo = (
            str(protocol.date_from).replace("-", "")
            if protocol.date_from
            else "19000101"
        ) + "0000"
        hi = (
            str(protocol.date_to).replace("-", "") if protocol.date_to else "29991231"
        ) + "2359"
        query += f" AND submittedDate:[{lo} TO {hi}]"
    ns = {
        "a": "http://www.w3.org/2005/Atom",
        "o": "http://a9.com/-/spec/opensearch/1.1/",
    }
    while len(records) < protocol.max_records_per_query:
        params = {
            "search_query": query,
            "start": start,
            "max_results": min(100, protocol.max_records_per_query - len(records)),
        }
        r = client.get("https://export.arxiv.org/api/query", params=params, timeout=30)
        r.raise_for_status()
        root = ET.fromstring(r.text)
        entries = root.findall("a:entry", ns)
        pages.append(
            {
                "params": {k: v for k, v in params.items() if k != "api_key"},
                "returned": len(entries),
                "total_matches": int(root.findtext("o:totalResults", "0", ns)),
            }
        )
        for entry in entries:
            url = entry.findtext("a:id", "", ns)
            if "/api/errors" in url:
                raise SearchPageError(
                    records, pages, "arXiv returned an API error entry"
                )
            code = re.sub(r"v\d+$", "", url.split("/abs/")[-1])
            key = "A" + hashlib.sha256(code.encode()).hexdigest()[:16]
            records.append(
                {
                    "id": key,
                    "landing_url": url,
                    "title": " ".join(entry.findtext("a:title", "", ns).split()),
                    "year": int(entry.findtext("a:published", "0000", ns)[:4]) or None,
                    "doi": entry.findtext("{http://arxiv.org/schemas/atom}doi"),
                    "authors": [
                        a.findtext("a:name", "", ns)
                        for a in entry.findall("a:author", ns)
                    ],
                    "abstract": " ".join(entry.findtext("a:summary", "", ns).split()),
                    "source": "arxiv",
                    "pdf_urls": [f"https://arxiv.org/pdf/{code}"],
                }
            )
        start += len(entries)
        if not entries or start >= int(root.findtext("o:totalResults", "0", ns)):
            break
        time.sleep(3)
    return records, pages


def normalize_doi(value):
    return re.sub(
        r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", (value or "").strip().lower()
    ).rstrip(".")


def deduplicate(records):
    unique, duplicates, aliases = [], [], {}
    for record in records:
        doi = normalize_doi(record.get("doi"))
        title = re.sub(r"[^\w]+", "", (record.get("title") or "").casefold())
        keys = ["id:" + record["id"]]
        if doi:
            keys.append("doi:" + doi)
        authors = record.get("authors") or []
        author = re.sub(r"[^\w]+", "", authors[0].casefold()) if authors else ""
        if title and len(title) >= 20 and record.get("year") and author:
            keys.append("title:" + title + ":" + str(record["year"]) + ":" + author)
        match = next(
            (
                aliases[k]
                for k in keys
                if k in aliases
                and not (
                    k.startswith("title:")
                    and doi
                    and normalize_doi(unique[aliases[k]].get("doi"))
                    and doi != normalize_doi(unique[aliases[k]].get("doi"))
                )
            ),
            None,
        )
        if match is not None:
            existing = unique[match]
            duplicates.append(
                {
                    "duplicate_id": record["id"],
                    "retained_id": existing["id"],
                    "matched_keys": [k for k in keys if k in aliases],
                }
            )
            existing["provenance"] = existing.get("provenance", []) + record.get(
                "provenance", []
            )
            existing["pdf_urls"] = list(
                dict.fromkeys(existing.get("pdf_urls", []) + record.get("pdf_urls", []))
            )
            if not existing.get("abstract"):
                existing["abstract"] = record.get("abstract")
            for key in keys:
                aliases[key] = match
        else:
            for key in keys:
                aliases[key] = len(unique)
            unique.append(dict(record))
    return unique, duplicates


def retrieve(protocol, queries):
    raw, log = [], []
    handlers = {"openalex": openalex, "pubmed": pubmed, "arxiv": arxiv}
    with session() as client:
        for source in protocol.sources:
            for query in dict.fromkeys(queries[source]):
                event = {
                    "source": source,
                    "query": query,
                    "timestamp": datetime.now(UTC).isoformat(),
                    "records": 0,
                    "error": None,
                    "pages": [],
                }
                records, pages = [], []
                try:
                    records, pages = handlers[source](client, query, protocol)
                except SearchPageError as error:
                    records, pages = error.records, error.pages
                    event["error"] = str(error)
                except (
                    requests.RequestException,
                    ValueError,
                    KeyError,
                    ET.ParseError,
                ) as error:
                    event["error"] = str(error)
                event.update(
                    records=len(records),
                    pages=pages,
                    limit_reached=len(records) >= protocol.max_records_per_query,
                )
                totals = [
                    p["total_matches"]
                    for p in pages
                    if isinstance(p.get("total_matches"), int)
                ]
                event["truncated"] = (
                    max(totals) > len(records) if totals else event["limit_reached"]
                )
                for record in records:
                    record["provenance"] = [
                        {
                            "source": source,
                            "query": query,
                            "timestamp": event["timestamp"],
                        }
                    ]
                raw.extend(records)
                log.append(event)
    papers, duplicates = deduplicate(raw)
    return {
        "papers": papers,
        "raw_records": raw,
        "duplicates": duplicates,
        "search_log": log,
    }
