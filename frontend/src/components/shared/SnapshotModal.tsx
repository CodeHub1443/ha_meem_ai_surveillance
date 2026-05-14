import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Download } from "lucide-react";
import { useTranslation } from "react-i18next";

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
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>{title || t("events.snapshot")}</DialogTitle>
        </DialogHeader>
        <div className="bg-muted rounded-md overflow-hidden flex items-center justify-center min-h-[300px]">
          {src ? (
            <img src={src} alt="snapshot" className="max-h-[70vh] w-auto" />
          ) : (
            <span className="text-muted-foreground text-sm">{t("common.noData")}</span>
          )}
        </div>
        {src && (
          <div className="flex justify-end">
            <a href={src} download>
              <Button variant="outline" size="sm">
                <Download className="h-4 w-4 mr-2" /> {t("common.download")}
              </Button>
            </a>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
