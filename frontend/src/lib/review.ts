import {
  Activity,
  BookOpen,
  FileCheck2,
  FileText,
  Layers3,
  LayoutDashboard,
  Quote,
} from "lucide-react";
import { type Detail, type Kind, type Stage } from "../api";
export type Tab =
  | "papers"
  | "conversation"
  | "overview"
  | Stage
  | "report"
  | "activity"
  | "protocol"
  | "appraisal"
  | "prisma";
export const tabs: { id: Tab; title: string; icon: typeof BookOpen }[] = [
  { id: "conversation", title: "Review assistant", icon: BookOpen },
  { id: "papers", title: "Papers & PDFs", icon: BookOpen },
  { id: "overview", title: "Overview", icon: LayoutDashboard },
  { id: "protocol", title: "Review protocol", icon: BookOpen },
  { id: "screening", title: "Screening", icon: Layers3 },
  { id: "eligibility", title: "Full-text eligibility", icon: FileCheck2 },
  { id: "evidence", title: "Evidence review", icon: Quote },
  { id: "appraisal", title: "Study appraisal", icon: FileCheck2 },
  { id: "report", title: "Report & quality", icon: FileText },
  { id: "prisma", title: "PRISMA checklist", icon: Layers3 },
  { id: "activity", title: "Activity", icon: Activity },
];
export const kinds: { value: Kind; label: string }[] = [
  { value: "research_objective", label: "Research objective" },
  { value: "methodology", label: "Methodology" },
  { value: "main_findings", label: "Main findings" },
  { value: "limitations", label: "Author-reported limitations" },
];
export const isBusy = (d: Detail | null) =>
  ["queued", "running"].includes(d?.job.status || "");
export function progressMessage(d: Detail): string {
  const message = d.progress?.message || "";
  const match = message.match(/^([^:]+): (.+)$/);
  if (!match) return message;
  const paper = d.papers.find(
    (p) => p.paper_id === match[1] || p.id.split("/").pop() === match[1],
  );
  if (!paper && !/^W\d+$/.test(match[1])) return message;
  const action = match[2]
    .replace(/^finding source passages/i, "Finding relevant passages")
    .replace(/^selecting source sentences/i, "Extracting evidence from the article")
    .replace(/^assessing text window (\d+)\/(\d+)/i, "Checking article eligibility (section $1 of $2)");
  return `${action} — ${paper?.title?.trim() || "Current article"}`;
}
export const safeUrl = (url?: string | null) =>
  url && /^https?:\/\//i.test(url) ? url : undefined;
export const time = (value: string) =>
  new Date(value).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
