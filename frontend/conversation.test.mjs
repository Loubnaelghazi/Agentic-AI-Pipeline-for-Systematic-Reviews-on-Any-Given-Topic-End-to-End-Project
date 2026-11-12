import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { build } from "esbuild";

// Render the real TSX with React; no model calls or browser globals are needed.
const compiled = await build({
  stdin: {
    resolveDir: fileURLToPath(new URL(".", import.meta.url)),
    loader: "tsx",
    contents: `import React from "react";
      import { renderToStaticMarkup } from "react-dom/server";
      import { Conversation } from "./src/components/Conversation";
      import App from "./src/App";
      export { preferredTheme, saveTheme } from "./src/lib/theme";
      import { RunSetup, defaultRunConfig } from "./src/components/RunSetup";
      import { Report } from "./src/components/Report";
      export const renderSetup = (changes = {}) => renderToStaticMarkup(<RunSetup value={{...defaultRunConfig,...changes}} onChange={() => {}} disabled={false} />);
      export const renderReport = (detail) => renderToStaticMarkup(<Report detail={detail} />);
      import { ThinkingControl } from "./src/components/ThinkingControl";
      import { PdfViewer } from "./src/components/PdfViewer";
      export const renderThinking = (controls) => renderToStaticMarkup(<ThinkingControl controls={controls} loading={false} disabled={false} onChange={() => {}} />);
      export const renderPdf = () => renderToStaticMarkup(<PdfViewer fileUrl="/api/reviews/fixture/papers/W1/file?format=pdf" title="Original paper" onClose={() => {}} />);
      export const renderHome = () => renderToStaticMarkup(<App />);
      export const render = (detail) => renderToStaticMarkup(<Conversation detail={detail} reviewer="Test reviewer" onSaved={async () => {}} onError={() => {}} onRun={async () => {}} onTab={() => {}} />);`,
  },
  bundle: true,
  platform: "node",
  format: "cjs",
  jsx: "automatic",
  external: ["react", "react/*", "react-dom", "react-dom/*"],
  define: { "window.__FOLIO_CONFIG__": "{}" },
  write: false,
});
const module = { exports: {} };
new Function("require", "module", "exports", compiled.outputFiles[0].text)(
  createRequire(import.meta.url),
  module,
  module.exports,
);
const render = module.exports.render;
const fixture = () => ({
  id: "fixture",
  topic: "Temporary review",
  status: "awaiting_step_confirmation",
  workflow_status: "awaiting_step_confirmation",
  workflow_protocol_fingerprint: "p",
  protocol: {
    fingerprint: "p",
    approval: { reviewer: "Test reviewer" },
    protocol: { exclusion_criteria: [] },
  },
  runtime_settings: { thinking: "off" },
  awaiting_confirmation: { stage: "save", title: "Screening", token: "test" },
  pending: { screening: 1, eligibility: 0, evidence: 0 },
  appraisals: [],
  decisions: [],
  step_confirmations: [],
  evidence: [],
  search_log: [],
  job: { status: "completed" },
  completed: ["retrieval", "screening", "save"],
  total_stages: 11,
  papers: [
    {
      id: "https://openalex.org/W1",
      paper_id: "W1",
      title: "Paper to assess",
      abstract: "A source abstract.",
      files: {},
    },
  ],
  queue: {
    items: [
      {
        item_id: "screening:W1",
        paper_id: "W1",
        stage: "screening",
        title: "Paper to assess",
        required: true,
        decision: null,
        fingerprint: "f",
        status: "pending",
      },
    ],
    unavailable_full_texts: [],
    full_text_not_sought: [],
    invalid_evidence: [],
    included_papers: [],
  },
});

test("guided screening displays one review task and blocks phase confirmation until decisions finish", () => {
  const html = render(fixture());
  assert.match(html, /Which papers should we keep/);
  assert.match(html, /Paper to assess/);
  const footer = html.match(
    /<footer class="validation-actions">[\s\S]*?<\/footer>/,
  )[0];
  assert.match(footer, /1 decisions remaining/);
  assert.match(footer, /disabled=""/);
  assert.match(footer, /Confirm &amp; continue/);
});

