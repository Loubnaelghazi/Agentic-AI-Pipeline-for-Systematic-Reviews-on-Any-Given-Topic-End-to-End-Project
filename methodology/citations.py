"""Readable manuscript references; provenance identifiers stay in source artifacts."""

import re


def readable_citations(manuscript, papers):
    references = {}
    for paper in papers:
        pid = str(paper.get("id") or paper.get("paper_id") or "").rsplit("/", 1)[-1]
        if pid and pid not in references:
            references[pid] = (len(references) + 1, paper)

    lines = []
    for line in manuscript.splitlines():
        # Verbatim scientific quotations must remain unchanged.
        if line.lstrip().startswith(">"):
            lines.append(line)
            continue
        for pid, (number, paper) in references.items():
            heading = re.fullmatch(r"(#{1,6})\s+" + re.escape(pid) + r"\s*", line)
            if heading:
                title = paper.get("title") or "Article title unavailable"
                year = f" ({paper['year']})" if paper.get("year") else ""
                line = f"{heading[1]} [{number}] {title}{year}"
                break
        # Never change source URLs, including an OpenAlex fallback URL.
        pieces = re.split(r"(https?://[^\s<>]+)", line)
        for index in range(0, len(pieces), 2):
            text = pieces[index]
            for pid, (number, _) in references.items():
                key = re.escape(pid)
                text = re.sub(
                    r"\[" + key + r"(?::[\w:-]+)?;\s*([^\]]+)\]",
                    lambda match, n=number: f"[{n}; {match[1]}]",
                    text,
                )
                text = re.sub(r"\[" + key + r"(?::[\w:-]+)?\]", f"[{number}]", text)
                text = re.sub(r"(?<![\w/])" + key + r"(?!\w)", f"[{number}]", text)
            pieces[index] = text
        lines.append("".join(pieces))
    return "\n".join(lines) + ("\n" if manuscript.endswith("\n") else "")
