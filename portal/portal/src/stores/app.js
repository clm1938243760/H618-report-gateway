import { defineStore } from "pinia";
import { Storage } from "@/utils/storage";
import { getLanguage } from "@/locales/i18n";

export const useAppStore = defineStore({
  id: "app",
  state: () => ({
    layoutPlan: "default",
    language: getLanguage() || "zh"
  }),

  actions: {
    SET_LAYOUTPLAN(plan) {
      this.layoutPlan = plan;
      Storage.set("layoutPlan", plan);
    },
    SET_LANGUAGE(language) {
      this.language = language;
      Storage.set("language", language);
      // 刷新页面更新视图
      window.location.reload();
    }
  }
});
