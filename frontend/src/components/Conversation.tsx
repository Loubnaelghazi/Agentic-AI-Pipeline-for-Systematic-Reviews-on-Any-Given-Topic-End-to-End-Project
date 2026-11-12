import { AutomaticReview } from "./AutomaticReview";
import { ThinkingControl } from "./ThinkingControl";
import { useEffect, useRef, useState } from "react";
import {
  ArrowRight,
  ArrowUp,
  ChevronRight,
  FileCheck2,
  Settings2,
  FileText,
  Bot,
  Check,
  ChevronDown,
  LoaderCircle,
  Pause,
  RefreshCw,
} from "lucide-react";
import Markdown from "react-markdown";
import { readable, request, type Detail, type Stage } from "../api";
import { isBusy, progressMessage, type Tab } from "../lib/review";
import { ProtocolPanel, AppraisalPanel, PrismaPanel } from "./Methodology";
import { ReviewWorkspace } from "./ReviewWorkspace";
import { Report } from "./Report";

type Props = {
  detail: Detail;
  reviewer: string;
  onSaved: () => Promise<void>;
  onError: (message: string) => void;
  onRun: () => Promise<void>;
  onTab: (tab: Tab) => void;
};
type Controls = {
  model: string;
  available: boolean;
  error: string | null;
  options: { value: string; label: string }[];
};
const phases = [
  "Protocol",
  "Search",
  "Screening",
  "Full text",
  "Evidence",
  "Appraisal",
  "Report",
];
const stagePhase: Record<string, number> = {
  retrieval: 1,
  save: 2,
  full_text_screening: 3,
  extraction: 4,
  appraisal: 5,
  quality: 6,
};
const phaseTab: Record<number, Stage> = {
  2: "screening",
  3: "eligibility",
  4: "evidence",
};
export function Conversation({
  detail: d,
  reviewer,
  onSaved,
  onError,
  onRun,
  onTab,
}: Props) {
  const busy = isBusy(d);
  const [working, setWorking] = useState(false);
  const [controls, setControls] = useState<Controls | null>(null);
  const [loadingControls, setLoadingControls] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [showChecklist, setShowChecklist] = useState(false);
  const [limit, setLimit] = useState(8);
  const [clock, setClock] = useState(Date.now());
  useEffect(() => {
    if (!busy) return;
    const timer = setInterval(() => setClock(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [busy]);
  const paused = d.workflow_status === "paused";
  const elapsed = d.job.started_at
    ? Math.max(0, Math.floor((clock - Date.parse(d.job.started_at)) / 1000))
    : 0;
  async function loadControls() {
    setLoadingControls(true);
    try {
      setControls(
        await request<Controls>(
          `/model-controls${d.runtime_settings?.model ? `?model=${encodeURIComponent(d.runtime_settings.model)}` : ""}`,
        ),
      );
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setLoadingControls(false);
    }
  }
  useEffect(() => {
    void loadControls();
  }, [d.id]);
  const automatic = d.runtime_settings?.mode === "automatic";
  const freshProtocol =
    !!d.protocol?.approval &&
    d.workflow_protocol_fingerprint !== d.protocol.fingerprint;
  const confirmation = freshProtocol ? null : d.awaiting_confirmation;
  const pendingAppraisal = d.appraisals.filter((a) => !a.assessment).length;
  const waitingPhase: Record<string, number> = {
    awaiting_screening_review: 2,
    awaiting_eligibility_review: 3,
    awaiting_evidence_review: 4,
    awaiting_appraisal_review: 5,
  };
  const readyPhase = !d.protocol?.approval
    ? 0
    : freshProtocol
      ? 1
      : confirmation
        ? (stagePhase[confirmation.stage] ?? 1)
        : d.workflow_status && waitingPhase[d.workflow_status]
          ? waitingPhase[d.workflow_status]
          : d.pending.screening
            ? 2
            : d.pending.eligibility
              ? 3
              : d.pending.evidence
                ? 4
                : pendingAppraisal
                  ? 5
                  : d.report_current
                    ? 6
                    : 1;
  const processingPhases: Record<string, number> = {
    search_strategy: 1,
    retrieval: 1,
    screening: 2,
    save: 2,
    download: 3,
    full_text_screening: 3,
    ingestion: 4,
    extraction: 4,
    appraisal: 5,
    synthesis: 6,
    quality: 6,
  };
  const phase =
    (busy || paused) && d.progress
      ? (processingPhases[d.progress.stage] ?? readyPhase)
      : readyPhase;
  const reviewStage = phaseTab[phase];
  const remaining = reviewStage
    ? d.pending[reviewStage]
    : phase === 5
      ? pendingAppraisal
      : 0;
  const headings = [
    "Let’s define what you want to review.",
    "Check the papers I found.",
    "Which papers should we keep?",
    "Check the complete papers.",
    "Check the supporting evidence.",
    "Assess the included studies.",
    d.writing?.ready === false ? "Scientific writing needs attention." : "Your review draft is ready.",
  ];
  const prompts = [
    "Review the question and criteria below. Approve the protocol when you’re happy with it.",
    `${d.papers.length} records are available. Check their relevance and search coverage before starting screening.`,
    `${remaining} screening decisions need your judgement. Read each card and choose Include or Exclude.`,
    `${remaining} full texts need a decision. Keep papers that meet your criteria; exclusions need a reason.`,
    `${remaining} evidence items need checking. Compare each quotation with its source before approving.`,
    `${remaining} studies need assessment. Work through one question at a time; optional fields can be skipped.`,
    "Read the draft and its quality findings. You can download the files or assess the reporting checklist below.",
  ];
  async function continueReview() {
    if (working || busy) return;
    setWorking(true);
    try {
      if (confirmation && !(confirmation.stage === "quality" && d.writing?.ready === false))
        await request(`/reviews/${d.id}/confirm-step`, {
          method: "POST",
          body: JSON.stringify({ token: confirmation.token, reviewer }),
        });
      await onSaved();
      await onRun();
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
  async function changeThinking(mode: string) {
    setWorking(true);
    try {
      await request(`/reviews/${d.id}/settings`, {
        method: "PUT",
        body: JSON.stringify({ thinking: mode }),
      });
      await onSaved();
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setWorking(false);
    }
  }
  const needsName = !!confirmation && !reviewer.trim();
  const props = {
    detail: d,
    reviewer,
    busy: busy || working,
    onSaved,
    onError,
  };
  const [validationOpen, setValidationOpen] = useState(false);
  const [message, setMessage] = useState("");
  const [sending, setSending] = useState(false);
  const [pendingMessage, setPendingMessage] = useState("");
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => {
    setValidationOpen(false);
  }, [phase, confirmation?.token]);
  useEffect(() => {
    end.current?.scrollIntoView({ block: "end" });
  }, [d.chat_messages?.length, sending]);
  async function send() {
    if (!message.trim() || sending || busy || working) return;
    const text = message.trim();
    setSending(true);
    setPendingMessage(text);
    setMessage("");
    try {
      await request(`/reviews/${d.id}/messages`, {
        method: "POST",
        body: JSON.stringify({ text, request_id: crypto.randomUUID() }),
      });
      await onSaved();
    } catch (e) {
      setMessage(text);
      onError((e as Error).message);
    } finally {
      setSending(false);
      setPendingMessage("");
    }
  }
  const blocked = working || sending || busy;
  return (
    <section
      className="chat-conversation"
      aria-label="Guided review conversation"
    >
      <div className="chat-toolbar">
        <div className="model-control">
          <span className="model-dot" />
          <strong>{controls?.model || "Local model"}</strong>
          <span className="model-local">local</span>
        </div>
        <div>
          <ThinkingControl
            mode={d.runtime_settings?.thinking || "off"}
            controls={controls}
            loading={loadingControls}
            disabled={blocked}
            onChange={(mode) => void changeThinking(mode)}
          />
          <button
            type="button"
            className="papers-button"
            onClick={() => onTab("papers")}
          >
            <FileText size={16} />
            Papers & PDFs
            <span>{d.papers.filter((p) => p.files.pdf).length}</span>
          </button>
          <button
            className="icon-button"
            title={controls?.error || "Refresh model controls"}
            aria-label="Refresh model controls"
            disabled={loadingControls}
            onClick={() => void loadControls()}
          >
            <RefreshCw size={14} className={loadingControls ? "spin" : ""} />
          </button>
          <button
            className="icon-button"
            title="Review files and activity"
            aria-label="Review files and activity"
            onClick={() => onTab("report")}
          >
            <Settings2 size={17} />
          </button>
        </div>
      </div>
      {controls?.error && (
        <div className="model-warning">
          Thinking controls unavailable. Check Ollama and use refresh to retry.
        </div>
      )}
      <div className="thread-scroll">
        <div className="thread-width">
          <div className="message user-message">
            <div className="message-body">
              <p>{d.topic}</p>
            </div>
          </div>
          <div className="message assistant-message">
            <span className="assistant-avatar">
              <Bot size={19} />
            </span>
            <div className="message-body">
              <p>
                I’ll help you build a literature review on this topic. We’ll
                agree on the criteria, find papers, check the evidence, and
                prepare a draft.{" "}
                <strong>
                  {automatic
                    ? "I’ll automate the intermediate steps and ask you to accept or reject the final draft."
                    : "You validate each phase before I move on."}
                </strong>
              </p>
            </div>
          </div>
          {(d.step_confirmations?.length || d.decisions.length) > 0 && (
            <div className="validation-history">
              <button onClick={() => setHistoryOpen(!historyOpen)}>
                <Check size={14} />
                {d.step_confirmations?.length || 0} phases validated ·{" "}
                {d.decisions.length} saved decisions
                <ChevronDown size={14} />
              </button>
              {historyOpen && (
                <div>
                  {d.step_confirmations?.map((e) => (
                    <p key={e.token}>
                      <strong>{e.reviewer}</strong> validated {e.title}.
                    </p>
                  ))}
                  {d.decisions.map((e, i) => (
                    <p key={`${e.timestamp}:${i}`}>
                      <strong>{e.reviewer}</strong> · {readable(e.decision)} ·{" "}
                      {e.item_id}
                      {e.reason ? ` — ${e.reason}` : ""}
                    </p>
                  ))}
                </div>
              )}
            </div>
          )}
          {d.chat_messages?.map((m) => (
            <div
              className={`message ${m.role === "user" ? "user-message" : "assistant-message"}`}
              key={m.id}
            >
              {m.role === "assistant" && (
                <span className="assistant-avatar">
                  <Bot size={19} />
                </span>
              )}
              <div className="message-body">
                {m.role === "assistant" ? (
                  <Markdown>{m.content}</Markdown>
                ) : (
                  <p>{m.content}</p>
                )}
              </div>
            </div>
          ))}
          {sending && (
            <>
              <div className="message user-message">
                <div className="message-body">
                  <p>{pendingMessage}</p>
                </div>
              </div>
              <div className="message assistant-message">
                <span className="assistant-avatar">
                  <Bot size={19} />
                </span>
                <div className="message-body typing-indicator" role="status">
                  <span />
                  <span />
                  <span />
                  <small>Preparing an answer…</small>
                </div>
              </div>
            </>
          )}
          {automatic ? (
            <AutomaticReview
              detail={d}
              reviewer={reviewer}
              onSaved={onSaved}
              onError={onError}
              onRun={onRun}
              onTab={onTab}
            />
          ) : (
            <>
              <div className="message assistant-message live-task">
                <span className="assistant-avatar">
                  <Bot size={19} />
                </span>
                <div className="message-body">
                  <span className="phase-caption">
                    PHASE {phase + 1} OF {phases.length} · {phases[phase]}
                  </span>
                  <h2>
                    {busy
                      ? d.progress
                        ? `${readable(d.progress.stage)}…`
                        : "Preparing the next step…"
                      : headings[phase]}
                  </h2>
                  <p>
                    {busy
                      ? progressMessage(d) ||
                        "I’m working on this phase. I’ll stop for your validation before continuing."
                      : prompts[phase]}
                  </p>
                  {busy ? (
                    <div className="processing-card">
                      <div>
                        <LoaderCircle className="spin" size={19} />
                        <strong>Working on this phase</strong>
                      </div>
                      <p>
                        {d.progress?.total
                          ? `${d.progress.completed} of ${d.progress.total} items completed`
                          : `${d.completed.length} of ${d.total_stages} processing stages completed`}{" "}
                        · {Math.floor(elapsed / 60)}m {elapsed % 60}s elapsed
                      </p>
                      {d.progress?.total ? (
                        <progress
                          value={d.progress.completed}
                          max={d.progress.total}
                          aria-label="Items processed"
                        />
                      ) : null}
                      <div>
                        <button
                          className="secondary-button"
                          disabled={working || d.job.pause_requested}
                          onClick={() => void pause()}
                        >
                          <Pause size={14} />
                          {d.job.pause_requested
                            ? "Pause requested…"
                            : "Pause to review"}
                        </button>
                        <button
                          className="text-button"
                          onClick={() => onTab("activity")}
                        >
                          View live log
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div
                      className={`validation-card ${validationOpen ? "expanded" : ""}`}
                    >
                      <button
                        className="validation-card-heading"
                        aria-expanded={validationOpen}
                        onClick={() => setValidationOpen(!validationOpen)}
                      >
                        <span className="validation-icon">
                          <FileCheck2 size={20} />
                        </span>
                        <span>
                          <strong>
                            {phase === 0
                              ? "Review the protocol"
                              : phase === 1
                                ? "Review search results"
                                : phase === 6
                                  ? "Review the draft"
                                  : `Review ${phases[phase].toLowerCase()}`}
                          </strong>
                          <small>
                            {remaining
                              ? `${remaining} decisions need your validation`
                              : phase === 0
                                ? "Check criteria before approving"
                                : "Open details to inspect this phase"}
                          </small>
                        </span>
                        <ChevronRight
                          size={18}
                          className={validationOpen ? "rotated" : ""}
                        />
                      </button>
                      <div
                        hidden={!validationOpen}
                        className="validation-content chat-task"
                      >
                        {phase === 0 && (
                          <ProtocolPanel
                            key={`${d.protocol?.fingerprint}:${d.protocol?.revision}`}
                            {...props}
                            busy={blocked}
                          />
                        )}
                        {phase === 1 && (
                          <div className="chat-search-results">
                            <div className="search-summary">
                              <strong>{d.papers.length} papers</strong>
                              <span>{d.search_log.length} logged searches</span>
                              <span>
                                {d.search_log.filter((s) => s.error).length}{" "}
                                source errors
                              </span>
                            </div>
                            {!d.papers.length && (
                              <p>
                                Your protocol is ready. Continue to start
                                searching.
                              </p>
                            )}
                            {d.papers.slice(0, limit).map((p) => (
                              <details className="chat-paper" key={p.paper_id}>
                                <summary>
                                  <strong>{p.title}</strong>
                                  <small>{p.year || "Year unknown"}</small>
                                </summary>
                                <p>{p.abstract || "No abstract available."}</p>
                              </details>
                            ))}
                            {limit < d.papers.length && (
                              <button
                                className="secondary-button"
                                onClick={() => setLimit(limit + 10)}
                              >
                                Show more papers
                              </button>
                            )}
                            <button
                              className="text-button"
                              onClick={() => onTab("protocol")}
                            >
                              Edit search settings
                            </button>
                          </div>
                        )}
                        {reviewStage && remaining > 0 && (
                          <ReviewWorkspace
                            key={`${d.id}:${reviewStage}`}
                            detail={d}
                            stage={reviewStage}
                            reviewer={reviewer}
                            busy={blocked}
                            onSaved={onSaved}
                            onError={onError}
                            guided
                          />
                        )}
                        {reviewStage && remaining === 0 && (
                          <div className="chat-complete">
                            <Check size={20} />
                            <p>
                              {paused
                                ? "Processing is paused. Continue to finish preparing this phase."
                                : "This phase has no pending decisions."}
                            </p>
                            <button
                              className="text-button"
                              onClick={() => onTab(reviewStage)}
                            >
                              Inspect all items
                            </button>
                          </div>
                        )}
                        {phase === 5 && pendingAppraisal > 0 && (
                          <AppraisalPanel {...props} busy={blocked} />
                        )}
                        {phase === 5 && pendingAppraisal === 0 && (
                          <p>
                            Study assessments are saved. Validate this phase to
                            prepare the report.
                          </p>
                        )}
                        {phase === 6 && (
                          <>
                            <Report detail={d} />
                            <button
                              className="secondary-button"
                              onClick={() => setShowChecklist(!showChecklist)}
                            >
                              {showChecklist ? "Hide" : "Open"} PRISMA checklist
                            </button>
                            {showChecklist && (
                              <PrismaPanel {...props} busy={blocked} />
                            )}
                          </>
                        )}
                      </div>
                      <footer className="validation-actions">
                        <span>
                          {needsName
                            ? "Enter your reviewer name above."
                            : remaining
                              ? `${remaining} decisions remaining in this phase`
                              : paused
                                ? "Paused — resume from saved work."
                                : phase === 0
                                  ? "Approve the protocol in the card above."
                                  : "Waiting for your validation."}
                        </span>
                        <button
                          className="primary-button"
                          disabled={
                            blocked ||
                            remaining > 0 ||
                            !d.protocol?.approval ||
                            needsName ||
                            (!!d.report_current && !confirmation && d.writing?.ready !== false)
                          }
                          onClick={() => void continueReview()}
                        >
                          {working ? (
                            <LoaderCircle className="spin" size={15} />
                          ) : (
                            <ArrowRight size={15} />
                          )}
                          {phase === 6 && d.writing?.ready === false
                            ? "Resume scientific writing"
                            : confirmation?.stage === "quality"
                            ? "Validate & finish"
                            : confirmation
                              ? "Confirm & continue"
                              : "Continue"}
                        </button>
                      </footer>
                    </div>
                  )}
                </div>
              </div>
            </>
          )}
          <div ref={end} />
        </div>
      </div>
      <div className="composer-dock">
        <div className="composer-width">
          <form
            className="message-composer"
            onSubmit={(e) => {
              e.preventDefault();
              void send();
            }}
          >
            <textarea
              aria-label="Message the review assistant"
              placeholder={
                busy
                  ? "Processing this phase — you can pause to ask a question"
                  : "Ask about your review, criteria, or evidence…"
              }
              rows={2}
              maxLength={4000}
              disabled={busy || sending}
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void send();
                }
              }}
            />
            <div>
              <span>
                <span className="composer-indicator" />
                {busy
                  ? "Processing"
                  : sending
                    ? "Responding"
                    : "Ask anything about this review"}
              </span>
              <button
                type="submit"
                aria-label="Send message"
                disabled={!message.trim() || blocked}
              >
                {sending ? (
                  <LoaderCircle className="spin" size={19} />
                ) : (
                  <ArrowUp size={19} />
                )}
              </button>
            </div>
          </form>
          <p className="composer-note">
            AI guidance can be wrong. Check sources. Chat messages never approve
            papers or advance phases.
          </p>
        </div>
      </div>
    </section>
  );
}
