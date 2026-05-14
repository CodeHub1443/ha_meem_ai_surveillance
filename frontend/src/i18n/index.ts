import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import en from "./locales/en.json";
import bn from "./locales/bn.json";

const STORAGE_KEY = "tdi_lang";

const stored = typeof window !== "undefined" ? window.localStorage.getItem(STORAGE_KEY) : null;

void i18n.use(initReactI18next).init({
  resources: {
    en: { translation: en },
    bn: { translation: bn },
  },
  lng: stored || "en",
  fallbackLng: "en",
  interpolation: { escapeValue: false },
});

export function setLanguage(lang: "en" | "bn") {
  void i18n.changeLanguage(lang);
  if (typeof window !== "undefined") window.localStorage.setItem(STORAGE_KEY, lang);
}

export default i18n;
