import { ArrowDownToLine, ChevronDown, ExternalLink } from "lucide-react";
import { artifactUrl, type Detail } from "../api";

export function SelectionSummary({ detail: d }: { detail: Detail }) {
  const flow = d.prisma_flow;
  if (!flow) return null;
  const value = (key: string) => {
    const count = flow[key];
    return typeof count === "number" && Number.isInteger(count) && count >= 0 ? count : "—";
  };
  const pending = value("eligibility_uncertain");
  const automatic = d.runtime_settings?.mode === "automatic";
  const diagram = artifactUrl(d.id, "prisma_flow.svg").replace("download=true", "download=false");
  const cards = [
    { key: "records_identified", label: "Records found", tone: "blue", note: "Before deduplication" },
    { key: "reports_retrieved", label: "Full texts retrieved", tone: "teal", note: "Available for assessment" },
    { key: "reports_included", label: automatic ? "Include recommendations" : "Included reports", tone: "green", note: automatic ? "Machine recommendations" : "Eligibility decisions" },
    { key: "eligibility_uncertain", label: "Decisions pending", tone: "amber", note: "Evidence remains provisional" },
  ];
  return <section className="panel selection-summary" aria-label="Search and selection results">
    <div className="section-heading">
      <div><span className="eyebrow">FROM SEARCH TO EVIDENCE</span><h2>Search & selection</h2></div>
      <span className={`selection-status ${typeof pending === "number" && pending > 0 ? "pending" : ""}`}>
        {typeof pending === "number" && pending > 0 ? `${pending} eligibility decisions pending` : "Reporting draft"}
      </span>
    </div>
    <div className="selection-stats">
      {cards.map(card => <div className={`selection-stat ${card.tone}`} key={card.key}>
        <span>{card.label}</span><strong>{value(card.key)}</strong><small>{card.note}</small>
      </div>)}
    </div>
    <p className="selection-explanation">
      {typeof pending === "number" && pending > 0
        ? "Pending reports can provide provisional excerpts, but do not support the primary comparative conclusions."
        : "Counts describe reports; independent studies and scientific conclusions require review."}
      {" "}An unavailable PDF is an access gap, not a scientific exclusion.
    </p>
    <details className="selection-diagram" open>
      <summary><span>PRISMA selection diagram</span><ChevronDown size={16} /></summary>
      <div className="selection-figure">
        <img src={`${diagram}&v=${encodeURIComponent(d.automatic_result?.fingerprint || "current")}`} alt="PRISMA-oriented selection diagram showing identification, screening, retrieval and separate include and pending decisions" />
      </div>
      <div className="selection-figure-actions">
        <a href={diagram} target="_blank" rel="noreferrer"><ExternalLink size={14} /> View full size</a>
        <a href={artifactUrl(d.id, "prisma_flow.svg")}><ArrowDownToLine size={14} /> Download diagram</a>
      </div>
      <p className="selection-caption">Reporting aid based on saved selection records. The diagram does not certify PRISMA compliance.</p>
    </details>
  </section>;
}
