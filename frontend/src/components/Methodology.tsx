import { PdfButton } from "./PdfViewer";
import { useState, type FormEvent } from "react";
import { apiUrl, request, type Detail } from "../api";
import { Badge, Empty } from "./ui";

type MethodProps = {
  detail: Detail;
  reviewer: string;
  busy: boolean;
  onSaved: () => Promise<void>;
  onError: (message: string) => void;
};
const lines = (value: string) =>
  value
    .split("\n")
    .map((v) => v.trim())
    .filter(Boolean);
export function ProtocolPanel({
  detail,
  reviewer,
  busy,
  onSaved,
  onError,
}: MethodProps) {
  const document = detail.protocol;
  const [value, setValue] = useState(document?.protocol);
  const [adopt, setAdopt] = useState(document?.adopt_existing || false);
  const [reason, setReason] = useState("");
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  async function action(path: string, body?: unknown) {
    setSaving(true);
    try {
      await request(`/reviews/${detail.id}/protocol${path}`, {
        method: "POST",
        body: body ? JSON.stringify(body) : undefined,
      });
      await onSaved();
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }
  if (!document || !value)
    return (
      <section className="panel">
        <Empty title="Define the review before screening.">
          Create a protocol draft, refine its criteria and search concepts, then
          explicitly approve it.
        </Empty>
        <div className="method-actions">
          <button
            className="primary-button"
            disabled={busy || saving}
            onClick={() => void action("/draft")}
          >
            Create protocol draft
          </button>
          <button
            className="secondary-button"
            disabled={busy || saving}
            onClick={() => void action("/suggest")}
          >
            Suggest with local planner
          </button>
        </div>
      </section>
    );
  function update(key: string, next: unknown) {
    setValue((v) => (v ? { ...v, [key]: next } : v));
    setDirty(true);
  }
  async function save(event: FormEvent) {
    event.preventDefault();
    await action("", {
      protocol: value,
      author: reviewer,
      adopt_existing: adopt,
    });
  }
  return (
    <section className="panel method-panel">
      <div className="section-heading">
        <h2>Review protocol · revision {document.revision}</h2>
        <Badge tone={document.approval ? "green" : "amber"}>
          {document.approval ? "Approved" : "Approval required"}
        </Badge>
      </div>
      <form
        onInvalid={(e) => {
          const section = (e.target as HTMLElement).closest("details");
          if (section) section.open = true;
        }}
        onSubmit={(e) => void save(e)}
      >
        <fieldset disabled={busy || saving}>
          <label className="form-label">
            Research question
            <textarea
              required
              value={value.research_question}
              onChange={(e) => update("research_question", e.target.value)}
            />
          </label>
          <label className="form-label">
            Rationale
            <textarea
              required
              value={value.rationale}
              onChange={(e) => update("rationale", e.target.value)}
            />
          </label>
          <div className="method-grid">
            <label className="form-label">
              Inclusion criteria · one per line
              <textarea
                rows={5}
                required
                value={value.inclusion_criteria.join("\n")}
                onChange={(e) =>
                  update("inclusion_criteria", lines(e.target.value))
                }
              />
            </label>
            <label className="form-label">
              Exclusion criteria · one per line
              <textarea
                rows={5}
                required
                value={value.exclusion_criteria.join("\n")}
                onChange={(e) =>
                  update("exclusion_criteria", lines(e.target.value))
                }
              />
            </label>
          </div>
          <label className="form-label">
            Search concepts · one group per line, synonyms separated by |
            <textarea
              rows={4}
              required
              value={value.concepts.map((g) => g.join(" | ")).join("\n")}
              onChange={(e) =>
                update(
                  "concepts",
                  lines(e.target.value).map((g) =>
                    g
                      .split("|")
                      .map((t) => t.trim())
                      .filter(Boolean),
                  ),
                )
              }
            />
          </label>
          <details className="advanced-settings">
            <summary>Optional PubMed vocabulary</summary>
            <label className="form-label">
              MeSH terms · optional, used only in PubMed
              <textarea
                value={value.mesh_terms.join("\n")}
                onChange={(e) => update("mesh_terms", lines(e.target.value))}
              />
            </label>
          </details>
          <div className="method-actions">
            {["openalex", "pubmed", "arxiv"].map((source) => (
              <label key={source}>
                <input
                  type="checkbox"
                  checked={value.sources.includes(source)}
                  onChange={(e) =>
                    update(
                      "sources",
                      e.target.checked
                        ? [...value.sources, source]
                        : value.sources.filter((s) => s !== source),
                    )
                  }
                />{" "}
                {source}
              </label>
            ))}
          </div>
          <details className="advanced-settings">
            <summary>Search limits, extraction and appraisal settings</summary>
            <p className="muted">
              Defaults are filled in. Review these settings when they need to
              change.
            </p>
            <div className="method-grid">
              <label className="form-label">
                Records per query
                <input
                  type="number"
                  min={1}
                  max={500}
                  value={value.max_records_per_query}
                  onChange={(e) =>
                    update("max_records_per_query", Number(e.target.value))
                  }
                />
              </label>
              <label className="form-label">
                Publication start · optional
                <input
                  type="date"
                  value={value.date_from || ""}
                  onChange={(e) => update("date_from", e.target.value || null)}
                />
              </label>
              <label className="form-label">
                Publication end · optional
                <input
                  type="date"
                  value={value.date_to || ""}
                  onChange={(e) => update("date_to", e.target.value || null)}
                />
              </label>
            </div>
            <label className="form-label">
              Extraction fields · one per line
              <textarea
                rows={5}
                value={value.extraction_fields.join("\n")}
                onChange={(e) =>
                  update("extraction_fields", lines(e.target.value))
                }
              />
            </label>
            <label className="form-label">
              Appraisal tool / rubric name
              <input
                required
                value={value.appraisal_name}
                onChange={(e) => update("appraisal_name", e.target.value)}
              />
            </label>
            <label className="form-label">
              Appraisal domains · id | question, one per line
              <textarea
                rows={6}
                value={value.appraisal_domains
                  .map((d) => `${d.id} | ${d.question}`)
                  .join("\n")}
                onChange={(e) =>
                  update(
                    "appraisal_domains",
                    lines(e.target.value).map((line) => {
                      const [id, ...q] = line.split("|");
                      return { id: id.trim(), question: q.join("|").trim() };
                    }),
                  )
                }
              />
              <small>
                The default rubric is project-defined. Choose design-appropriate
                domains; no validated instrument algorithm is implied.
              </small>
            </label>
            <label className="form-label">
              Synthesis plan
              <textarea
                value={value.synthesis_plan}
                onChange={(e) => update("synthesis_plan", e.target.value)}
              />
            </label>
            <div className="method-grid">
              {(["registration", "funding", "conflicts"] as const).map(
                (key) => (
                  <label className="form-label" key={key}>
                    {key}
                    <input
                      value={value[key]}
                      onChange={(e) => update(key, e.target.value)}
                    />
                  </label>
                ),
              )}
            </div>
            <label className="form-label">
              <span>
                <input
                  type="checkbox"
                  checked={value.meta_analysis}
                  onChange={(e) => update("meta_analysis", e.target.checked)}
                />{" "}
                Prepare meta-analysis inputs when comparable estimates are
                available
              </span>
            </label>
          </details>
          <label className="form-label">
            <span>
              <input
                type="checkbox"
                checked={adopt}
                onChange={(e) => {
                  setAdopt(e.target.checked);
                  setDirty(true);
                }}
              />{" "}
              Reuse existing search records, then rerun screening against this
              protocol
            </span>
            <small>
              Legacy search coverage remains explicitly unknown. Leave unchecked
              for new multi-source searches.
            </small>
          </label>
          <div className="method-actions">
            <button
              className="primary-button"
              disabled={!reviewer.trim() || saving}
            >
              Save new revision
            </button>
            <span>{reviewer.trim() || "Enter your reviewer name above"}</span>
          </div>
          <label className="form-label">
            Approval notes · optional
            <textarea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Add context about your approval if useful…"
            />
          </label>
          <button
            type="button"
            className="primary-button"
            disabled={
              dirty || !!document.approval || !reviewer.trim() || saving
            }
            onClick={() =>
              void action("/approve", {
                fingerprint: document.fingerprint,
                reviewer,
                reason,
              })
            }
          >
            {document.approval ? "Protocol approved" : "Approve saved protocol"}
          </button>
          {dirty && (
            <p className="muted">
              Save your changes before approving the protocol.
            </p>
          )}
        </fieldset>
      </form>
    </section>
  );
}

export function AppraisalPanel({
  detail,
  reviewer,
  busy,
  onSaved,
  onError,
}: MethodProps) {
  const [selected, setSelected] = useState("");
  const item =
    detail.appraisals.find((i) => i.paper_id === selected) ||
    detail.appraisals[0];
  if (!item)
    return (
      <section className="panel">
        <Empty title="Include a study to assess its quality.">
          Appraisal is performed against the approved protocol, with source
          support for substantive judgements.
        </Empty>
      </section>
    );
  return (
    <section className="panel method-panel">
      <div className="section-heading">
        <h2>Study characteristics & appraisal</h2>
        <Badge>
          {detail.appraisals.filter((i) => !i.assessment).length} pending
        </Badge>
      </div>
      <select
        value={item.paper_id}
        onChange={(e) => setSelected(e.target.value)}
      >
        {detail.appraisals.map((i) => (
          <option key={i.paper_id} value={i.paper_id}>
            {i.paper_id} · {i.assessment ? "Reviewed" : "Pending"}
          </option>
        ))}
      </select>
      <AppraisalForm
        key={`${item.paper_id}:${item.fingerprint}:${item.assessment?.timestamp || ""}`}
        {...{ detail, reviewer, busy, onError, item }}
        onSaved={async () => {
          await onSaved();
          const next = detail.appraisals.find(
            (i) => i.paper_id !== item.paper_id && !i.assessment,
          );
          if (next) setSelected(next.paper_id);
        }}
      />
    </section>
  );
}
function AppraisalForm({
  detail,
  reviewer,
  busy,
  onSaved,
  onError,
  item,
}: MethodProps & { item: Detail["appraisals"][number] }) {
  const fields = detail.protocol?.protocol.extraction_fields || [];
  const [domains, setDomains] = useState(
    item.domains.map(
      (d) =>
        item.assessment?.domains.find((v) => v.domain_id === d.id) || {
          domain_id: d.id,
          judgement: "",
          rationale: "",
          quote: "",
        },
    ),
  );
  const [characteristics, setCharacteristics] = useState<
    Record<string, { value: string; quote: string }>
  >(
    Object.fromEntries(
      fields.map((f) => [
        f,
        item.assessment?.characteristics?.[f] ||
          (() => {
            const candidate = detail.evidence
              .find((e) => e.paper_id === item.paper_id)
              ?.characteristic_proposals?.find((c) => c.field === f);
            return {
              value: "",
              quote: candidate?.quote || "",
            };
          })(),
      ]),
    ),
  );
  const [overall, setOverall] = useState(item.assessment?.overall || "");
  const [step, setStep] = useState(0);
  const total = fields.length + item.domains.length + 1;
  const [reason, setReason] = useState(item.assessment?.rationale || "");
  const [studyId, setStudyId] = useState(item.assessment?.study_id || "");
  const [saving, setSaving] = useState(false);
  const [quoteError, setQuoteError] = useState("");
  const paper = detail.papers.find((p) => p.paper_id === item.paper_id);
  async function save(e: FormEvent) {
    e.preventDefault();
    setQuoteError("");
    if (step < total - 1) {
      const activeField = fields[step];
      const quote = activeField
        ? characteristics[activeField].value.trim()
          ? characteristics[activeField].quote
          : ""
        : domains[step - fields.length]?.quote;
      if (quote?.trim()) {
        setSaving(true);
        try {
          await request(
            `/reviews/${detail.id}/appraisals/${item.paper_id}/check-quote`,
            { method: "POST", body: JSON.stringify({ quote }) },
          );
        } catch (error) {
          setQuoteError((error as Error).message);
          return;
        } finally {
          setSaving(false);
        }
      }
      setStep(step + 1);
      return;
    }
    const invalidField = fields.findIndex(
      (f) =>
        characteristics[f].value.trim() && !characteristics[f].quote.trim(),
    );
    if (invalidField >= 0) {
      onError(
        "Add a source quote for this study detail, or leave the value blank.",
      );
      setStep(invalidField);
      return;
    }
    const invalidDomain = domains.findIndex(
      (d) =>
        !d.judgement ||
        (d.judgement !== "unclear" && d.rationale.trim().length < 5) ||
        (!["unclear", "not_applicable"].includes(d.judgement) &&
          !d.quote.trim()),
    );
    if (invalidDomain >= 0) {
      onError("Complete the judgement and required support for this domain.");
      setStep(fields.length + invalidDomain);
      return;
    }
    if (domains.some((d) => !d.judgement)) {
      onError("Review each appraisal domain before saving.");
      setStep(fields.length + domains.findIndex((d) => !d.judgement));
      return;
    }
    setSaving(true);
    try {
      await request(`/reviews/${detail.id}/appraisals/${item.paper_id}`, {
        method: "POST",
        body: JSON.stringify({
          fingerprint: item.fingerprint,
          reviewer,
          overall,
          rationale: reason,
          domains: domains.map(
            ({ domain_id, judgement, rationale, quote }) => ({
              domain_id,
              judgement,
              rationale,
              quote,
            }),
          ),
          characteristics: Object.fromEntries(
            Object.entries(characteristics).map(([field, { value, quote }]) => [
              field,
              { value, quote },
            ]),
          ),
          study_id: studyId,
        }),
      });
      await onSaved();
    } catch (error) {
      const message = (error as Error).message;
      const location = message.match(/\[(domain|field):([^\]]+)\]/);
      if (location) {
        const index =
          location[1] === "domain"
            ? fields.length +
              domains.findIndex((d) => d.domain_id === location[2])
            : fields.indexOf(location[2]);
        if (index >= 0) setStep(index);
      }
      setQuoteError(message.replace(/\[(domain|field):[^\]]+\]\s*/, ""));
      onError(message);
    } finally {
      setSaving(false);
    }
  }
  const field = fields[step];
  const candidate = detail.evidence
    .find((e) => e.paper_id === item.paper_id)
    ?.characteristic_proposals?.find((c) => c.field === field);
  const domainIndex = step - fields.length;
  const domain = item.domains[domainIndex];
  const summary = step === total - 1;
  return (
    <form className="guided-assessment" onSubmit={(e) => void save(e)}>
      <h3>{paper?.title || item.paper_id}</h3>
      <div className="guided-toolbar">
        <span>
          Step {step + 1} of {total} ·{" "}
          {field
            ? "Study details"
            : summary
              ? "Finish assessment"
              : "Quality assessment"}
        </span>
        {paper?.files.pdf && (
          <PdfButton fileUrl={paper.files.pdf} title={paper.title} />
        )}
        {paper?.files.pdf && (
          <a
            className="secondary-button"
            target="_blank"
            rel="noreferrer"
            href={apiUrl(paper.files.pdf)}
          >
            Read source PDF
          </a>
        )}
      </div>
      <progress
        className="guided-progress"
        value={step + 1}
        max={total}
        aria-label="Assessment step"
      />
      <label className="form-label">
        Jump to section
        <select value={step} onChange={(e) => setStep(Number(e.target.value))}>
          {fields.map((f, i) => (
            <option key={f} value={i}>
              {i + 1}. {f.replaceAll("_", " ")}
            </option>
          ))}
          {item.domains.map((d, i) => (
            <option key={d.id} value={fields.length + i}>
              {fields.length + i + 1}. {d.question}
            </option>
          ))}
          <option value={total - 1}>Finish assessment</option>
        </select>
      </label>
      <AppraisalSourceText reviewId={detail.id} paperId={item.paper_id} />
      {quoteError && (
        <p className="quote-error" role="alert">
          {quoteError}
        </p>
      )}
      <fieldset disabled={busy || saving}>
        {field && (
          <div className="method-box" key={field}>
            {candidate && !characteristics[field].value && (
              <div className="context-note">
                <span>AI candidate — check the source before using</span>
                <blockquote>{candidate.quote}</blockquote>
                <button
                  type="button"
                  className="secondary-button"
                  onClick={() =>
                    setCharacteristics((v) => ({
                      ...v,
                      [field]: {
                        value: candidate.quote,
                        quote: candidate.quote,
                      },
                    }))
                  }
                >
                  Use this quotation
                </button>
              </div>
            )}
            <label className="form-label">
              {field.replaceAll("_", " ")} · optional
              <textarea
                rows={3}
                placeholder="Leave blank if not reported or not confirmed"
                value={characteristics[field].value}
                onChange={(e) =>
                  setCharacteristics((v) => ({
                    ...v,
                    [field]: { ...v[field], value: e.target.value },
                  }))
                }
              />
            </label>
            {characteristics[field].value.trim() && (
              <label className="form-label">
                Supporting source quote · required for a populated value
                <textarea
                  rows={3}
                  required
                  value={characteristics[field].quote}
                  onChange={(e) =>
                    setCharacteristics((v) => ({
                      ...v,
                      [field]: { ...v[field], quote: e.target.value },
                    }))
                  }
                />
              </label>
            )}
            <small>
              Any prefilled text is an AI proposal. Check it against the source
              before keeping it.
            </small>
            <button
              type="button"
              className="text-button"
              onClick={() => {
                setCharacteristics((v) => ({
                  ...v,
                  [field]: { value: "", quote: "" },
                }));
                setStep(step + 1);
              }}
            >
              Not reported / skip this field →
            </button>
            {step < fields.length - 1 && (
              <button
                type="button"
                className="text-button"
                onClick={() => {
                  setCharacteristics((v) => ({
                    ...v,
                    ...Object.fromEntries(
                      fields
                        .slice(step)
                        .map((f) => [f, { value: "", quote: "" }]),
                    ),
                  }));
                  setStep(fields.length);
                }}
              >
                Leave remaining optional details blank →
              </button>
            )}
          </div>
        )}
        {!field && !summary && domain && (
          <div className="method-box" key={domain.id}>
            <h3>{domain.question}</h3>
            <p className="muted">{item.tool}</p>
            <label className="form-label">
              Your judgement · required
              <select
                required
                value={domains[domainIndex].judgement}
                onChange={(e) =>
                  setDomains((v) =>
                    v.map((d, i) =>
                      i === domainIndex
                        ? { ...d, judgement: e.target.value }
                        : d,
                    ),
                  )
                }
              >
                <option value="">Choose a judgement…</option>
                {[
                  "low",
                  "some_concerns",
                  "high",
                  "unclear",
                  "not_applicable",
                ].map((v) => (
                  <option key={v} value={v}>
                    {v.replaceAll("_", " ")}
                  </option>
                ))}
              </select>
            </label>
            {domains[domainIndex].judgement && (
              <>
                <label className="form-label">
                  {domains[domainIndex].judgement === "unclear"
                    ? "Notes · optional"
                    : "Reason · required"}
                  <textarea
                    rows={2}
                    required={domains[domainIndex].judgement !== "unclear"}
                    minLength={
                      domains[domainIndex].judgement !== "unclear"
                        ? 5
                        : undefined
                    }
                    value={domains[domainIndex].rationale}
                    onChange={(e) =>
                      setDomains((v) =>
                        v.map((d, i) =>
                          i === domainIndex
                            ? { ...d, rationale: e.target.value }
                            : d,
                        ),
                      )
                    }
                  />
                </label>
                <label className="form-label">
                  Supporting source quote ·{" "}
                  {!["unclear", "not_applicable"].includes(
                    domains[domainIndex].judgement,
                  )
                    ? "required"
                    : "optional"}
                  <textarea
                    rows={3}
                    required={
                      !["unclear", "not_applicable"].includes(
                        domains[domainIndex].judgement,
                      )
                    }
                    value={domains[domainIndex].quote}
                    onChange={(e) =>
                      setDomains((v) =>
                        v.map((d, i) =>
                          i === domainIndex
                            ? { ...d, quote: e.target.value }
                            : d,
                        ),
                      )
                    }
                  />
                </label>
              </>
            )}
          </div>
        )}
        {summary && (
          <div className="method-box">
            <p>
              {
                Object.values(characteristics).filter((c) => c.value.trim())
                  .length
              }{" "}
              study details populated ·{" "}
              {domains.filter((d) => d.judgement).length} of {domains.length}{" "}
              domains reviewed.
            </p>
            <label className="form-label">
              Overall judgement · required
              <select
                required
                value={overall}
                onChange={(e) => setOverall(e.target.value)}
              >
                <option value="">Choose a judgement…</option>
                {[
                  "low",
                  "some_concerns",
                  "high",
                  "unclear",
                  "not_applicable",
                ].map((v) => (
                  <option key={v} value={v}>
                    {v.replaceAll("_", " ")}
                  </option>
                ))}
              </select>
            </label>
            <label className="form-label">
              {overall === "unclear"
                ? "Overall notes · optional"
                : "Overall reason · required"}
              <textarea
                rows={2}
                required={overall !== "unclear"}
                minLength={overall !== "unclear" ? 5 : undefined}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
              />
            </label>
            <label className="form-label">
              Study identifier · optional
              <input
                value={studyId}
                onChange={(e) => setStudyId(e.target.value)}
                placeholder="For linking reports of the same study"
              />
            </label>
            {!reviewer.trim() && (
              <p>
                Enter your reviewer name at the top of the page before saving.
              </p>
            )}
          </div>
        )}
        <div className="guided-footer">
          <button
            type="button"
            className="secondary-button"
            disabled={step === 0}
            onClick={() => setStep(step - 1)}
          >
            Back
          </button>
          <span>
            {summary
              ? "Save confirms the details and judgements you reviewed."
              : "Your edits stay here while moving between steps."}
          </span>
          <button
            className="primary-button"
            disabled={saving || (summary && !reviewer.trim())}
          >
            {saving ? "Saving…" : summary ? "Save assessment" : "Next →"}
          </button>
        </div>
      </fieldset>
    </form>
  );
}