test("completed decisions unlock confirmation without starting the next phase automatically", () => {
  const detail = fixture();
  detail.pending.screening = 0;
  const html = render(detail);
  assert.match(html, /no pending decisions/);
  const footer = html.match(
    /<footer class="validation-actions">[\s\S]*?<\/footer>/,
  )[0];
  assert.doesNotMatch(footer, /disabled=""/);
  assert.match(footer, /Confirm &amp; continue/);
});

test("a revised protocol returns to search instead of presenting an old confirmation", () => {
  const detail = fixture();
  detail.protocol.fingerprint = "new-protocol";
  const html = render(detail);
  assert.match(html, /Check the papers I found/);
  const footer = html.match(
    /<footer class="validation-actions">[\s\S]*?<\/footer>/,
  )[0];
  assert.doesNotMatch(footer, /Confirm &amp; continue/);
});

test("a paused extraction stays on evidence instead of jumping to appraisal", () => {
  const detail = fixture();
  detail.awaiting_confirmation = null;
  detail.workflow_status = "paused";
  detail.pending.screening = 0;
  detail.appraisals = [{ assessment: null }];
  detail.progress = { stage: "extraction", completed: 0, total: 1 };
  const html = render(detail);
  assert.match(html, /Check the supporting evidence/);
  assert.match(html, /Processing is paused/);
});

test("working phases display the current operation, counts, and elapsed time", () => {
  const detail = fixture();
  detail.job = { status: "running", started_at: new Date().toISOString() };
  detail.progress = {
    stage: "screening",
    completed: 2,
    total: 4,
    message: "Screening paper three",
  };
  const html = render(detail);
  assert.match(html, /Screening paper three/);
  assert.match(html, /2 of 4 items completed/);
  assert.match(html, /elapsed/);
  assert.match(html, /Pause to review/);
});

test("the app starts as a new chat, with a real composer rather than dashboard navigation", () => {
  globalThis.location = { search: "", pathname: "/" };
  globalThis.localStorage = { getItem: () => "", setItem: () => {} };
  const html = module.exports.renderHome();
  assert.match(html, /What would you like/);
  assert.match(html, /New conversation/);
  assert.match(html, /Research question/);
  assert.doesNotMatch(html, /Review protocol<\/button>/);
});

test("a review conversation includes stored messages and a usable message composer", () => {
  const detail = fixture();
  detail.chat_messages = [
    { id: "test-user", role: "user", content: "Explain the criteria" },
    {
      id: "test-assistant",
      role: "assistant",
      content: "Use the criteria in the protocol.",
    },
  ];
  const html = render(detail);
  assert.match(html, /Explain the criteria/);
  assert.match(html, /Use the criteria in the protocol/);
  assert.match(html, /Message the review assistant/);
  assert.match(html, /Send message/);
  assert.match(html, /aria-expanded="false"/);
});

test("Thinking Off and On are visible, with Off selected by default", () => {
  const html = module.exports.renderThinking({
    available: true,
    options: [
      { value: "off", label: "Off" },
      { value: "on", label: "On" },
    ],
  });
  assert.match(html, /aria-label="Turn thinking off" aria-pressed="true"/);
  assert.match(html, /aria-label="Turn thinking on" aria-pressed="false"/);
  const unavailable = module.exports.renderThinking(null);
  assert.match(unavailable, /Turn thinking on/);
  assert.match(unavailable, /disabled=""/);
});

test("the PDF reader preserves access to original bytes and responsive page navigation", () => {
  const html = module.exports.renderPdf();
  assert.match(html, /Original PDF: Original paper/);
  assert.match(html, /Next PDF page/);
  assert.match(html, /download=true/);
  assert.match(html, /Open original/);
  assert.match(html, /Browser PDF view/);
});

test("run settings open from the prompt box while the initial page stays compact", () => {
  globalThis.location = { search: "", pathname: "/" };
  globalThis.localStorage = { getItem: () => "", setItem: () => {} };
  const html = module.exports.renderHome();
  assert.match(
    html,
    /aria-label="Open run settings" aria-haspopup="dialog" aria-expanded="false"/,
  );
  assert.match(html, /<dialog[^>]*id="run-settings-dialog"[^>]*>/);
  assert.doesNotMatch(html, /<dialog[^>]*\bopen(?:=|\s|>)/);
  assert.match(html, /Switch to dark mode/);
  const promptForm = html.match(
    /<form id="new-review-form"[\s\S]*?<\/form>/,
  )[0];
  assert.match(promptForm, /Research question/);
  assert.doesNotMatch(promptForm, /run-settings-dialog/);
  assert.match(html, /Choose a local model/);
  assert.match(html, /How should this review run/);
  assert.match(html, /Automated draft/);
  assert.match(html, /Records per query/);
  assert.match(html, /Response temperature/);
  assert.match(html, /Search sources/);
});

