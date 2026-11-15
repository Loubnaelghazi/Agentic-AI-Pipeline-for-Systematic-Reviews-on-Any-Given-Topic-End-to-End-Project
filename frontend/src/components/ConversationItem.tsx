import { MessageSquare, Trash2 } from "lucide-react";
import type { Review } from "../api";

export function ConversationItem({ review, selected, disabled, onChoose, onDelete }: {
  review: Review;
  selected: boolean;
  disabled: boolean;
  onChoose: () => void;
  onDelete: () => void;
}) {
  return <div className={`conversation-item ${selected ? "selected" : ""}`}>
    <button className="conversation-open" onClick={onChoose} aria-current={selected ? "page" : undefined}>
      <MessageSquare size={15} /><span>{review.topic}</span>
    </button>
    <button className="conversation-delete" onClick={onDelete} disabled={disabled}
      aria-label={`Delete conversation: ${review.topic}`} title="Delete conversation">
      <Trash2 size={15} />
    </button>
  </div>;
}