function AppraisalSourceText({
  reviewId,
  paperId,
}: {
  reviewId: string;
  paperId: string;
}) {
  const [text, setText] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  async function load() {
    if (text !== null || loading) return;
    setLoading(true);
    setError("");
    try {
      const result = await request<{ text: string }>(
        `/reviews/${reviewId}/appraisals/${paperId}/source`,
      );
      setText(result.text);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }
  return (
    <details
      className="advanced-settings"
      onToggle={(e) => {
        if (e.currentTarget.open) void load();
      }}
    >
      <summary>Source text — copy exact supporting quotations</summary>
      <p className="muted">
        This is the text used by quote verification. Copy one continuous
        passage. Write your interpretation in Reason. PDF reference sections are
        excluded.
      </p>
      {loading && <p role="status">Loading source text…</p>}
      {error && (
        <p role="alert">
          {error}{" "}
          <button type="button" onClick={() => void load()}>
            Retry
          </button>
        </p>
      )}
      {text !== null &&
        (text ? (
          <textarea
            aria-label="Source body text for quotation"
            readOnly
            rows={10}
            value={text}
          />
        ) : (
          <p>
            No extractable body text is available. A supported quotation cannot
            be verified from this source.
          </p>
        ))}
    </details>
  );
}

export function PrismaPanel({
  detail,
  reviewer,
  busy,
  onSaved,
  onError,
}: MethodProps) {
  const [selected, setSelected] = useState("1");
  const item = detail.prisma?.items.find((i) => i.id === selected);
  if (!detail.prisma || !item)
    return (
      <section className="panel">
        <Empty title="Generate the manuscript before checking its reporting.">
          The reporting checklist is tied to the manuscript fingerprint; edits
          invalidate earlier checks.
        </Empty>
      </section>
    );
  return (
    <section className="panel method-panel">
      <div className="section-heading">
        <h2>PRISMA reporting assessment</h2>
        <a href={detail.prisma.source} target="_blank" rel="noreferrer">
          Official guidance
        </a>
      </div>
      <p className="muted">
        Artifact generation alone does not establish compliance. Review each
        item against the official checklist and record a manuscript location or
        an explicit applicability rationale.
      </p>
      <select value={selected} onChange={(e) => setSelected(e.target.value)}>
        {detail.prisma.items.map((i) => (
          <option key={i.id} value={i.id}>
            {i.id} · {i.topic} · {i.status}
          </option>
        ))}
      </select>
      <p className="muted">
        {
          detail.prisma.items.filter(
            (i) =>
              i.status !== "requires_human_review" && i.status !== "missing",
          ).length
        }{" "}
        of {detail.prisma.items.length} items addressed
      </p>
      <h3>
        {item.id}. {item.topic}
      </h3>
      <ChecklistForm
        key={`${item.id}:${detail.prisma.report_fingerprint}`}
        {...{ detail, reviewer, busy, onError, item }}
        onSaved={async () => {
          await onSaved();
          const next = detail.prisma!.items.find(
            (i) =>
              i.id !== item.id &&
              (i.status === "requires_human_review" || i.status === "missing"),
          );
          if (next) setSelected(next.id);
        }}
      />
    </section>
  );
}
function ChecklistForm({
  detail,
  reviewer,
  busy,
  onSaved,
  onError,
  item,
}: MethodProps & { item: NonNullable<Detail["prisma"]>["items"][number] }) {
  const [status, setStatus] = useState(
    item.status === "requires_human_review" ? "missing" : item.status,
  );
  const [location, setLocation] = useState(item.location);
  const [reason, setReason] = useState(item.reason);
  const [saving, setSaving] = useState(false);
  async function save(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      await request(`/reviews/${detail.id}/prisma/${item.id}`, {
        method: "POST",
        body: JSON.stringify({
          fingerprint: detail.prisma!.report_fingerprint,
          status,
          location,
          reason,
          reviewer,
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
    <form onSubmit={(e) => void save(e)}>
      {item.suggested_location && <p className="muted">Suggested section: {item.suggested_location}. Verify it before marking this item as reported.</p>}
      <fieldset disabled={busy || saving}>
        <label className="form-label">
          Status
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            {["reported", "not_applicable", "missing"].map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </label>
        <label className="form-label">
          Manuscript location
          <input
            value={location}
            required={status === "reported"}
            onChange={(e) => setLocation(e.target.value)}
          />
        </label>
        <label className="form-label">
          {status === "reported" ? "Notes · optional" : "Reason · required"}
          <textarea
            value={reason}
            required={status !== "reported"}
            onChange={(e) => setReason(e.target.value)}
          />
        </label>
        <button
          className="primary-button"
          disabled={!reviewer.trim() || saving}
        >
          Save & next item
        </button>
      </fieldset>
    </form>
  );
}
