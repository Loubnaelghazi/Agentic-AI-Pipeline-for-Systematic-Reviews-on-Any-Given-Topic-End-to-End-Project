import { ArrowDownToLine, Clock3, FileText, ShieldCheck } from "lucide-react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { SelectionSummary } from "./SelectionSummary";
import { artifactUrl, readable, type Detail } from "../api";
import { Badge, Empty } from "./ui";
const fileLabels: Record<string, string> = {
  "technical_report.docx": "Technical & reproducibility report (Word)", "technical_report.md": "Technical & reproducibility report (Markdown)",
  "automatic_review.docx": "Word manuscript", "literature_review.docx": "Word manuscript",
  "automatic_review.md": "Markdown manuscript", "literature_review.md": "Markdown manuscript",
  "numerical_results.csv": "Numerical study results (CSV)", "evidence_table.csv": "Source evidence table (CSV)",
  "full_text_decisions.csv": "Selection decisions (CSV)", "references.bib": "Bibliography (BibTeX)",
  "prisma_flow.svg": "PRISMA diagram (SVG)", "prisma_flow.png": "PRISMA diagram (PNG)",
  "evidence_map.svg": "Evidence map", "evidence_map.csv": "Evidence map (CSV)",
  "meta_analysis_template.csv": "Meta-analysis preparation (CSV)",
};
export function Report({ detail: d }: { detail: Detail }) {
  const manuscript = d.runtime_settings?.mode === "automatic" ? "automatic_review" : "literature_review";
  const technical = d.artifacts.filter(name => name.endsWith(".json") || name.startsWith("technical_report."));
  const documents = d.artifacts.filter(name => !name.endsWith(".json") && !name.startsWith("technical_report."));
  const writing = d.automatic_result?.writing || d.writing;
  const reportCurrent = d.automatic_result ? d.automatic_result.current : d.report_current;
  return (
    <div className="report-columns">
      {writing && <section className="panel writing-status" aria-label="Scientific writing status">
        <span className="eyebrow">SCIENTIFIC MANUSCRIPT</span>
        <h2>{d.report && !reportCurrent ? "Checks from the previous manuscript" : writing.ready ? "Ready for scientific review" : "Writing in progress or incomplete"}</h2>
        <p>{d.report && !reportCurrent ? "These checks belong to an earlier draft. Resume the review to apply the current evidence and decisions. " : ""}{writing.completed_sections} of {writing.total_sections} scientific sections passed paragraph and citation checks. Methods, selection counts and references are assembled from the recorded review.</p>
        <div className="writing-section-list">{["introduction", "results", "discussion", "conclusion", "abstract"].map(name => <span key={name} className={writing.sections?.find(s => s.name === name)?.verified ? "writing-verified" : "writing-pending"}>{writing.sections?.find(s => s.name === name)?.verified ? "✓" : "○"} {readable(name)}</span>)}</div>
        {!!writing.issues.length && <details><summary>Writing checks to resolve ({writing.issues.length})</summary><ul>{writing.issues.map((issue, i) => <li key={i}>{issue}</li>)}</ul></details>}
        <p>Automated checks support review; a researcher must assess the scientific interpretation.</p>
      </section>}
      <SelectionSummary detail={d} />
      <section className="panel report-panel">
        <div className="section-heading">
          <div>
            <span className="eyebrow">THE EVIDENCE, ON PAPER</span>
            <h2>Review draft</h2>
          </div>
          {d.report && (
            <div className="report-downloads">
            <a className="primary-button" href={artifactUrl(d.id, `${manuscript}.docx`)}><ArrowDownToLine size={15} /> Scientific manuscript</a>
            {d.artifacts.includes("technical_report.docx") && <a className="secondary-button" href={artifactUrl(d.id, "technical_report.docx")}><ArrowDownToLine size={15} /> Technical report</a>}
            <a
              className="secondary-button"
              href={artifactUrl(
                d.id,
                d.runtime_settings?.mode === "automatic"
                  ? "automatic_review.md"
                  : "literature_review.md",
              )}
            >
              <ArrowDownToLine size={15} /> Markdown
            </a>
            </div>
          )}
        </div>
        {d.report && !reportCurrent && (
          <div className="report-notice">
            <Clock3 size={17} />
            <span>
              This is a historical draft. Complete the review decisions and
              resume the workflow to regenerate it.
            </span>
          </div>
        )}
        {d.report ? (
          <article className="markdown scientific-manuscript">
            <Markdown remarkPlugins={[remarkGfm]} components={{img: ({src, alt}) => src === "prisma_flow.png" ? <img src={artifactUrl(d.id, "prisma_flow.png").replace("download=true", "download=false")} alt={alt || "Study selection flow"} loading="lazy" /> : <span>{alt}</span>}}>{d.report}</Markdown>
          </article>
        ) : (
          <Empty icon={FileText} title="The draft comes after the decisions.">
            Complete screening, full-text eligibility, and evidence review. Then
            resume the workflow to generate your draft.
          </Empty>
        )}
      </section>
      <div>
        <section className="panel qa-panel">
          <div className="section-heading">
            <div>
              <span className="eyebrow">A SECOND LOOK</span>
              <h2>Quality review</h2>
            </div>
            <ShieldCheck size={20} />
          </div>
          {d.quality ? (
            <>
              <Badge tone={d.quality.passed ? "green" : "amber"}>
                {d.quality.passed ? "Checks passed" : "Needs attention"}
                {!reportCurrent ? " · Historical" : ""}
              </Badge>
              <p className="qa-description">
                Automated review is advisory. It does not establish scientific
                correctness.
              </p>
              <h3>Issues to assess</h3>
              <ul className="qa-list">
                {d.quality.issues.map((issue, i) => (
                  <li key={i}>{issue}</li>
                ))}
              </ul>
              {d.quality.recommendations.length > 0 && (
                <details>
                  <summary>
                    Recommendations ({d.quality.recommendations.length})
                  </summary>
                  <ul className="qa-list">
                    {d.quality.recommendations.map((r, i) => (
                      <li key={i}>{r}</li>
                    ))}
                  </ul>
                </details>
              )}
            </>
          ) : (
            <p className="muted">
              Quality checks will appear after a report is generated.
            </p>
          )}
        </section>
        <section className="panel exports-panel">
          <h3>Review files</h3>
          {documents.map((name) => (
            <a key={name} href={artifactUrl(d.id, name)}>
              <FileText size={15} />
              <span>
                {fileLabels[name] || readable(name.replace(".md", ""))}
              </span>
              <ArrowDownToLine size={14} />
            </a>
          ))}
          {technical.length > 0 && <details className="technical-artifacts">
            <summary>Technical files & audit trail ({technical.length})</summary>
            <p>Machine-readable records for reproducibility and troubleshooting.</p>
            {technical.map(name => <a key={name} href={artifactUrl(d.id, name)}><FileText size={14} /><span>{fileLabels[name] || readable(name.replace(".json", ""))}</span><ArrowDownToLine size={14} /></a>)}
          </details>}
        </section>
      </div>
    </div>
  );
}
