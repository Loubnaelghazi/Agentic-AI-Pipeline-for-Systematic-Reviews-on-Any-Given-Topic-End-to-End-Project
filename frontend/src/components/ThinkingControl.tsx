export type ThinkingControls = {
  available: boolean;
  options: { value: string; label: string }[];
};
export function ThinkingControl({
  mode = "off",
  controls,
  loading,
  disabled,
  onChange,
}: {
  mode?: string;
  controls: ThinkingControls | null;
  loading: boolean;
  disabled: boolean;
  onChange: (mode: string) => void;
}) {
  const options = controls?.options || [];
  const binary =
    !controls || !controls.available || options.some((o) => o.value === "on");
  const on = mode !== "off" && mode !== "default";
  return (
    <div className="thinking-switch" aria-label="Thinking mode" title="Thinking for drafting and search. Critical eligibility checks may use additional reasoning.">
      <span>Thinking</span>
      {binary ? (
        <>
          <button
            type="button"
            aria-label="Turn thinking off"
            aria-pressed={!on}
            className={!on ? "active" : ""}
            disabled={
              disabled || loading || !options.some((o) => o.value === "off")
            }
            onClick={() => onChange("off")}
          >
            Off
          </button>
          <button
            type="button"
            aria-label="Turn thinking on"
            aria-pressed={on}
            className={on ? "active" : ""}
            disabled={
              disabled || loading || !options.some((o) => o.value === "on")
            }
            onClick={() => onChange("on")}
          >
            On
          </button>
        </>
      ) : (
        <select
          aria-label="Model thinking mode"
          value={mode}
          disabled={disabled || loading}
          onChange={(e) => onChange(e.target.value)}
        >
          <option value="off">Off unavailable</option>
          {options
            .filter((o) => o.value !== "default" && o.value !== "off")
            .map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
        </select>
      )}
    </div>
  );
}
