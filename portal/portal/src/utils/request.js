import axios from "axios";
import NProgress from "nprogress";
import "nprogress/nprogress.css";
import router from "@/router";
import { getRefreshToken, getToken, setRefreshToken, setToken } from "@/utils/token";
import { getAnonymousID } from "@/utils/getUUid";
import { useUserStore } from "@/stores/user";
import globalSetting from "@/setting";
import { handleNetworkError } from "./interceptor";
import { ElMessage } from "element-plus";
import setting from "@/setting";
import { initAppSqlTrace } from "@/plugins/sql-trace";
import { emitRuntimeEvent } from "@/micro-app/runtime";

const appNameSpace = globalSetting.appNameSpace;
const SUCCESS_CODES = ["0", "200", "20000", "SUCCESS", "500001"];
let refreshPromise = null;

// NProgress 配置
NProgress.configure({
  showSpinner: false
});

const instance = axios.create({
  baseURL: "/api",
  timeout: 30000 // 超时时间
});

initAppSqlTrace({
  service: instance
});

function isSuccessCode(code) {
  return SUCCESS_CODES.includes(String(code));
}

function resetExpiredSession(message = "登录已失效，请重新登录") {
  const userStore = useUserStore();
  userStore.resetApp();

  const isRunningInRegularWindow = setting.appRuntimeWindowObject === "window";
  if (isRunningInRegularWindow) {
    router.replace({
      name: "Login",
      query: {
        redirect: router.currentRoute.value?.fullPath
      }
    });
  } else {
    emitRuntimeEvent("AuthExpired", { appName: setting.appName });
  }

  ElMessage.error(message);
}

async function refreshCurrentSession() {
  const accessToken = getToken();
  const refreshToken = getRefreshToken();

  if (!accessToken || !refreshToken) {
    throw new Error("登录已失效，请重新登录");
  }

  if (!refreshPromise) {
    refreshPromise = axios({
      baseURL: instance.defaults.baseURL,
      timeout: instance.defaults.timeout,
      method: "post",
      url: "/yjstation/api/v1/dock/auth/refresh",
      headers: {
        "Content-Type": "application/json;charset=utf-8"
      },
      data: {
        refreshToken,
        token: accessToken
      }
    })
      .then(({ data }) => {
        const { code, msg, data: payload } = data || {};
        if (!isSuccessCode(code) || !payload?.token || !payload?.refreshToken) {
          throw data || new Error(msg || "登录已失效，请重新登录");
        }

        setToken(payload.token);
        setRefreshToken(payload.refreshToken);
        return payload.token;
      })
      .finally(() => {
        refreshPromise = null;
      });
  }

  return refreshPromise;
}

// 配置请求拦截器
instance.interceptors.request.use(
  (config) => {
    NProgress.start(); // 开启 progress bar
    config.headers = config.headers || {};

    const token = getToken();
    if (token && !config.headers.Authorization && !config.headers.authorization) {
      config.headers.Authorization = `Bearer ${token}`;
    }

    const localeHid = localStorage.getItem(`${appNameSpace}.hospitalId`);
    if (config.headers) {
      if (["", undefined, null].includes(config.headers.Hid)) {
        config.headers.Hid = localeHid;
      }
    }

    if (!config.headers.Authorization) {
      const anonymousID = getAnonymousID();
      config.headers.uuid_token = anonymousID;
    }

    if (config.isDownLoadFile) {
      config.responseType = "blob";
    }
    if (config.isUploadFile) {
      config.headers["Content-Type"] = "multipart/form-data";
    }
    if (config.urlencoded) {
      config.headers["Content-Type"] = "application/x-www-form-urlencoded";
    }

    return config;
  },
  (err) => {
    NProgress.done(); // 关闭 progress bar
    return Promise.reject(err); // 将错误消息挂到promise的失败函数上
  }
);

// 配置相应拦截器
instance.interceptors.response.use(
  (res) => {
    NProgress.done();
    const message = res.data.Message || res.data.msg || "未知错误";
    const code = res.data.code; // 获取后端自定义状态码

    // if (res.status !== 200) return Promise.reject(res.data)
    if (res.status !== 200) return Promise.reject(message);

    // 如果是401则跳转到登录页面
    // if (code === 401) {
    //   ElMessage.error('当前登录已失效，请重新登录')
    //   const store = useUserStore()
    //   store.FedLogout().then(() => {
    //     router.replace({
    //       name: 'Login',
    //       params: {
    //         redirect: router.currentRoute.fullPath
    //       }
    //     })
    //   })
    // }

    // 状态码非200则弹窗提示
    // if (code !== 200) {
    //   // 解决连续弹出警告框的问题
    //   if (!window._$messageInstance || !window._$messageInstance.visible) {
    //     window._$messageInstance = ElMessage({
    //       message,
    //       type: 'error',
    //       onClose() {
    //         window._$messageInstance = undefined
    //       }
    //     })
    //   }
    //   return Promise.reject(new Error(message))
    // }
    return res.data;
  },
  async (err) => {
    NProgress.done();
    // 检测网络环境
    if (!window.navigator.onLine) {
      ElMessage.error("无网络连接,请检查当前网络是否正常");
    } else {
      const { response, config: originalRequest = {} } = err;
      const status = response?.status;

      if (status === 401 && !originalRequest.__isRetryRequest && getToken() && getRefreshToken()) {
        try {
          const token = await refreshCurrentSession();
          originalRequest.__isRetryRequest = true;
          originalRequest.headers = originalRequest.headers || {};
          originalRequest.headers.Authorization = `Bearer ${token}`;
          return instance(originalRequest);
        } catch (refreshError) {
          const message = refreshError?.response?.data?.msg || refreshError?.msg || refreshError?.message;
          resetExpiredSession(message);
          return Promise.reject(refreshError);
        }
      }

      if (status === 401) {
        resetExpiredSession("登录信息已失效，请重新登录");
        return Promise.reject(response?.data || err);
      }

      if (response) {
        handleNetworkError(response);
      } else {
        ElMessage.error(err.message || "请求失败");
      }
    }
    return Promise.reject(err);
  }
);

export default instance;
