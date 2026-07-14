import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import {
  applyDocumentLocale,
  defaultLocale,
  fallbackLocale,
  LOCALE_STORAGE_KEY,
  normalizeLocale,
  persistLocale,
  resolveInitialLocale,
  type SupportedLocale,
} from "./config";

import enCommon from "./locales/en/common.json";
import zhCNCommon from "./locales/zh-CN/common.json";
import zhTWCommon from "./locales/zh-TW/common.json";
import frCommon from "./locales/fr/common.json";
import jaCommon from "./locales/ja/common.json";
import koCommon from "./locales/ko/common.json";
import esCommon from "./locales/es/common.json";
import viCommon from "./locales/vi/common.json";
import idCommon from "./locales/id/common.json";

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function mergeLocale<T extends Record<string, unknown>>(
  base: T,
  translation: Record<string, unknown>,
): T {
  const merged: Record<string, unknown> = { ...base };
  for (const [key, value] of Object.entries(translation)) {
    const baseValue = base[key];
    merged[key] = isRecord(baseValue) && isRecord(value)
      ? mergeLocale(baseValue, value)
      : value;
  }
  return merged as T;
}

export const resources = {
  en: { common: enCommon },
  "zh-CN": { common: mergeLocale(enCommon, zhCNCommon) },
  "zh-TW": { common: mergeLocale(enCommon, zhTWCommon) },
  fr: { common: mergeLocale(enCommon, frCommon) },
  ja: { common: mergeLocale(enCommon, jaCommon) },
  ko: { common: mergeLocale(enCommon, koCommon) },
  es: { common: mergeLocale(enCommon, esCommon) },
  vi: { common: mergeLocale(enCommon, viCommon) },
  id: { common: mergeLocale(enCommon, idCommon) },
} as const;

export function currentLocale(): SupportedLocale {
  return normalizeLocale(i18n.resolvedLanguage ?? i18n.language ?? defaultLocale);
}

export async function setAppLanguage(locale: SupportedLocale): Promise<void> {
  await i18n.changeLanguage(locale);
}

if (!i18n.isInitialized) {
  void i18n
    .use(initReactI18next)
    .init({
      resources,
      lng: resolveInitialLocale(),
      fallbackLng: fallbackLocale,
      defaultNS: "common",
      ns: ["common"],
      interpolation: {
        escapeValue: false,
      },
      returnNull: false,
      supportedLngs: Object.keys(resources),
    });
}

const syncLocaleSideEffects = (language: string) => {
  const locale = normalizeLocale(language);
  applyDocumentLocale(locale);
  persistLocale(locale);
};

syncLocaleSideEffects(currentLocale());
i18n.on("languageChanged", syncLocaleSideEffects);

export { LOCALE_STORAGE_KEY };
export default i18n;
