import { defaultRunConfig } from "./components/RunSetup";
import { RunSettings } from "./components/RunSettings";
import { preferredTheme, saveTheme } from "./lib/theme";
import { PaperLibrary } from "./components/PaperLibrary";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowUp,
  BookOpen,
  Check,
  LoaderCircle,
  Menu,
  Moon,
  MessageSquare,
  Plus,
  Search,
  Settings2,
  Sun,
  X,
} from "lucide-react";
import { request, type Detail, type Review, type Stage } from "./api";
import { Conversation } from "./components/Conversation";
import { ActivityPanel } from "./components/ActivityPanel";
import { Overview } from "./components/Overview";
import {
  ProtocolPanel,
  AppraisalPanel,
  PrismaPanel,
} from "./components/Methodology";
import { Report } from "./components/Report";
import { ReviewWorkspace } from "./components/ReviewWorkspace";
import { isBusy, tabs, type Tab } from "./lib/review";

export default function App() {
  const [reviews, setReviews] = useState<Review[]>([]);
  const [selected, setSelected] = useState(
    new URLSearchParams(location.search).get("review") || "",
  );
  const [detail, setDetail] = useState<Detail | null>(null);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [topic, setTopic] = useState("");
  const [runConfig, setRunConfig] = useState(defaultRunConfig);
  const [theme, setTheme] = useState(preferredTheme);
  const [filter, setFilter] = useState("");
  const [error, setError] = useState("");
  const [mobile, setMobile] = useState(false);
  const [drawer, setDrawer] = useState<Tab | null>(null);
  const [reviewer, setReviewer] = useState(
    localStorage.getItem("folio-reviewer") || "",
  );
  const active = useRef(selected);
  active.current = selected;
  const busy = isBusy(detail);
  const refresh = useCallback(async () => {
    if (!selected) return;
    const value = await request<Detail>(
      `/reviews/${encodeURIComponent(selected)}`,
    );
    if (active.current === selected) setDetail(value);
  }, [selected]);
  useEffect(() => {
    let valid = true;
    request<Review[]>("/reviews")
      .then((list) => {
        if (valid) {
          setReviews(list);
          if (selected && !list.some((r) => r.id === selected)) setSelected("");
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
  }, []);
  useEffect(() => {
    setDetail(null);
    setError("");
    setDrawer(null);
    if (!selected) {
      history.replaceState(null, "", location.pathname);
      return;
    }
    history.replaceState(null, "", `?review=${encodeURIComponent(selected)}`);
    setLoading(true);
    void refresh()
      .catch((e) => {
        if (active.current === selected) setError(e.message);
      })
      .finally(() => {
        if (active.current === selected) setLoading(false);
      });
  }, [selected, refresh]);
  useEffect(() => {
    if (!selected) return;
    const timer = setInterval(
      () => void refresh().catch((e) => setError(e.message)),
      busy ? 1500 : 10000,
    );
    return () => clearInterval(timer);
  }, [selected, busy, refresh]);
  useEffect(() => {
    localStorage.setItem("folio-reviewer", reviewer);
  }, [reviewer]);
  useEffect(() => {
    if (!drawer) return;
    const previous = document.activeElement as HTMLElement | null;
    const close = (e: KeyboardEvent) => {
      if (e.key === "Escape") setDrawer(null);
      if (e.key !== "Tab") return;
      const dialog = document.querySelector<HTMLElement>(".review-drawer");
      const controls = Array.from(
        dialog?.querySelectorAll<HTMLElement>(
          'button:not(:disabled), a[href], input:not(:disabled), textarea:not(:disabled), select:not(:disabled), [tabindex="0"]',
        ) || [],
      ).filter((el) => el.getClientRects().length > 0);
      const first = controls[0],
        last = controls[controls.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last?.focus();
      }
      if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first?.focus();
      }
    };
    window.addEventListener("keydown", close);
    return () => {
      window.removeEventListener("keydown", close);
      previous?.focus();
    };
  }, [drawer !== null]);
  function choose(id: string) {
    if (!id) setRunConfig((current) => ({ ...current, thinking: "off" }));
    setSelected(id);
    setMobile(false);
    setDrawer(null);
    setError("");
  }
  async function createReview(e?: React.FormEvent) {
    e?.preventDefault();
    if (!topic.trim() || creating) return;
    if (
      !runConfig.sources.length ||
      runConfig.max_records < 1 ||
      runConfig.max_records > 100
    ) {
      setError(
        "Choose at least one source and a record limit between 1 and 100.",
      );
      return;
    }
    const years = [runConfig.year_from, runConfig.year_to];
    if (years.some((y) => y !== null && (!Number.isInteger(y) || y < 1 || y > 9999)) ||
        (runConfig.year_from !== null && runConfig.year_to !== null && runConfig.year_from > runConfig.year_to)) {
      setError("Enter valid years; the start year must not be after the end year.");
      return;
    }
    setCreating(true);
    setError("");
    try {
      const review = await request<Review>("/reviews", {
        method: "POST",
        body: JSON.stringify({
          topic: topic.trim(),
          configuration: { ...runConfig, model: runConfig.model || null },
        }),
      });
      setReviews((list) => [review, ...list]);
      setTopic("");
      choose(review.id);
      await request(`/reviews/${review.id}/protocol/draft`, { method: "POST" });
      if (runConfig.mode === "automatic")
        await request(`/reviews/${review.id}/run`, { method: "POST" });
      const createdDetail = await request<Detail>(`/reviews/${review.id}`);
      if (active.current === review.id) setDetail(createdDetail);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setCreating(false);
    }
  }
  async function saved() {
    setError("");
    await refresh();
  }
  async function run() {
    setError("");
    if (!detail || busy) return;
    await request(`/reviews/${detail.id}/run`, { method: "POST" });
    await refresh();
  }
  const stage =
    drawer && ["screening", "eligibility", "evidence"].includes(drawer)
      ? (drawer as Stage)
      : null;
  const methodProps = detail
    ? { detail, reviewer, busy, onSaved: saved, onError: setError }
    : null;
  return (
    <div className="chat-app">
      {mobile && (
        <button
          className="sidebar-backdrop"
          aria-label="Close conversations"
          onClick={() => setMobile(false)}
        />
      )}
      <aside className={`chat-sidebar ${mobile ? "open" : ""}`}>
        <button className="brand" onClick={() => choose("")}>
          <span>
            <BookOpen size={20} />
          </span>
          folio<span className="brand-dot">.</span>
        </button>
        <button className="new-chat" onClick={() => choose("")}>
          <Plus size={18} /> New conversation
        </button>
        <label className="conversation-search">
          <Search size={15} />
          <input
            aria-label="Find conversations"
            placeholder="Find a conversation"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
        </label>
        <div className="sidebar-caption">YOUR REVIEWS</div>
        <nav className="conversation-list" aria-label="Review conversations">
          {reviews
            .filter((r) => r.topic.toLowerCase().includes(filter.toLowerCase()))
            .map((r) => (
              <button
                key={r.id}
                className={selected === r.id ? "selected" : ""}
                onClick={() => choose(r.id)}
              >
                <MessageSquare size={15} />
                <span>{r.topic}</span>
              </button>
            ))}
          {!reviews.length && <p>Your conversations will appear here.</p>}
        </nav>
        <div className="sidebar-account">
          <span className="account-avatar">
            {reviewer.trim()[0]?.toUpperCase() || "Y"}
          </span>
          <div>
            <strong>{reviewer.trim() || "Your workspace"}</strong>
            <small>Local research assistant</small>
          </div>
          <Check size={14} />
        </div>
      </aside>
      <main className="chat-main">
        <header className="app-topbar">
          <button
            className="icon-button mobile-menu"
            aria-label="Open conversations"
            onClick={() => setMobile(true)}
          >
            <Menu size={20} />
          </button>
          <span>
            Folio <span className="topbar-divider">/</span>{" "}
            {selected ? "Research conversation" : "New conversation"}
          </span>
          <div>
            <button
              type="button"
              className="icon-button theme-toggle"
              aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
              title={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
              onClick={() => {
                const next = theme === "dark" ? "light" : "dark";
                saveTheme(next);
                setTheme(next);
              }}
            >
              {theme === "dark" ? <Sun size={19} /> : <Moon size={19} />}
            </button>
            <label className="reviewer-input">
              Reviewer
              <input
                aria-label="Reviewer name"
                placeholder="Your name · saved once"
                value={reviewer}
                onChange={(e) => setReviewer(e.target.value)}
              />
            </label>
            {detail && (
              <button
                className="icon-button"
                aria-label="Open review details"
                title="Review details and files"
                onClick={() =>
                  setDrawer(
                    detail.runtime_settings?.mode === "automatic"
                      ? "report"
                      : "overview",
                  )
                }
              >
                <Settings2 size={19} />
              </button>
            )}
          </div>
        </header>
        {error && (
          <div className="app-error" role="alert">
            <span>
              {error === "Failed to fetch"
                ? "Cannot reach the backend. Check that Docker is running."
                : error}
            </span>
            <button
              className="icon-button"
              aria-label="Dismiss error"
              onClick={() => setError("")}
            >
              <X size={16} />
            </button>
          </div>
        )}
        {loading && selected && !detail ? (
          <div className="loading-screen">
            <LoaderCircle className="spin" size={26} />
            <p>Opening conversation…</p>
          </div>
        ) : detail ? (
          <Conversation
            key={selected}
            detail={detail}
            reviewer={reviewer}
            onSaved={saved}
            onError={setError}
            onRun={run}
            onTab={setDrawer}
          />
        ) : (
          <section className="chat-welcome">
            <div className="welcome-intro">
              <span className="welcome-logo">
                <BookOpen size={30} />
              </span>
              <p className="welcome-eyebrow">YOUR RESEARCH STARTS HERE</p>
              <h1>
                What would you like
                <br />
                to investigate?
              </h1>
              <p className="welcome-description">
                {runConfig.mode === "automatic"
                  ? "Ask a question. I’ll prepare a research draft for your final review."
                  : "Ask a question. Find the evidence. Review each step together."}
              </p>
            </div>
            <div className="welcome-composer">
              <form id="new-review-form" onSubmit={(e) => void createReview(e)}>
                <textarea
                  aria-label="Research question"
                  placeholder="Ask a research question…"
                  rows={3}
                  maxLength={2000}
                  value={topic}
                  onChange={(e) => setTopic(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      void createReview();
                    }
                  }}
                />
              </form>
              <div className="welcome-composer-actions">
                <RunSettings
                  value={runConfig}
                  onChange={setRunConfig}
                  disabled={creating}
                />
                <button
                  type="submit"
                  form="new-review-form"
                  className="send-prompt"
                  aria-label="Start research conversation"
                  disabled={!topic.trim() || creating}
                >
                  {creating ? (
                    <LoaderCircle className="spin" size={20} />
                  ) : (
                    <ArrowUp size={20} />
                  )}
                </button>
              </div>
            </div>
            <small className="welcome-keyboard-hint">
              Enter to start · Shift + Enter for a new line
            </small>
            <div className="starter-prompts">
              {[
                "How is AI used in systematic reviews?",
                "Deep learning for medical image classification",
                "What improves renewable energy forecasting?",
              ].map((p) => (
                <button key={p} onClick={() => setTopic(p)}>
                  {p}
                </button>
              ))}
            </div>
            <small className="welcome-note">
              Local models. Source-linked evidence. Your decisions.
            </small>
          </section>
        )}
      </main>
      {drawer && detail && methodProps && (
        <div
          className="drawer-overlay"
          onClick={(e) => {
            if (e.target === e.currentTarget) setDrawer(null);
          }}
        >
          <section
            className="review-drawer"
            role="dialog"
            aria-modal="true"
            aria-label="Review details"
          >
            <header>
              <h2>Review details</h2>
              <button
                className="icon-button"
                autoFocus
                aria-label="Close review details"
                onClick={() => setDrawer(null)}
              >
                <X size={20} />
              </button>
            </header>
            <nav>
              {tabs
                .filter(
                  (t) =>
                    t.id !== "conversation" &&
                    (detail.runtime_settings?.mode !== "automatic" ||
                      ["papers", "report", "prisma", "activity"].includes(t.id)),
                )
                .map((t) => (
                  <button
                    key={t.id}
                    className={drawer === t.id ? "active" : ""}
                    onClick={() => setDrawer(t.id)}
                  >
                    {t.title}
                  </button>
                ))}
            </nav>
            <div className="drawer-body">
              {drawer === "papers" && <PaperLibrary detail={detail} />}
              {drawer === "overview" && (
                <Overview
                  detail={detail}
                  pendingTotal={Object.values(detail.pending).reduce(
                    (a, b) => a + b,
                    0,
                  )}
                  currentStage={
                    !detail.protocol?.approval
                      ? "protocol"
                      : detail.pending.screening
                        ? "screening"
                        : detail.pending.eligibility
                          ? "eligibility"
                          : "evidence"
                  }
                  onTab={setDrawer}
                />
              )}
              {drawer === "protocol" && (
                <ProtocolPanel
                  key={detail.protocol?.fingerprint}
                  {...methodProps}
                />
              )}
              {drawer === "appraisal" && <AppraisalPanel {...methodProps} />}
              {drawer === "prisma" && <PrismaPanel {...methodProps} />}
              {drawer === "report" && <Report detail={detail} />}
              {drawer === "activity" && <ActivityPanel detail={detail} />}
              {stage && (
                <ReviewWorkspace
                  key={stage}
                  detail={detail}
                  stage={stage}
                  reviewer={reviewer}
                  busy={busy}
                  onSaved={saved}
                  onError={setError}
                  guided
                />
              )}
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
