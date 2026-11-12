import { useEffect, useRef, useState } from "react";
import { RefreshCw, Settings2 } from "lucide-react";
import { request } from "../api";
import { ThinkingControl } from "./ThinkingControl";
export type RunConfig = {
  model: string;
  thinking: string;
  mode: "guided" | "automatic";
  temperature: number;
  max_records: number;
  sources: string[];
  year_from: number | null;
  year_to: number | null;
};
export const defaultRunConfig: RunConfig = {
  model: "",
  thinking: "off",
  mode: "guided",
  temperature: 0,
  max_records: 10,
  sources: ["openalex", "pubmed", "arxiv"],
  year_from: null,
  year_to: null,
};
export function RunSetup({
  value,
  onChange,
  disabled,
}: {
  value: RunConfig;
  onChange: (v: RunConfig) => void;
  disabled: boolean;
}) {
  const latest = useRef(value);
  latest.current = value;
  const [models, setModels] = useState<{ name: string }[]>([]);
  const [controls, setControls] = useState<{
    available: boolean;
    options: { value: string; label: string }[];
  } | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  useEffect(() => {
    let valid = true;
    request<{
      models: { name: string }[];
      default_model: string;
      error: string | null;
    }>("/models")
      .then((data) => {
        if (!valid) return;
        setModels(data.models);
        setError(data.error || "");
        if (!latest.current.model && data.models.length)
          onChange({
            ...latest.current,
            model: data.models.some((m) => m.name === data.default_model)
              ? data.default_model
              : data.models[0].name,
          });
      })
      .catch((e) => {
        if (valid) setError(e.message);
      });
    return () => {
      valid = false;
    };
  }, [reload]);
  useEffect(() => {
    let valid = true;
    setLoading(true);
    setControls(null);
    request<{
      available: boolean;
      options: { value: string; label: string }[];
      error: string | null;
    }>(
      `/model-controls${value.model ? `?model=${encodeURIComponent(value.model)}` : ""}`,
    )
      .then((data) => {
        if (valid) {
          setControls(data);
          if (data.error) setError(data.error);
        }
      })
      .catch((e) => {
        if (valid) setError(e.message);
      })
      .finally(() => {
        if (valid) setLoading(false);
      });
    return () => {
      valid = false;
    };
  }, [value.model, reload]);
  return (
    <section
      className="run-setup"
      aria-label="Configure this conversation before sending a prompt"
    >
      <div className="run-setup-heading">
        <span>
          <Settings2 size={16} /> Run settings
        </span>
        <button
          type="button"
          className="icon-button"
          aria-label="Refresh available models"
          disabled={disabled}
          onClick={() => {
            setError("");
            setReload(reload + 1);
          }}
        >
          <RefreshCw size={15} />
        </button>
      </div>
      <div className="run-main-options">
        <label>
          Local model
          <select
            aria-label="Choose a local model"
            value={value.model}
            disabled={disabled}
            onChange={(e) =>
              onChange({ ...value, model: e.target.value, thinking: "off" })
            }
          >
            {!value.model && <option value="">Configured model</option>}
            {models.map((m) => (
              <option key={m.name} value={m.name}>
                {m.name}
              </option>
            ))}
          </select>
        </label>
        <ThinkingControl
          mode={value.thinking}
          controls={controls}
          loading={loading}
          disabled={disabled}
          onChange={(thinking) => onChange({ ...value, thinking })}
        />
      </div>
      <p className="qa-description">Thinking controls drafting and search. Critical eligibility checks may use additional reasoning to resolve contradictions.</p>
      <fieldset disabled={disabled} className="run-mode-options">
        <legend>How should this review run?</legend>
        <label className={value.mode === "guided" ? "selected" : ""}>
          <input
            type="radio"
            name="review-mode"
            value="guided"
            checked={value.mode === "guided"}
            onChange={() => onChange({ ...value, mode: "guided" })}
          />
          <span>
            <strong>Guided</strong>
            <small>You validate each phase.</small>
          </span>
        </label>
        <label className={value.mode === "automatic" ? "selected" : ""}>
          <input
            type="radio"
            name="review-mode"
            value="automatic"
            checked={value.mode === "automatic"}
            onChange={() => onChange({ ...value, mode: "automatic" })}
          />
          <span>
            <strong>Automated draft</strong>
            <small>
              Runs to a draft. You accept or reject the final result.
            </small>
          </span>
        </label>
      </fieldset>
      {value.mode === "automatic" && (
        <p className="automatic-notice">
          Intermediate decisions will be AI proposals. Accepting the final draft
          does not certify individual claims or scientific quality.
        </p>
      )}
      <details className="setup-advanced">
        <summary>Search and response parameters</summary>
        <div className="run-parameter-grid">
          <label>
            Records per query
            <input
              type="number"
              min={1}
              max={100}
              value={value.max_records}
              disabled={disabled}
              onChange={(e) =>
                onChange({ ...value, max_records: Number(e.target.value) })
              }
            />
          </label>
          <label>
            Response temperature
            <input
              type="number"
              min={0}
              max={1}
              step={0.1}
              value={value.temperature}
              disabled={disabled}
              onChange={(e) =>
                onChange({ ...value, temperature: Number(e.target.value) })
              }
            />
          </label>
        </div>
        <div className="run-parameter-grid">
          <label>Publication year · from
            <input type="number" min={1} max={9999} step={1} placeholder="No lower limit"
              aria-label="Publication start year" value={value.year_from ?? ""} disabled={disabled}
              onChange={(e) => onChange({ ...value, year_from: e.target.value === "" ? null : Number(e.target.value) })} />
          </label>
          <label>Publication year · to
            <input type="number" min={value.year_from ?? 1} max={9999} step={1} placeholder="No upper limit"
              aria-label="Publication end year" value={value.year_to ?? ""} disabled={disabled}
              onChange={(e) => onChange({ ...value, year_to: e.target.value === "" ? null : Number(e.target.value) })} />
          </label>
        </div>
        <small>Optional: leave both years blank to search all dates. Bounds include the full selected years. arXiv filters submission dates.</small>
        {value.year_from !== null && value.year_to !== null && value.year_from > value.year_to && <p role="alert">The start year must not be after the end year.</p>}
        <fieldset disabled={disabled}>
          <legend>Search sources · choose at least one</legend>
          {["openalex", "pubmed", "arxiv"].map((source) => (
            <label key={source}>
              <input
                type="checkbox"
                checked={value.sources.includes(source)}
                onChange={(e) =>
                  onChange({
                    ...value,
                    sources: e.target.checked
                      ? [...value.sources, source]
                      : value.sources.filter((s) => s !== source),
                  })
                }
              />
              {source}
            </label>
          ))}
        </fieldset>
        <small>
          Lower temperature gives more consistent responses. More records take
          longer to process.
        </small>
      </details>
      {error && (
        <p role="status" className="setup-error">
          {error}
        </p>
      )}
    </section>
  );
}