test("theme follows the system initially and remembers an explicit choice", (t) => {
  const previousWindow = globalThis.window;
  const previousStorage = globalThis.localStorage;
  const previousDocument = globalThis.document;
  t.after(() => {
    globalThis.window = previousWindow;
    globalThis.localStorage = previousStorage;
    globalThis.document = previousDocument;
  });
  let stored = null;
  globalThis.window = { matchMedia: () => ({ matches: true }) };
  globalThis.localStorage = {
    getItem: () => stored,
    setItem: (key, value) => {
      assert.equal(key, "folio-theme");
      stored = value;
    },
  };
  const root = { dataset: {}, style: {} };
  globalThis.document = { documentElement: root, querySelector: () => null };
  assert.equal(module.exports.preferredTheme(), "dark");
  module.exports.saveTheme("light");
  assert.equal(root.dataset.theme, "light");
  assert.equal(root.style.colorScheme, "light");
  assert.equal(module.exports.preferredTheme(), "light");
  globalThis.localStorage = {
    getItem: () => {
      throw new Error("Storage denied");
    },
    setItem: () => {
      throw new Error("Storage denied");
    },
  };
  assert.equal(module.exports.preferredTheme(), "dark");
  assert.doesNotThrow(() => module.exports.saveTheme("dark"));
  assert.equal(root.dataset.theme, "dark");
});

test("automated mode shows only final-result acceptance or rejection, without a protocol approval gate", () => {
  const detail = fixture();
  detail.runtime_settings = { ...detail.runtime_settings, mode: "automatic" };
  detail.protocol = null;
  detail.workflow_status = "awaiting_final_review";
  detail.automatic_result = {
    fingerprint: "final",
    current: true,
    decision: null,
  };
  detail.report = "# Automated preliminary draft";
  detail.report_current = true;
  detail.quality = null;
  detail.artifacts = [];
  const html = render(detail);
  assert.match(html, /Accept final result/);
  assert.match(html, /Reject final result/);
  assert.match(html, /not been individually human-validated/);
  assert.doesNotMatch(html, /Approve saved protocol/);
  assert.doesNotMatch(html, /Confirm &amp; continue/);
});


test("publication years are optional and default to an unrestricted date range", () => {
  const html = module.exports.renderSetup();
  assert.match(html, /Publication start year/);
  assert.match(html, /Publication end year/);
  assert.match(html, /leave both years blank/);
  assert.match(html, /No lower limit/);
  assert.match(html, /No upper limit/);
  assert.match(module.exports.renderSetup({year_from:2025,year_to:2020}), /start year must not be after/);
});

test("automatic reports expose PRISMA diagram and checklist navigation", () => {
  const detail = fixture();
  detail.runtime_settings = {...detail.runtime_settings,mode:"automatic"};
  detail.workflow_status = "awaiting_final_review";
  detail.automatic_result = {fingerprint:"test",current:true,decision:null};
  detail.report = "# Automated report";
  detail.report_current = true;
  detail.prisma = {source:"https://www.prisma-statement.org/prisma-2020-checklist",items:[]};
  detail.prisma_flow = {reports_sought:2};
  detail.quality = null;
  detail.artifacts = ["prisma_flow.svg","prisma_checklist.json"];
  assert.match(render(detail), /Review PRISMA checklist/);
  assert.match(module.exports.renderReport(detail), /PRISMA-oriented selection diagram/);
});

test("an incomplete extraction exposes retry and prevents final acceptance", () => {
  const detail = fixture();
  detail.runtime_settings = {...detail.runtime_settings,mode:"automatic"};
  detail.workflow_status = "awaiting_final_review";
  detail.automatic_result = {fingerprint:"test",current:true,ready:false,failed_paper_ids:["W1"],decision:null};
  detail.report = "# Incomplete draft";
  detail.report_current = false;
  detail.quality = null;
  detail.artifacts = [];
  const html = render(detail);
  assert.match(html, /Retry failed extractions/);
  assert.match(html, /scientific draft needs attention/);
  assert.match(html, /disabled=""[^>]*>.*?Accept final result/s);
  assert.doesNotMatch(html, /Your automated draft is ready to review/);
});

