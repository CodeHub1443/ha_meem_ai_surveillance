import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/badge";
import type { EventType } from "@/types/surveillance";

export function EventBadge({ type }: { type: EventType }) {
  const { t } = useTranslation();
  if (type === "AUTHORIZED") {
    return (
      <Badge className="bg-success text-success-foreground hover:bg-success/90 font-medium uppercase tracking-wide text-[10px]">
        {t("events.authorized")}
      </Badge>
    );
  }
  return (
    <Badge className="bg-danger text-danger-foreground hover:bg-danger/90 font-medium uppercase tracking-wide text-[10px]">
      {t("events.unknown")}
    </Badge>
  );
}
