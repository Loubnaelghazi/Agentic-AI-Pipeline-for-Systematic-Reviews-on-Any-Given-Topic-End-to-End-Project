export type Stage = "screening" | "eligibility" | "evidence";
export type Kind =
  | "research_objective"
  | "methodology"
  | "main_findings"
  | "limitations";
export type Decision = {
  item_id: string;
  decision: "include" | "exclude" | "approve" | "reject";
  reviewer: string;
  reason: string;
  timestamp: string;
  kind: Kind | null;
  fingerprint: string;
  stage: Stage;
};
export type Passage = {
  passage_id: string;
  source: string;
  text: string;
  page_start: number | null;
  page_end: number | null;
};
export type Item = {
  item_id: string;
  stage: Stage;
  paper_id: string;
  title?: string;
  abstract?: string | null;
  required: boolean;
  status: string;
  decision: Decision | null;
  fingerprint: string;
  automated_decision?: string;
  proposal?: { recommendation: string; reason: string; coverage?: string };
  quote?: string;
  proposed_kind?: Kind;
  passage?: Passage;
  empty_evidence?: boolean;
};
export type Paper = {
  id: string;
  landing_url?: string;
  paper_id: string;
  title: string;
  abstract?: string | null;
  year?: number;
  authors?: string[];
  doi?: string | null;
  screening?: {
    decision: string;
    reason?: string;
    disagreement?: boolean;
    reviews?: {
      role: string;
      decision: string;
      reason: string;
      criteria: string[];
    }[];
  };
  full_text_status: string;
  files: { pdf?: string; txt?: string };
};
export type Evidence = {
  paper_id: string;
  characteristic_proposals?: {
    field: string;
    quote: string;
    passage_id: string;
  }[];
  claims?: { quote: string; kind: Kind }[];
  error?: string;
};
export type Job = {
  pause_requested?: boolean;
  id?: string;
  status?: string;
  started_at?: string;
  finished_at?: string;
  log?: string;
  error?: string;
  workflow_status?: string;
};
export type Review = {
  id: string;
  topic: string;
  status: string;
  paper_count: number;
  report_current: boolean;
};
export type Protocol = {
  research_question: string;
  rationale: string;
  inclusion_criteria: string[];
  exclusion_criteria: string[];
  concepts: string[][];
  mesh_terms: string[];
  sources: string[];
  max_records_per_query: number;
  date_from: string | null;
  date_to: string | null;
  extraction_fields: string[];
  appraisal_name: string;
  appraisal_domains: { id: string; question: string }[];
  synthesis_plan: string;
  meta_analysis: boolean;
  registration: string;
  funding: string;
  conflicts: string;
};
export type ProtocolDocument = {
  revision: number;
  protocol: Protocol;
  fingerprint: string;
  adopt_existing: boolean;
  approval: { reviewer: string; reason: string; timestamp: string } | null;
};
export type StudyAssessment = {
  timestamp: string;
  overall: string;
  rationale: string;
  study_id: string;
  domains: {
    domain_id: string;
    judgement: string;
    rationale: string;
    quote: string;
  }[];
  characteristics: Record<string, { value: string; quote: string }>;
};
export type PrismaItem = {
  id: string;
  topic: string;
  status: string;
  location: string;
  reason: string;
  reviewer: string;
  suggested_location?: string;
};
export type WritingStatus = {
  ready: boolean;
  status: string;
  completed_sections: number;
  total_sections: number;
  issues: string[];
  sections?: { name: string; verified: boolean }[];
};
export type Detail = Review & {
  writing?: WritingStatus;
  automatic_result?: {
    writing?: WritingStatus;
    ready?: boolean;
    failed_paper_ids?: string[];
    fingerprint: string;
    current: boolean;
    scope: string;
    decision: {
      decision: "accept" | "reject";
      reviewer: string;
      note: string;
    } | null;
  } | null;
  chat_messages?: {
    id: string;
    role: "user" | "assistant";
    content: string;
    timestamp: string;
  }[];
  workflow_status?: string;
  workflow_protocol_fingerprint?: string;
  runtime_settings: {
    thinking: string;
    model?: string;
    mode?: "guided" | "automatic";
    temperature?: number;
    max_records?: number;
    year_from?: number | null;
    year_to?: number | null;
    sources?: string[];
  };
  awaiting_confirmation: {
    stage: string;
    title: string;
    token: string;
    protocol_fingerprint?: string;
  } | null;
  step_confirmations: {
    stage: string;
    title: string;
    token: string;
    reviewer: string;
    timestamp: string;
  }[];
  progress?: {
    stage: string;
    completed: number;
    total: number | null;
    message: string;
    updated_at: string;
  } | null;
  protocol: ProtocolDocument | null;
  appraisals: {
    paper_id: string;
    fingerprint: string;
    domains: { id: string; question: string }[];
    tool: string;
    assessment: StudyAssessment | null;
  }[];
  appraisal_proposals: Record<string, { proposal: { notes: string[] } }>;
  prisma: {
    source: string;
    report_fingerprint: string;
    items: PrismaItem[];
  } | null;
  prisma_flow: Record<string, unknown> | null;
  search_log: {
    source: string;
    query: string;
    timestamp: string;
    records: number;
    error: string | null;
  }[];
  papers: Paper[];
  queue: {
    items: Item[];
    included_papers: string[];
    unavailable_full_texts: string[];
    full_text_not_sought: string[];
    invalid_evidence: string[];
  };
  pending: Record<Stage, number>;
  evidence: Evidence[];
  completed: string[];
  total_stages: number;
  job: Job;
  report: string | null;
  quality: {
    passed: boolean;
    issues: string[];
    recommendations: string[];
  } | null;
  statistics: Record<string, number | null> | null;
  decisions: Decision[];
  artifacts: string[];
  errors: { stage: string; error: string; time: string }[];
};
declare global {
  interface Window {
    __FOLIO_CONFIG__?: { apiBaseUrl?: string };
  }
}

const apiBase = (
  window.__FOLIO_CONFIG__?.apiBaseUrl ?? "http://localhost:8000"
).replace(/\/+$/, "");
export const apiUrl = (path: string) => `${apiBase}${path}`;

export async function request<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  const headers = new Headers(options?.headers);
  if (options?.body && !headers.has("Content-Type"))
    headers.set("Content-Type", "application/json");
  const response = await fetch(apiUrl(`/api${path}`), { ...options, headers });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = body.detail;
    throw new Error(
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail.map((v: { msg: string }) => v.msg).join("; ")
          : `Request failed (${response.status})`,
    );
  }
  return response.json();
}
export const artifactUrl = (id: string, name: string) =>
  apiUrl(
    `/api/reviews/${encodeURIComponent(id)}/artifacts/${encodeURIComponent(name)}?download=true`,
  );
export const readable = (value: string) =>
  value.replaceAll("_", " ").replace(/^\w/, (c) => c.toUpperCase());
