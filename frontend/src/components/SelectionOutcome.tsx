import { artifactUrl, type Detail } from "../api";
import type { Tab } from "../lib/review";

export function SelectionOutcome({ detail, onTab, onRun }: {
  detail: Detail; onTab?: (tab: Tab) => void; onRun?: () => Promise<void>;
}) {
  const outcome = detail.selection_outcome;
  if (!outcome) return null;
  return <section className="panel" aria-label="Review stopped without evidence">
    <span className="eyebrow">SEARCH AND SELECTION OUTCOME</span>
    <h2>No evidence available for a scientific manuscript</h2>
    <p>{outcome.message}</p>
    <p>The review has stopped. No further extraction, appraisal or scientific writing will run while this selection remains empty.</p>
    <p>You can inspect your decisions, revise and approve the protocol, or start a new conversation with different search settings. Unavailable PDFs are access gaps, not scientific exclusions.</p>
    <div className="method-actions">
      {onTab && <>
        <button className="secondary-button" onClick={() => onTab(outcome.reason === "all_screened_out" ? "screening" : "papers")}>Review selection</button>
        <button className="secondary-button" onClick={() => onTab("protocol")}>Edit protocol</button>
      </>}
      {detail.artifacts.includes("selection_report.docx") && <a className="secondary-button" href={artifactUrl(detail.id, "selection_report.docx")}>Download selection report</a>}
      {onRun && <button className="text-button" onClick={() => void onRun()}>Recheck after changes</button>}
    </div>
  </section>;
}