test("selection results show readable counts, tables and separate pending decisions", () => {
  const detail = fixture();
  detail.runtime_settings = {...detail.runtime_settings, mode:"automatic"};
  detail.prisma_flow = {records_identified:3,reports_retrieved:2,reports_included:0,eligibility_uncertain:2};
  detail.report = "## Selection results\n\n| Stage | Count |\n| --- | --- |\n| Pending | 2 |";
  detail.artifacts = ["automatic_review.docx", "prisma_flow.svg", "prisma_flow.json"];
  const html = module.exports.renderReport(detail);
  assert.match(html, /Records found<\/span><strong>3/);
  assert.match(html, /Include recommendations<\/span><strong>0/);
  assert.match(html, /2 eligibility decisions pending/);
  assert.match(html, /<table>/);
  assert.match(html, /Scientific manuscript/);
  assert.match(html, /<details class="technical-artifacts">/);
  assert.doesNotMatch(html, /records_identified/);
});


test("incomplete scientific writing shows section progress and resume without blaming extraction", () => {
  const detail = fixture();
  detail.runtime_settings = {...detail.runtime_settings, mode:"automatic"};
  detail.workflow_status = "awaiting_final_review";
  detail.automatic_result = {fingerprint:"test", current:true, ready:false, failed_paper_ids:[], decision:null, writing:{ready:false,status:"needs_revision",completed_sections:3,total_sections:5,issues:["Unsupported comparison"],sections:[{name:"introduction",verified:true}]}};
  detail.quality = null;
  detail.artifacts = [];
  const html = render(detail);
  assert.match(html, /Resume scientific writing/);
  assert.match(html, /3 of 5 scientific sections/);
  assert.doesNotMatch(html, /Retry failed extractions/);
  assert.match(html, /disabled=""[^>]*>.*?Accept final result/s);
});

test("missing eligible evidence explains the next action instead of offering a useless writing retry", () => {
  const detail = fixture();
  detail.runtime_settings = {...detail.runtime_settings, mode:"automatic"};
  detail.workflow_status = "awaiting_final_review";
  detail.automatic_result = {fingerprint:"test",current:true,ready:false,failed_paper_ids:[],decision:null,writing:{ready:false,status:"insufficient_eligible_evidence",completed_sections:0,total_sections:5,issues:[]}};
  detail.quality = null;
  detail.artifacts = [];
  const html = render(detail);
  assert.match(html, /Inspect source papers/);
  assert.match(html, /guided review to adjudicate uncertain selections/);
  assert.doesNotMatch(html, /Resume scientific writing/);
});

test("guided report with unfinished writing offers resume instead of final validation", () => {
  const detail = fixture();
  detail.pending = {screening:0, eligibility:0, evidence:0};
  detail.appraisals = [];
  detail.report_current = true;
  detail.workflow_status = "awaiting_step_confirmation";
  detail.awaiting_confirmation = {stage:"quality",token:"quality-token",title:"Report"};
  detail.writing = {ready:false,status:"needs_revision",completed_sections:4,total_sections:5,issues:[]};
  detail.artifacts = [];
  detail.quality = null;
  const html = render(detail);
  assert.match(html, /Scientific writing needs attention/);
  assert.match(html, /Resume scientific writing/);
  assert.doesNotMatch(html, /Validate &amp; finish/);
});

test("scientific manuscript renders its figure inline and offers a separate technical report", () => {
  const detail = fixture();
  detail.runtime_settings = {...detail.runtime_settings, mode:"automatic"};
  detail.report = "![Study selection](prisma_flow.png)\n\n*Figure 1. Selection flow.*";
  detail.artifacts = ["automatic_review.docx", "technical_report.docx", "technical_report.md", "prisma_flow.png"];
  const html = module.exports.renderReport(detail);
  assert.match(html, /Scientific manuscript/);
  assert.match(html, /Technical report/);
  assert.match(html, /<img[^>]+prisma_flow\.png\?download=false/);
  assert.match(html, /Figure 1. Selection flow/);
});
