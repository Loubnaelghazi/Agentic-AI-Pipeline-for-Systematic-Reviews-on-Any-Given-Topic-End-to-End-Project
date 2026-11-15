"""Read-only review inspection and optional machine audit, never a human-reference benchmark.

python -m evaluation.audit_review REVIEW_ID OUTPUT_DIR [--inference] [--profile prediction]
"""

import argparse
import hashlib
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from agents.grounding import validate_record
from methodology.protocol import Protocol, load_protocol
from storage.human_review import read_json, validate_record_source
from storage.review_manager import get_review_path, write_json


def inspect_review(review_id):
    from agents.writing_agent import writing_status

    root = get_review_path(review_id)
    out = root / "outputs"
    state = read_json(root / "workflow_state.json", {})
    records = read_json(out / "evidence.json", [])
    papers = read_json(root / "papers.json", [])
    source_checks = []
    for record in records:
        try:
            validate_record_source(review_id, record)
            claims = validate_record(record, review_id)
            source_checks.append(
                {
                    "paper_id": record["paper_id"],
                    "passed": bool(claims),
                    "matched_claims": len(claims),
                }
            )
        except (OSError, ValueError, KeyError, RuntimeError) as error:
            source_checks.append(
                {"paper_id": record["paper_id"], "passed": False, "error": str(error)}
            )
    word = []
    for name in (
        "automatic_review.docx",
        "literature_review.docx",
        "technical_report.docx",
    ):
        path = out / name
        if path.exists():
            try:
                with zipfile.ZipFile(path) as archive:
                    from xml.etree import ElementTree as ET

                    content = ET.fromstring(archive.read("word/document.xml"))
                    ns = {
                        "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
                    }
                    word.append(
                        {
                            "file": name,
                            "valid": archive.testzip() is None,
                            "tables": len(content.findall(".//w:tbl", ns)),
                            "figures": len(content.findall(".//w:drawing", ns)),
                        }
                    )
            except (OSError, KeyError, ValueError, zipfile.BadZipFile) as error:
                word.append({"file": name, "valid": False, "error": str(error)})
    pairs = [p.get("screening", {}).get("reviews", []) for p in papers]
    pairs = [p for p in pairs if len(p) == 2]
    logs = read_json(out / "search_log.json", [])
    return {
        "review_id": review_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "status": state.get("status"),
        "completed_stages": state.get("completed", []),
        "source_checks": source_checks,
        "word_exports": word,
        "writing": writing_status(review_id),
        "prisma_count_checks": read_json(out / "prisma_flow.json", {}).get(
            "count_checks", {}
        ),
        "searched_sources": sorted({e["source"] for e in logs}),
        "search_errors": [e for e in logs if e.get("error")],
        "search_truncated": any(e.get("truncated") for e in logs),
        "simulated_reviewer_pairs": len(pairs),
        "simulated_reviewer_agreement": sum(
            p[0]["decision"] == p[1]["decision"] for p in pairs
        )
        / len(pairs)
        if pairs
        else None,
        "execution_trace": read_json(out / "execution_trace.json", []),
        "human_reference_metrics": None,
        "scope": "Software/source integrity and observed execution only. Matching quotations and model agreement do not establish scientific accuracy, completeness or time savings versus humans.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review_id")
    parser.add_argument("directory", type=Path)
    parser.add_argument("--inference", action="store_true")
    parser.add_argument("--profile", choices=["general", "prediction", "diagnostic"])
    args = parser.parse_args()
    if args.directory.exists():
        parser.error("Use a new directory to preserve prior audit results")
    root = get_review_path(args.review_id)
    before = {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in root.rglob("*")
        if p.is_file() and "history" not in p.parts and "chroma" not in p.parts
    }
    args.directory.mkdir(parents=True)
    started = perf_counter()
    write_json(args.directory / "integrity.json", inspect_review(args.review_id))
    if args.inference:
        from agents.appraisal_agent import propose_appraisal
        from agents.scientific_qa import review_manuscript
        from methodology.appraisal_profiles import apply_profile

        protocol = Protocol.model_validate(load_protocol(args.review_id)["protocol"])
        if args.profile:
            protocol = apply_profile(protocol, args.profile)
        records = read_json(root / "outputs/evidence.json", [])
        appraisals = {}
        for record in records:
            appraisals[record["paper_id"]] = propose_appraisal(
                protocol, record, report_progress=False
            )
            write_json(args.directory / "appraisal_proposals.json", appraisals)
            print(f"Appraisal completed for {record['paper_id']}", flush=True)
        report_path = next(
            (
                p
                for p in [
                    root / "outputs/automatic_review.md",
                    root / "outputs/literature_review.md",
                ]
                if p.exists()
            ),
            None,
        )
        if not report_path:
            raise ValueError("A scientific manuscript is required for criticism")
        write_json(
            args.directory / "scientific_quality.json",
            review_manuscript(
                protocol.model_dump(mode="json"),
                records,
                report_path.read_text(),
                writing=read_json(root / "outputs/scientific_manuscript.json", {}),
            ),
        )
    changed = [
        name
        for name, sha in before.items()
        if not (root / name).exists()
        or hashlib.sha256((root / name).read_bytes()).hexdigest() != sha
    ]
    write_json(
        args.directory / "manifest.json",
        {
            "review_id": args.review_id,
            "elapsed_seconds": perf_counter() - started,
            "changed_existing_files": changed,
            "human_annotations_created": False,
            "note": "Progress/status files can change during optional inference; human decisions and manuscripts are never written by this audit.",
        },
    )
    print(f"Audit saved to {args.directory}", flush=True)


if __name__ == "__main__":
    main()
