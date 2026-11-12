import { useEffect, useRef, useState } from "react";
import { ChevronDown, Settings2, X } from "lucide-react";
import { RunSetup, type RunConfig } from "./RunSetup";

export function RunSettings({
  value,
  onChange,
  disabled,
}: {
  value: RunConfig;
  onChange: (value: RunConfig) => void;
  disabled: boolean;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (disabled) dialog.current?.close();
  }, [disabled]);
  return (
    <>
      <button
        ref={trigger}
        className="run-settings-trigger"
        type="button"
        aria-label="Open run settings"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls="run-settings-dialog"
        disabled={disabled}
        onClick={() => {
          dialog.current?.showModal();
          setOpen(true);
        }}
      >
        <Settings2 size={16} />
        <span className="settings-trigger-label">Settings</span>
        <span className="settings-model">{value.model || "Local model"}</span>
        <span className="settings-mode">
          {value.mode === "automatic" ? "Automated" : "Guided"}
        </span>
        <span className="settings-thinking">
          Thinking {value.thinking === "off" ? "off" : value.thinking}
        </span>
        <ChevronDown size={14} />
      </button>
      <dialog
        ref={dialog}
        id="run-settings-dialog"
        className="run-settings-dialog"
        aria-labelledby="run-settings-title"
        onClose={() => {
          setOpen(false);
          trigger.current?.focus();
        }}
        onClick={(e) => {
          if (e.target === e.currentTarget) dialog.current?.close();
        }}
      >
        <div className="run-settings-panel">
          <header>
            <div>
              <h2 id="run-settings-title">Set up your research</h2>
              <p>Adjust these before sending your question.</p>
            </div>
            <button
              type="button"
              className="icon-button"
              aria-label="Close run settings"
              onClick={() => dialog.current?.close()}
            >
              <X size={20} />
            </button>
          </header>
          <div className="run-settings-body">
            <RunSetup value={value} onChange={onChange} disabled={disabled} />
          </div>
          <footer>
            <span>Changes apply to this new conversation.</span>
            <button
              type="button"
              className="primary-button"
              onClick={() => dialog.current?.close()}
            >
              Done
            </button>
          </footer>
        </div>
      </dialog>
    </>
  );
}
