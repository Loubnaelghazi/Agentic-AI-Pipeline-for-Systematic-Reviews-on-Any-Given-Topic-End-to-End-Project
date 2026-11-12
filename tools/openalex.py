import requests


def reconstruct_abstract(inverted_index):
    if not inverted_index:
        return None

    words = {}

    for word, positions in inverted_index.items():
        for position in positions:
            words[position] = word

    return " ".join(words[i] for i in sorted(words))


def search_papers(topic: str, limit: int = 10):
    url = "https://api.openalex.org/works"

    params = {
        "search": topic,
        "per-page": limit,
    }

    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()

    data = response.json()
    papers = []

    for work in data.get("results", []):
        papers.append(
            {
                "id": work.get("id"),
                "title": work.get("title"),
                "year": work.get("publication_year"),
                "doi": work.get("doi"),
                "authors": [
                    author["author"]["display_name"]
                    for author in work.get("authorships", [])
                ],
                "abstract": reconstruct_abstract(work.get("abstract_inverted_index")),
            }
        )

    return papers
