import { useEffect, useRef, useState } from "react";
import {
  ChevronLeft,
  ChevronRight,
  Download,
  ExternalLink,
  FileText,
  LoaderCircle,
  X,
} from "lucide-react";
import { apiUrl, request } from "../api";

type Props = {
  fileUrl: string;
  title: string;
  initialPage?: number;
  onClose: () => void;
};
export function PdfViewer({ fileUrl, title, initialPage = 1, onClose }: Props) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [info, setInfo] = useState<{ pages: number; filename: string } | null>(
    null,
  );
  const [page, setPage] = useState(initialPage);
  const [native, setNative] = useState(false);
  const [zoom, setZoom] = useState(100);
  const [error, setError] = useState("");
  const [imageReady, setImageReady] = useState(false);
  const base = fileUrl.split("?")[0].replace(/\/file$/, "");
  useEffect(() => {
    dialog.current?.showModal();
    let valid = true;
    request<{ pages: number; filename: string }>(
      `${base.replace(/^\/api/, "")}/pdf-info`,
    )
      .then((value) => {
        if (valid) {
          setInfo(value);
          setPage(Math.max(1, Math.min(initialPage, value.pages || 1)));
        }
      })
      .catch((e) => {
        if (valid) setError(e.message);
      });
    return () => {
      valid = false;
    };
  }, [base, initialPage]);
  useEffect(() => {
    setImageReady(false);
  }, [page, zoom > 125]);
  return (
    <dialog
      ref={dialog}
      className="pdf-dialog"
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
      aria-label={`Original PDF: ${title}`}
    >
      <header>
        <div>
          <FileText size={19} />
          <div>
            <strong>{title}</strong>
            <small>
              Original paper · figures, tables and page layout preserved
            </small>
          </div>
        </div>
        <button
          type="button"
          className="icon-button"
          autoFocus
          onClick={onClose}
          aria-label="Close PDF viewer"
        >
          <X size={21} />
        </button>
      </header>
      <div className="pdf-tools">
        <div className="pdf-pagination">
          <button
            type="button"
            className="icon-button"
            aria-label="Previous PDF page"
            disabled={!info || page <= 1}
            onClick={() => setPage(page - 1)}
          >
            <ChevronLeft size={19} />
          </button>
          <label>
            Page{" "}
            <select
              aria-label="PDF page"
              value={page}
              disabled={!info}
              onChange={(e) => setPage(Number(e.target.value))}
            >
              {Array.from({ length: info?.pages || 1 }, (_, i) => (
                <option key={i} value={i + 1}>
                  {i + 1}
                </option>
              ))}
            </select>{" "}
            of {info?.pages || "…"}
          </label>
          <button
            type="button"
            className="icon-button"
            aria-label="Next PDF page"
            disabled={!info || page >= info.pages}
            onClick={() => setPage(page + 1)}
          >
            <ChevronRight size={19} />
          </button>
        </div>
        <div className="pdf-zoom">
          <button
            type="button"
            className="icon-button"
            aria-label="Zoom PDF out"
            disabled={native || zoom <= 50}
            onClick={() => setZoom(zoom - 25)}
          >
            −
          </button>
          <span>{zoom}%</span>
          <button
            type="button"
            className="icon-button"
            aria-label="Zoom PDF in"
            disabled={native || zoom >= 200}
            onClick={() => setZoom(zoom + 25)}
          >
            +
          </button>
        </div>
        <div>
          <button
            type="button"
            className="secondary-button"
            onClick={() => setNative(!native)}
          >
            {native ? "Responsive page view" : "Browser PDF view"}
          </button>
          <a
            className="secondary-button"
            href={`${apiUrl(fileUrl)}#page=${page}`}
            target="_blank"
            rel="noreferrer"
          >
            <ExternalLink size={14} /> Open original
          </a>
          <a
            className="secondary-button"
            href={`${apiUrl(fileUrl)}${fileUrl.includes("?") ? "&" : "?"}download=true`}
          >
            <Download size={14} /> Download PDF
          </a>
        </div>
      </div>
      <div className="pdf-document">
        {error ? (
          <p role="alert">
            {error} Use “Open original” to read the PDF directly.
          </p>
        ) : native ? (
          <iframe
            title={`Original PDF document: ${title}`}
            src={`${apiUrl(fileUrl)}#page=${page}`}
          />
        ) : info ? (
          <>
            <div className="pdf-image-status" role="status">
              {!imageReady && (
                <>
                  <LoaderCircle className="spin" size={21} /> Loading page{" "}
                  {page}…
                </>
              )}
            </div>
            <img
              key={page}
              src={apiUrl(`${base}/page/${page}?scale=${zoom > 125 ? 2 : 1.5}`)}
              style={{ width: `${zoom}%`, maxWidth: "none" }}
              alt={`Original page ${page} of ${info.pages}: ${title}`}
              onLoad={() => setImageReady(true)}
              onError={() => setError("This page could not be displayed.")}
            />
          </>
        ) : (
          <p role="status">
            <LoaderCircle className="spin" size={22} /> Opening original PDF…
          </p>
        )}
      </div>
    </dialog>
  );
}
export function PdfButton({
  fileUrl,
  title,
  initialPage,
}: Omit<Props, "onClose">) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        className="secondary-button"
        onClick={() => setOpen(true)}
      >
        <FileText size={14} /> Read original PDF
      </button>
      {open && (
        <PdfViewer
          {...{ fileUrl, title, initialPage }}
          onClose={() => setOpen(false)}
        />
      )}
    </>
  );
}
