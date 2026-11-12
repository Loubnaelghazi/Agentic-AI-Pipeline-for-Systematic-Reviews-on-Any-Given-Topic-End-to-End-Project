import { Activity, Check, LoaderCircle } from "lucide-react";
import { readable, type Detail } from "../api";
import { isBusy, time } from "../lib/review";
import { Badge, Empty } from "./ui";
export function ActivityPanel({ detail: d }: { detail: Detail }) {
  return (
    <div className="activity-columns">
      <section className="panel">
        <div className="section-heading">
          <div>
            <span className="eyebrow">EVERY DECISION HAS A HISTORY</span>
            <h2>Review activity</h2>
          </div>
          <Badge>{d.decisions.length} decisions</Badge>
        </div>
        {d.decisions.length ? (
          <ol className="timeline">
            {[...d.decisions].reverse().map((event, i) => (
              <li key={`${event.timestamp}:${i}`}>
                <span className="timeline-dot">
                  <Check size={12} />
                </span>
                <div>
                  <div className="timeline-heading">
                    <strong>{event.reviewer}</strong>
                    <Badge
                      tone={
                        ["include", "approve"].includes(event.decision)
                          ? "green"
                          : ""
                      }
                    >
                      {readable(event.decision)}
                    </Badge>
                  </div>
                  <p>{event.reason}</p>
                  <small>
                    {readable(event.stage)} · {event.item_id} ·{" "}
                    {time(event.timestamp)}
                  </small>
                </div>
              </li>
            ))}
          </ol>
        ) : (
          <Empty icon={Activity} title="A fresh page in the record.">
            Your decisions and rationales will appear here as you assess papers
            and evidence.
          </Empty>
        )}
      </section>
      <div>
        <section className="panel run-panel">
          <div className="section-heading">
            <div>
              <span className="eyebrow">WORKFLOW EXECUTION</span>
              <h2>Run log</h2>
            </div>
            {isBusy(d) && <LoaderCircle className="spin" size={18} />}
          </div>
          {d.job.id ? (
            <>
              <Badge tone={d.job.status === "failed" ? "amber" : ""}>
                {readable(d.job.status || "Unknown")}
              </Badge>
              {d.job.error && <p className="job-error">{d.job.error}</p>}
              <pre className="run-log">
                {d.job.log || "Waiting for workflow output…"}
              </pre>
              <p className="run-time">
                Started {d.job.started_at ? time(d.job.started_at) : "—"}
                {d.job.finished_at
                  ? ` · Finished ${time(d.job.finished_at)}`
                  : ""}
              </p>
            </>
          ) : (
            <p className="muted">
              Start or resume the workflow to see its progress here.
            </p>
          )}
        </section>
        {d.errors.length > 0 && (
          <section className="panel error-history">
            <h3>Recorded workflow errors</h3>
            {[...d.errors].reverse().map((e, i) => (
              <div key={i}>
                <strong>{readable(e.stage)}</strong>
                <p>{e.error}</p>
              </div>
            ))}
          </section>
        )}
      </div>
    </div>
  );
}
