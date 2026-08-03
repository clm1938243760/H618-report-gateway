import axios from "axios";

const CSRF_KEY = "gmp.csrf";

export const api = axios.create({
  baseURL: "",
  withCredentials: true,
  timeout: 65000,
  headers: {
    Accept: "application/json"
  }
});

api.interceptors.request.use((config) => {
  const method = String(config.method || "get").toLowerCase();
  if (["post", "put", "patch", "delete"].includes(method)) {
    const csrf = sessionStorage.getItem(CSRF_KEY);
    if (csrf) {
      config.headers["X-CSRF-Token"] = csrf;
    }
  }
  return config;
});

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      sessionStorage.removeItem(CSRF_KEY);
      if (window.location.hash !== "#/login") {
        window.location.hash = "#/login";
      }
    }
    return Promise.reject(error);
  }
);

export function saveCsrf(value) {
  if (value) {
    sessionStorage.setItem(CSRF_KEY, value);
  } else {
    sessionStorage.removeItem(CSRF_KEY);
  }
}

export function errorMessage(error, fallback = "操作失败") {
  return error?.response?.data?.error || error?.message || fallback;
}
