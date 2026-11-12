import { useEffect, useState } from "react";
import { Bot, Check, LoaderCircle, Pause, X } from "lucide-react";
import { request, readable, type Detail } from "../api";
import { isBusy, progressMessage, type Tab } from "../lib/review";
import { Report } from "./Report";
export function AutomaticReview({
  detail: d,
  reviewer,
  onSaved,
  onError,
  onRun,
  onTab,
}: {
  detail: Detail;
  reviewer: string;
  onSaved: () => Promise<void>;
  onError: (s: string) => void;
  onRun: () => Promise<void>;
  onTab: (t: Tab) => void;
}) {
  const [working, setWorking] = useState(false);
  const [note, setNote] = useState("");
  const [showReport, setShowReport] = useState(true);
  const [clock, setClock] = useState(Date.now());
  const busy = isBusy(d);
  useEffect(() => {
    if (!busy) return;
    const timer = setInterval(() => setClock(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [busy]);
  const elapsed = d.job.started_at
    ? Math.max(0, Math.floor((clock - Date.parse(d.job.started_at)) / 1000))
    : 0;
  const result = d.automatic_result;
  async function decide(decision: "accept" | "reject") {
    if (!result || !reviewer.trim()) return;
    setWorking(true);
    try {
      await request(`/reviews/${d.id}/final-decision`, {
        method: "POST",
        body: JSON.stringify({
          fingerprint: result.fingerprint,
          decision,
          reviewer,
          note,
        }),
      });
      await onSaved();
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setWorking(false);
    }
  }
  async function pause() {
    setWorking(true);
    try {
      await request(`/reviews/${d.id}/pause`, { method: "POST" });
      await onSaved();
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setWorking(false);
    }
  }
  return (
    <div className="message assistant-message automatic-review">
      <span className="assistant-avatar">
        <Bot size={19} />
      </span>
      <div className="message-body">
        <span className="phase-caption">
          AUTOMATED DRAFT · FINAL REVIEW ONLY
        </span>
        <h2>
          {busy
            ? "I’m preparing your draft."
            : result && !result.current
              ? "The draft needs regeneration."
            : result?.ready === false
              ? "The scientific draft needs attention."
            : result?.decision
              ? `Draft ${result.decision.decision === "accept" ? "accepted" : "rejected"}.`
              : result
                ? "Your automated draft is ready to review."
                : d.workflow_status === "failed"
                  ? "The automatic run needs attention."
                  : "Ready to prepare an automated draft."}
        </h2>
        <p>
          {busy
            ? "I’ll handle the intermediate steps and stop when the final result is ready. No intermediate validation is required."
            : "Intermediate selections, source extraction and appraisal notes are machine proposals. Accept or reject the overall result below; this does not certify individual claims."}
        </p>
        {busy && (
          <div className="processing-card">
            <div>
              <LoaderCircle className="spin" size={19} />
              <strong>{readable(d.progress?.stage || "starting")}</strong>
            </div>
            <p>{progressMessage(d) || "Starting…"}</p>
            <p>
              {d.progress?.total
                ? `${d.progress.completed} of ${d.progress.total} items`
                : `${d.completed.length} of ${d.total_stages} stages`}{" "}
              · {Math.floor(elapsed / 60)}m {elapsed % 60}s elapsed
            </p>
            <button
              className="secondary-button"
              disabled={working || d.job.pause_requested}
              onClick={() => void pause()}
            >
              <Pause size={14} />
              {d.job.pause_requested ? "Pause requested…" : "Pause"}
            </button>
            <button className="text-button" onClick={() => onTab("activity")}>
              Live log
            </button>
          </div>
        )}
        {!busy && result?.ready === false && <div role="alert" className="automatic-notice">
          <p>{!result.current ? "The pipeline or evidence changed. Regenerate the draft to apply the current checks. Any displayed draft is historical." : result.failed_paper_ids?.length ? "Some source extractions are incomplete. Resume to retry them." : result.writing?.status === "insufficient_eligible_evidence" ? "No eligible evidence is available for scientific writing. Inspect full-text eligibility and search coverage before continuing." : "Scientific writing is incomplete. Resume to retry the missing sections; verified sections are saved."} Existing downloads are saved.</p>
          {result.current && result.writing?.status === "insufficient_eligible_evidence" ? <>
            <p>Use a guided review to adjudicate uncertain selections, or create a new review with a broader search.</p>
            <button type="button" className="primary-button" onClick={() => onTab("papers")}>Inspect source papers</button>
          </> : <button type="button" className="primary-button" disabled={working} onClick={() => void onRun().catch((e) => onError(e.message))}>{!result.current ? "Regenerate draft" : result.failed_paper_ids?.length ? "Retry failed extractions" : "Resume scientific writing"}</button>}
        </div>}
        {!busy && result && (
          <section className="automatic-final-card">
            <p className="automatic-notice">
              AI-generated preliminary draft. Intermediate decisions have not
              been individually human-validated.
            </p>
            {d.prisma && <button type="button" className="text-button" onClick={() => onTab("prisma")}>Review PRISMA checklist</button>}
            <button
              type="button"
              className="text-button"
              onClick={() => setShowReport(!showReport)}
            >
              {showReport ? "Hide draft" : "Read draft and quality notes"}
            </button>
            {showReport && (
              <div className="automatic-report">
                <Report detail={d} />
              </div>
            )}
            {!result.current && (
              <p role="alert">
                The report or sources changed. Regenerate before deciding.
              </p>
            )}
            {result.decision ? (
              <p className="final-decision-status">
                <Check size={18} /> {result.decision.reviewer}{" "}
                {result.decision.decision === "accept"
                  ? "accepted"
                  : "rejected"}{" "}
                this version.
                {result.decision.note ? ` ${result.decision.note}` : ""}
              </p>
            ) : (
              <>
                <label className="form-label">
                  Final review notes · optional
                  <textarea
                    rows={2}
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                    placeholder="Add any concerns or feedback…"
                  />
                </label>
                {!reviewer.trim() && (
                  <p>Enter your reviewer name above before deciding.</p>
                )}
                <div className="final-review-actions">
                  <button
                    className="secondary-button reject-final"
                    disabled={working || !result.current || !reviewer.trim()}
                    onClick={() => void decide("reject")}
                  >
                    <X size={16} />
                    Reject final result
                  </button>
                  <button
                    className="primary-button"
                    disabled={working || !result.current || result.ready === false || !reviewer.trim()}
                    onClick={() => void decide("accept")}
                  >
                    <Check size={16} />
                    Accept final result
                  </button>
                </div>
              </>
            )}
          </section>
        )}
        {!busy && (!result || !result.current) && (
          <div className="automatic-resume">
            <button
              className="primary-button"
              disabled={working}
              onClick={() => void onRun().catch((e) => onError(e.message))}
            >
              {result
                ? "Regenerate draft"
                : d.completed.length
                  ? "Resume automatic run"
                  : "Start automatic run"}
            </button>
            <button className="text-button" onClick={() => onTab("activity")}>
              Inspect activity
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
