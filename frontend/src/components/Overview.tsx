import {
  ArrowRight,
  BookOpen,
  Check,
  ChevronRight,
  ClipboardCheck,
  FileText,
  Quote,
  ShieldCheck,
} from "lucide-react";
import { type Detail } from "../api";
import { isBusy, type Tab } from "../lib/review";
import { Badge, Empty } from "./ui";
export function Overview({
  detail: d,
  onTab,
  pendingTotal,
  currentStage,
}: {
  detail: Detail;
  onTab: (tab: Tab) => void;
  pendingTotal: number;
  currentStage: Tab;
}) {
  const quotes = d.evidence.reduce((n, e) => n + (e.claims?.length || 0), 0);
  const fullTexts = d.papers.filter(
    (p) => p.full_text_status === "retrieved",
  ).length;
  const metrics = [
    {
      label: "Records retrieved",
      value: d.paper_count,
      sub: "Title & abstract records",
      icon: BookOpen,
    },
    {
      label: "Full texts available",
      value: fullTexts,
      sub: `${d.queue.unavailable_full_texts.length} unavailable · ${d.queue.included_papers.length} eligible`,
      icon: FileText,
    },
    {
      label: "Source quotations",
      value: quotes,
      sub: "Candidates for human assessment",
      icon: Quote,
    },
    {
      label: "Decisions awaiting you",
      value: pendingTotal,
      sub: "Across the available review queues",
      icon: ClipboardCheck,
    },
  ];
  const steps = [
    { label: "Discover", names: ["retrieval"] },
    { label: "Screen", names: ["save"] },
    { label: "Full text", names: ["download"] },
    { label: "Extract", names: ["extraction"] },
    { label: "Review evidence", names: ["extraction"], gate: true },
    { label: "Report", names: ["quality"] },
  ];
  return (
    <>
      <section className="metric-grid" aria-label="Review statistics">
        {metrics.map(({ label, value, sub, icon: Icon }) => (
          <div className="metric-card" key={label}>
            <div className="metric-top">
              <span>{label}</span>
              <Icon size={17} />
            </div>
            <div className="metric-value">{String(value).padStart(2, "0")}</div>
            <div className="metric-sub">{sub}</div>
          </div>
        ))}
      </section>
      {pendingTotal > 0 && (
        <section className="attention-panel">
          <div className="attention-symbol">
            <ClipboardCheck size={25} strokeWidth={1.4} />
          </div>
          <div>
            <div className="eyebrow">A MOMENT FOR YOUR JUDGMENT</div>
            <h2>
              {isBusy(d)
                ? "Saved items are available to inspect."
                : "The next step is yours."}
            </h2>
            <p>
              {currentStage === "protocol"
                ? "Define and approve your research protocol before screening."
                : currentStage === "appraisal"
                  ? "Confirm study characteristics and appraisal judgements."
                  : currentStage === "prisma"
                    ? "Assess the manuscript against the reporting checklist."
                    : d.pending.screening
                      ? `${d.pending.screening} papers need a screening decision before the workflow can continue.`
                      : d.pending.eligibility
                        ? `${d.pending.eligibility} full texts are ready for your eligibility assessment.`
                        : `${d.pending.evidence} evidence items are ready to be checked against their sources.`}
            </p>
          </div>
          <button className="dark-button" onClick={() => onTab(currentStage)}>
            Open review queue <ArrowRight size={16} />
          </button>
        </section>
      )}
      <section className="panel workflow-panel">
        <div className="section-heading">
          <div>
            <span className="eyebrow">THE BIG PICTURE</span>
            <h2>Your review, step by step</h2>
          </div>
          <Badge>
            {d.completed.length} of {d.total_stages} workflow stages saved
          </Badge>
        </div>
        <div className="workflow-steps">
          {steps.map((s, i) => {
            const done = s.gate
              ? d.completed.includes("synthesis")
              : s.names.every((n) => d.completed.includes(n));
            return (
              <div
                key={s.label}
                className={`workflow-step ${done ? "done" : ""}`}
              >
                <div className="step-number">
                  {done ? <Check size={16} /> : `0${i + 1}`}
                </div>
                <span>{s.label}</span>
                <small>
                  {done
                    ? "Saved"
                    : s.gate && d.pending.evidence
                      ? "Awaiting review"
                      : "Upcoming"}
                </small>
              </div>
            );
          })}
        </div>
      </section>
      <div className="overview-columns">
        <section className="panel">
          <div className="section-heading">
            <div>
              <span className="eyebrow">YOUR READING DESK</span>
              <h2>Recently retrieved</h2>
            </div>
            <button className="text-button" onClick={() => onTab("screening")}>
              All papers <ArrowRight size={14} />
            </button>
          </div>
          {d.papers.length ? (
            <div className="recent-papers">
              {d.papers.slice(0, 4).map((p, i) => (
                <button key={p.paper_id} onClick={() => onTab("screening")}>
                  <span className="paper-index">
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  <div>
                    <strong>{p.title}</strong>
                    <span>
                      {p.year || "Year unavailable"} <span>·</span> {p.paper_id}
                    </span>
                  </div>
                  <ChevronRight size={15} />
                </button>
              ))}
            </div>
          ) : (
            <Empty title="No papers yet">
              Start the workflow to discover relevant research.
            </Empty>
          )}
        </section>
        <section className="principles-panel">
          <span className="eyebrow">A NOTE ON RIGOR</span>
          <div className="large-quote">“</div>
          <h2>
            Good research leaves
            <br />a paper trail.
          </h2>
          <p>
            Source quotations, explicit decisions, and honest gaps. Every step
            is saved so you can see how a conclusion was reached.
          </p>
          <div className="principle-bottom">
            <ShieldCheck size={19} />
            <span>Human judgment stays at the center.</span>
          </div>
        </section>
      </div>
    </>
  );
}
