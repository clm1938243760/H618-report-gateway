import { createI18n } from "vue-i18n";
import setting from "@/setting.js";
import en from "./en.js";
import zh from "./zh.js";

const messages = {
  en,
  zh
};

// 从本地存储获取语言设置，默认为浏览器语言

const getLanguage = () => {
  const savedLang = localStorage.getItem(setting.appNameSpace + ".appLang");
  const browserLang = navigator.language.split("-")[0];
  const defaultLang = savedLang || (["zh", "en"].includes(browserLang) ? browserLang : "en");
  return defaultLang;
};

const i18n = createI18n({
  legacy: false,
  locale: getLanguage(),
  fallbackLocale: "en",
  messages
});

// 切换语言
export function setLocale(lang) {
  if (Object.keys(messages).includes(lang)) {
    i18n.global.locale.value = lang;
    localStorage.setItem(setting.appNameSpace + ".appLang", lang);
    document.documentElement.lang = lang;
  }
}

export { getLanguage };

export default i18n;
