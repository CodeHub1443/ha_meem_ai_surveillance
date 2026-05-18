import { useEffect } from "react";
import { createPortal } from "react-dom";
import { Button } from "@/components/ui/button";
import { Download, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { snapshotUrl } from "@/api/events";

export function SnapshotModal({
  open,
  onOpenChange,
  src,
  title,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  src: string | null;
  title?: string;
}) {
  const { t } = useTranslation();
  const resolvedSrc = snapshotUrl(src);

  // Close on Escape
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onOpenChange(false);
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [open, onOpenChange]);

  if (!open) return null;

  return createPortal(
    // Backdrop — click anywhere outside the card closes the modal.
    // No body scroll lock so the rest of the UI stays interactive.
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      onClick={() => onOpenChange(false)}
    >
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" />

      {/* Card — stop propagation so clicks inside don't dismiss */}
      <div
        className="relative z-10 bg-background rounded-xl shadow-2xl w-full max-w-3xl overflow-hidden flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b shrink-0">
          <span className="text-sm font-semibold">{title ?? t("events.snapshot")}</span>
          <button
            onClick={() => onOpenChange(false)}
            className="rounded-md p-1 text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Image */}
        <div className="bg-muted flex items-center justify-center min-h-[280px] max-h-[70vh] overflow-hidden">
          {resolvedSrc ? (
            <img
              src={resolvedSrc}
              alt={title ?? "snapshot"}
              className="max-h-[70vh] max-w-full object-contain"
            />
          ) : (
            <span className="text-muted-foreground text-sm">{t("common.noData")}</span>
          )}
        </div>

        {/* Footer */}
        {resolvedSrc && (
          <div className="flex justify-end px-4 py-3 border-t shrink-0">
            <a href={resolvedSrc} download target="_blank" rel="noopener noreferrer">
              <Button variant="outline" size="sm">
                <Download className="h-4 w-4 mr-2" />
                {t("common.download")}
              </Button>
            </a>
          </div>
        )}
      </div>
    </div>,
    document.body,
  );
}
