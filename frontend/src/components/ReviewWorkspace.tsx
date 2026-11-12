import { PdfButton } from "./PdfViewer";
import {
  BookOpen,
  Check,
  CheckCheck,
  ChevronRight,
  Circle,
  ClipboardCheck,
  ExternalLink,
  LoaderCircle,
  Quote,
  Search,
  UserRound,
  X,
} from "lucide-react";
import React, { useEffect, useRef, useState } from "react";
import {
  apiUrl,
  readable,
  request,
  type Decision,
  type Detail,
  type Item,
  type Kind,
  type Stage,
} from "../api";
import { kinds, safeUrl, time } from "../lib/review";
import { Badge, Empty } from "./ui";
export function ReviewWorkspace({
  detail: d,
  stage,
  reviewer,
  busy,
  onSaved,
  onError,
  guided = false,
}: {
  guided?: boolean;
  detail: Detail;
  stage: Stage;
  reviewer: string;
  busy: boolean;
  onSaved: () => Promise<void>;
  onError: (message: string) => void;
}) {
  const desk = useRef<HTMLElement>(null);
  useEffect(() => {
    if (!guided) desk.current?.scrollIntoView({ block: "start" });
  }, [stage, guided]);
  const [filter, setFilter] = useState("");
  const [all, setAll] = useState(false);
  const [itemId, setItemId] = useState("");
  const items = d.queue.items.filter(
    (i) =>
      i.stage === stage &&
      (all || (i.required && !i.decision)) &&
      `${i.title || ""} ${i.paper_id} ${i.quote || ""}`
        .toLowerCase()
        .includes(filter.toLowerCase()),
  );
  const item = items.find((i) => i.item_id === itemId) || items[0];
  const paper = d.papers.find((p) => p.paper_id === item?.paper_id);
  const name =
    stage === "screening"
      ? "Screening desk"
      : stage === "eligibility"
        ? "Full-text assessment"
        : "Evidence desk";
  return (
    <section ref={desk} className="panel review-panel">
      <div className="section-heading">
        <div>
          <span className="eyebrow">
            {stage === "evidence"
              ? "CHECK THE CLAIM, KEEP THE CONTEXT"
              : "ONE CONSIDERED DECISION AT A TIME"}
          </span>
          <h2>{name}</h2>
        </div>
        <Badge tone="amber">{d.pending[stage]} pending</Badge>
      </div>
      <div className="queue-toolbar">
        <div className="search-field">
          <Search size={16} />
          <input
            aria-label="Search review items"
            placeholder={
              stage === "evidence"
                ? "Search quotations or paper IDs…"
                : "Search titles or paper IDs…"
            }
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
        </div>
        <div className="segmented">
          <button
            className={!all ? "selected" : ""}
            onClick={() => setAll(false)}
          >
            Needs review
          </button>
          <button
            className={all ? "selected" : ""}
            onClick={() => setAll(true)}
          >
            All items
          </button>
        </div>
      </div>
      {items.length > 0 && (
        <label className="mobile-paper-picker form-label">
          Review item
          <select
            value={item.item_id}
            onChange={(e) => setItemId(e.target.value)}
          >
            {items.map((i, n) => (
              <option key={i.item_id} value={i.item_id}>
                {n + 1}. {i.title || i.quote || i.paper_id}
              </option>
            ))}
          </select>
        </label>
      )}
      {items.length ? (
        <div className="review-split">
          <div className="queue-list" aria-label="Review items">
            {items.map((i, n) => (
              <button
                key={i.item_id}
                className={`queue-item ${i.item_id === item?.item_id ? "selected" : ""}`}
                onClick={() => setItemId(i.item_id)}
              >
                <div className="queue-item-top">
                  <span>
                    {String(n + 1).padStart(2, "0")} / {i.paper_id}
                  </span>
                  {i.decision ? <CheckCheck size={14} /> : <Circle size={10} />}
                </div>
                <strong>{i.title || i.quote}</strong>
                <div className="queue-item-bottom">
                  <Badge
                    tone={
                      i.status === "stale" ? "amber" : i.decision ? "green" : ""
                    }
                  >
                    {i.decision
                      ? readable(i.decision.decision)
                      : i.status === "stale"
                        ? "Needs reassessment"
                        : i.required
                          ? "Needs review"
                          : `AI: ${i.automated_decision}`}
                  </Badge>
                  <ChevronRight size={14} />
                </div>
              </button>
            ))}
          </div>
          <div
            className="item-detail"
            key={`${item.item_id}:${item.fingerprint}:${item.decision?.timestamp || ""}`}
          >
            <div className="reading-body">
              <div className="item-eyebrow">
                <span>
                  {paper?.year || "Year unavailable"} · {item.paper_id}
                </span>
                <div className="source-links">
                  {paper?.files.pdf && (
                    <PdfButton
                      fileUrl={paper.files.pdf}
                      title={paper.title}
                      initialPage={item.passage?.page_start || 1}
                    />
                  )}
                  {paper?.files.pdf && (
                    <a
                      href={`${apiUrl(paper.files.pdf)}${item.passage?.page_start ? `#page=${item.passage.page_start}` : ""}`}
                      target="_blank"
                      rel="noreferrer"
                    >
                      Open PDF <ExternalLink size={13} />
                    </a>
                  )}
                  {!paper?.files.pdf && paper?.files.txt && (
                    <a
                      href={apiUrl(paper.files.txt)}
                      target="_blank"
                      rel="noreferrer"
                    >
                      Full text <ExternalLink size={13} />
                    </a>
                  )}
                  {safeUrl(paper?.landing_url || paper?.id) && (
                    <a
                      href={safeUrl(paper?.landing_url || paper?.id)}
                      target="_blank"
                      rel="noreferrer"
                    >
                      Paper record <ExternalLink size={13} />
                    </a>
                  )}
                </div>
              </div>
              <h3>{paper?.title || item.title || "Evidence assessment"}</h3>
              {paper?.authors?.length ? (
                <p className="authors">
                  {paper.authors.slice(0, 5).join(", ")}
                  {paper.authors.length > 5 ? " et al." : ""}
                </p>
              ) : null}
              {stage === "evidence" ? (
                <>
                  <div className="field-label">CANDIDATE QUOTATION</div>
                  <blockquote className="evidence-quote">
                    {item.quote}
                  </blockquote>
                  {item.passage && (
                    <>
                      <div className="field-label">
                        SOURCE CONTEXT{" "}
                        <span>
                          {item.passage.page_start
                            ? `PDF p. ${item.passage.page_start}${item.passage.page_end !== item.passage.page_start ? `–${item.passage.page_end}` : ""}`
                            : "Page unavailable"}
                        </span>
                      </div>
                      <div className="source-passage">
                        <Highlighted
                          text={item.passage.text}
                          quote={item.quote || ""}
                        />
                      </div>
                    </>
                  )}
                </>
              ) : (
                <>
                  <div className="field-label">
                    {stage === "screening" ? "ABSTRACT" : "PAPER CONTEXT"}
                  </div>
                  <p className="abstract">
                    {paper?.abstract ||
                      item.abstract ||
                      "No abstract is available. Inspect the paper record or full text before deciding; a missing abstract is not grounds for exclusion."}
                  </p>
                  {stage === "eligibility" && (
                    <div className="context-note">
                      <BookOpen size={17} />
                      <span>
                        Assess the complete report against your review criteria.
                        Record an explicit reason for inclusion or exclusion.
                      </span>
                    </div>
                  )}
                </>
              )}
              {item.decision && (
                <div className="previous-decision">
                  <CheckCheck size={15} />
                  <div>
                    <strong>
                      {readable(item.decision.decision)} by{" "}
                      {item.decision.reviewer}
                    </strong>
                    {item.decision.reason && <p>{item.decision.reason}</p>}
                    <small>
                      {time(item.decision.timestamp)} · Corrections add a new
                      history entry.
                    </small>
                  </div>
                </div>
              )}
              {item.proposal && (
                <div className="context-note">
                  <strong>
                    Advisory full-text recommendation:{" "}
                    {item.proposal.recommendation}
                  </strong>
                  <p>{item.proposal.reason}</p>
                  <small>{item.proposal.coverage}</small>
                </div>
              )}
            </div>
            <DecisionForm
              item={item}
              criteria={
                stage === "evidence"
                  ? [
                      "Quotation is not supported by the source",
                      "Incorrect attribution or category",
                      "Insufficient context",
                    ]
                  : d.protocol?.protocol.exclusion_criteria || []
              }
              onSkip={() =>
                setItemId(
                  items[
                    (items.findIndex((i) => i.item_id === item.item_id) + 1) %
                      items.length
                  ].item_id,
                )
              }
              reviewId={d.id}
              reviewer={reviewer}
              busy={busy}
              onSaved={async () => {
                await onSaved();
                if (items.length > 1)
                  setItemId(
                    items[
                      (items.findIndex((i) => i.item_id === item.item_id) + 1) %
                        items.length
                    ].item_id,
                  );
              }}
              onError={onError}
            />
          </div>
        </div>
      ) : (
        <Empty
          icon={stage === "evidence" ? Quote : ClipboardCheck}
          title={
            filter
              ? "No matching items"
              : stage === "evidence" && !d.queue.included_papers.length
                ? "Eligibility comes first."
                : "Nothing waiting here."
          }
        >
          {filter
            ? "Try a different title, phrase, or paper ID."
            : stage === "evidence" && !d.queue.included_papers.length
              ? "Include an eligible full-text study to unlock its quotations for review. Raw extractions stay preserved in your review workspace."
              : "Switch to All items to inspect previous decisions, or resume the workflow to move forward."}
        </Empty>
      )}
    </section>
  );
}
function Highlighted({ text, quote }: { text: string; quote: string }) {
  const index = text.indexOf(quote);
  return index < 0 || !quote ? (
    <>{text}</>
  ) : (
    <>
      {text.slice(0, index)}
      <mark>{text.slice(index, index + quote.length)}</mark>
      {text.slice(index + quote.length)}
    </>
  );
}
function DecisionForm({
  item,
  criteria,
  onSkip,
  reviewId,
  reviewer,
  busy,
  onSaved,
  onError,
}: {
  item: Item;
  criteria: string[];
  onSkip: () => void;
  reviewId: string;
  reviewer: string;
  busy: boolean;
  onSaved: () => Promise<void>;
  onError: (message: string) => void;
}) {
  const [choice, setChoice] = useState<Decision["decision"] | "">("");
  const [reason, setReason] = useState("");
  const [showNotes, setShowNotes] = useState(false);
  const [kind, setKind] = useState<Kind>(
    item.decision?.kind || item.proposed_kind || "main_findings",
  );
  const [saving, setSaving] = useState(false);
  const evidence = item.stage === "evidence";
  const requiresReason = item.stage === "eligibility" && choice === "exclude";
  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (!choice || (requiresReason && !reason.trim()) || !reviewer.trim())
      return;
    setSaving(true);
    try {
      await request(`/reviews/${encodeURIComponent(reviewId)}/decisions`, {
        method: "POST",
        body: JSON.stringify({
          item_id: item.item_id,
          fingerprint: item.fingerprint,
          decision: choice,
          reviewer,
          reason,
          kind:
            evidence && choice === "approve" && !item.empty_evidence
              ? kind
              : null,
        }),
      });
      await onSaved();
    } catch (error) {
      onError((error as Error).message);
    } finally {
      setSaving(false);
    }
  }
  return (
    <form className="decision-form" onSubmit={(e) => void save(e)}>
      <div className="field-label">
        YOUR ASSESSMENT{" "}
        <span>
          {item.decision
            ? "Update a decision"
            : "Save and move to the next pending item"}
        </span>
      </div>
      {busy && (
        <p className="context-note">
          The workflow is updating this review. Use “Pause to review” above;
          decisions unlock once the current operation is saved.
        </p>
      )}
      {!reviewer.trim() && (
        <p className="context-note">
          Enter your reviewer name at the top of the page to save a decision.
        </p>
      )}
      <fieldset disabled={busy || saving}>
        <legend className="sr-only">Review decision</legend>
        <div className="decision-options">
          {(evidence ? ["approve", "reject"] : ["include", "exclude"]).map(
            (value) => (
              <button
                type="button"
                key={value}
                aria-pressed={choice === value}
                className={`${choice === value ? "chosen" : ""} ${value}`}
                onClick={() => setChoice(value as Decision["decision"])}
              >
                {value === "approve" || value === "include" ? (
                  <Check size={16} />
                ) : (
                  <X size={16} />
                )}
                {item.empty_evidence && value === "approve"
                  ? "Acknowledge gap"
                  : readable(value)}
              </button>
            ),
          )}
        </div>
        {evidence && choice === "approve" && !item.empty_evidence && (
          <label className="form-label">
            Evidence category
            <select
              value={kind}
              onChange={(e) => setKind(e.target.value as Kind)}
            >
              {kinds.map((k) => (
                <option key={k.value} value={k.value}>
                  {k.label}
                </option>
              ))}
            </select>
            <small>Correct the model’s suggested category when needed.</small>
          </label>
        )}
        {(choice === "exclude" || choice === "reject") &&
          criteria.length > 0 && (
            <div
              className="reason-shortcuts"
              aria-label="Protocol exclusion reasons"
            >
              <span>Use a protocol reason:</span>
              {criteria.map((c) => (
                <button
                  type="button"
                  className={reason === c ? "selected" : ""}
                  key={c}
                  onClick={() => {
                    setReason(c);
                    setShowNotes(true);
                  }}
                >
                  {c}
                </button>
              ))}
            </div>
          )}
        {requiresReason || showNotes ? (
          <label className="form-label">
            {requiresReason
              ? "Exclusion reason · required"
              : "Notes · optional"}
            <textarea
              required={requiresReason}
              rows={2}
              placeholder={
                requiresReason
                  ? "Select a reason above or enter your own…"
                  : "Add context if useful…"
              }
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
          </label>
        ) : (
          <button
            type="button"
            className="text-button"
            onClick={() => setShowNotes(true)}
          >
            + Add optional notes
          </button>
        )}
        <div className="form-bottom">
          <button
            type="button"
            className="secondary-button"
            onClick={onSkip}
            disabled={busy || saving}
          >
            Skip for now
          </button>
          <span>
            <UserRound size={14} />
            {reviewer.trim() || "Enter your reviewer name above"}
          </span>
          <button
            className="primary-button"
            disabled={
              !choice ||
              (requiresReason && !reason.trim()) ||
              !reviewer.trim() ||
              busy ||
              saving
            }
          >
            {saving ? (
              <LoaderCircle className="spin" size={15} />
            ) : (
              <CheckCheck size={15} />
            )}{" "}
            {item.decision ? "Save correction" : "Save & next"}
          </button>
        </div>
      </fieldset>
    </form>
  );
}
