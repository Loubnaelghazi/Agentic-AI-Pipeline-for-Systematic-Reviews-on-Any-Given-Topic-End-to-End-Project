import { useState } from "react";
import { ExternalLink, FileText, Search } from "lucide-react";
import { type Detail } from "../api";
import { safeUrl } from "../lib/review";
import { PdfButton } from "./PdfViewer";
export function PaperLibrary({ detail }: { detail: Detail }) {
  const [filter, setFilter] = useState("");
  const papers = detail.papers.filter((p) =>
    `${p.title} ${p.year || ""}`.toLowerCase().includes(filter.toLowerCase()),
  );
  const available = detail.papers.filter((p) => p.files.pdf).length;
  return (
    <section className="paper-library">
      <h2>Papers & original PDFs</h2>
      <p>
        {available} of {detail.papers.length} papers have a saved original PDF.
        Downloads happen during the full-text phase after screening validation.
        Some sources do not provide an accessible PDF.
      </p>
      <label className="conversation-search">
        <Search size={17} />
        <input
          aria-label="Find a research paper"
          value={filter}
          placeholder="Find a paper by title or year…"
          onChange={(e) => setFilter(e.target.value)}
        />
      </label>
      {papers.map((p) => (
        <article key={p.paper_id}>
          <span className="paper-library-icon">
            <FileText size={20} />
          </span>
          <div>
            <h3>{p.title}</h3>
            <p>
              {p.year || "Year unknown"}
              {p.authors?.length
                ? ` · ${p.authors.slice(0, 3).join(", ")}`
                : ""}
            </p>
            <div>
              {p.files.pdf ? (
                <PdfButton fileUrl={p.files.pdf} title={p.title} />
              ) : (
                <span className="paper-unavailable">
                  {p.full_text_status === "unavailable"
                    ? "Original PDF unavailable"
                    : "PDF not downloaded yet"}
                </span>
              )}
              {safeUrl(p.landing_url || p.id) && (
                <a
                  href={safeUrl(p.landing_url || p.id)}
                  target="_blank"
                  rel="noreferrer"
                  className="text-button"
                >
                  Paper record <ExternalLink size={13} />
                </a>
              )}
            </div>
          </div>
        </article>
      ))}
      {!papers.length && <p>No matching papers.</p>}
    </section>
  );
}
