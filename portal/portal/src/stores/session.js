import { defineStore } from "pinia";
import { computed, ref } from "vue";
import { api, saveCsrf } from "@/api/client";

export const useSessionStore = defineStore("session", () => {
  const username = ref("");
  const csrf = ref("");
  const initialized = ref(false);
  const authenticated = computed(() => Boolean(username.value && csrf.value));

  function applySession(payload) {
    username.value = payload.username || "";
    csrf.value = payload.csrf || "";
    saveCsrf(csrf.value);
  }

  async function login(account, password) {
    const { data } = await api.post("/api/login", { username: account, password });
    applySession(data);
    initialized.value = true;
  }

  async function restore() {
    try {
      const { data } = await api.get("/api/session");
      applySession(data);
    } catch {
      applySession({});
    } finally {
      initialized.value = true;
    }
  }

  function initializeAnonymous() {
    applySession({});
    initialized.value = true;
  }

  async function logout() {
    try {
      await api.post("/api/logout");
    } finally {
      applySession({});
      initialized.value = true;
    }
  }

  return {
    username,
    csrf,
    initialized,
    authenticated,
    login,
    restore,
    initializeAnonymous,
    logout
  };
});
