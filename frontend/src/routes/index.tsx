import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Shield } from "lucide-react";
import { Button } from "@/components/ui/button";
import { LanguageToggle } from "@/components/shared/LanguageToggle";

export const Route = createFileRoute("/")({
  component: LockScreen,
});

// TODO: Replace this client-side PIN check with a proper auth endpoint.
// PIN is sourced from VITE_UNLOCK_PIN env var (default "1234").
const EXPECTED_PIN = (import.meta.env.VITE_UNLOCK_PIN as string | undefined) || "1234";

function LockScreen() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [digits, setDigits] = useState(["", "", "", ""]);
  const [error, setError] = useState(false);
  const [shake, setShake] = useState(false);
  const refs = [useRef<HTMLInputElement>(null), useRef<HTMLInputElement>(null), useRef<HTMLInputElement>(null), useRef<HTMLInputElement>(null)];

  useEffect(() => {
    if (typeof window !== "undefined" && window.sessionStorage.getItem("tdi_auth") === "true") {
      void navigate({ to: "/dashboard" });
    } else {
      refs[0].current?.focus();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleChange = (i: number, v: string) => {
    const c = v.replace(/\D/g, "").slice(-1);
    const next = [...digits];
    next[i] = c;
    setDigits(next);
    setError(false);
    if (c && i < 3) refs[i + 1].current?.focus();
  };

  const handleKey = (i: number, e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Backspace" && !digits[i] && i > 0) refs[i - 1].current?.focus();
    if (e.key === "Enter") attempt();
  };

  const attempt = () => {
    const pin = digits.join("");
    if (pin.length < 4) return;
    if (pin === EXPECTED_PIN) {
      window.sessionStorage.setItem("tdi_auth", "true");
      void navigate({ to: "/dashboard" });
    } else {
      setError(true);
      setShake(true);
      setTimeout(() => setShake(false), 500);
      setDigits(["", "", "", ""]);
      refs[0].current?.focus();
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-background px-4">
      <div className="absolute top-4 right-4">
        <LanguageToggle />
      </div>
      <div className={`bg-card border rounded-xl shadow-sm p-8 w-full max-w-md ${shake ? "animate-shake" : ""}`}>
        <div className="flex flex-col items-center text-center mb-6">
          <div className="h-14 w-14 rounded-xl bg-primary/10 flex items-center justify-center mb-3">
            <Shield className="h-8 w-8 text-primary" />
          </div>
          <h1 className="text-xl font-bold text-foreground">{t("app.name")}</h1>
          <p className="text-xs text-muted-foreground mt-1">{t("app.tagline")}</p>
        </div>

        <p className="text-sm text-center text-muted-foreground mb-4">{t("lock.subtitle")}</p>

        <div className="flex justify-center gap-3 mb-4">
          {digits.map((d, i) => (
            <input
              key={i}
              ref={refs[i]}
              type="password"
              inputMode="numeric"
              maxLength={1}
              value={d}
              onChange={(e) => handleChange(i, e.target.value)}
              onKeyDown={(e) => handleKey(i, e)}
              className={`h-14 w-12 text-center text-2xl font-bold rounded-md border-2 bg-background focus:outline-none focus:border-primary ${
                error ? "border-danger" : "border-border"
              }`}
            />
          ))}
        </div>

        {error && (
          <p className="text-sm text-danger text-center mb-3">{t("lock.wrong")}</p>
        )}

        <Button onClick={attempt} className="w-full" disabled={digits.join("").length < 4}>
          {t("lock.unlock")}
        </Button>
      </div>
    </div>
  );
}
