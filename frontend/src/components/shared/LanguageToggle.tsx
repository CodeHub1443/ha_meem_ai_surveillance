import { useTranslation } from "react-i18next";
import { setLanguage } from "@/i18n";

export function LanguageToggle() {
  const { i18n } = useTranslation();
  const lang = i18n.language?.startsWith("bn") ? "bn" : "en";
  return (
    <div className="inline-flex items-center rounded-md border bg-card text-xs overflow-hidden">
      <button
        type="button"
        onClick={() => setLanguage("en")}
        className={`px-3 py-1.5 transition-colors ${lang === "en" ? "bg-primary text-primary-foreground" : "hover:bg-muted"}`}
      >
        EN
      </button>
      <button
        type="button"
        onClick={() => setLanguage("bn")}
        className={`px-3 py-1.5 transition-colors ${lang === "bn" ? "bg-primary text-primary-foreground" : "hover:bg-muted"}`}
      >
        বাংলা
      </button>
    </div>
  );
}
