import { renderWithQiankun, qiankunWindow } from "vite-plugin-qiankun/dist/helper";
import setting from "@/setting";
import { getUrlParams } from "@/utils/tool";
import { getRefreshToken, getToken, setRefreshToken, setToken } from "@/utils/token";
import { resolveRuntimeHostSubPath, shouldEmitRuntimeRouteChange } from "@/micro-app/route-sync-core";
import { createHostTokenLoginMarker, shouldLoginByHostToken } from "@/micro-app/host-token-login";

const RUNTIME_TYPES = {
  MICRO_APP: "micro-app",
  WUJIE: "wujie",
  QIANKUN: "qiankun",
  STANDALONE: "standalone"
};

let hostContext = null;
let hostProps = null;
const HostTokenLoginMarkerKey = `${setting.appNameSpace}.host-token-login-marker`;

export function detectRuntime() {
  if (window.__MICRO_APP_ENVIRONMENT__ === true || Boolean(window.microApp?.getData)) {
    return { type: RUNTIME_TYPES.MICRO_APP, embedded: true };
  }

  if (window.__POWERED_BY_WUJIE__) {
    return { type: RUNTIME_TYPES.WUJIE, embedded: true };
  }

  if (qiankunWindow.__POWERED_BY_QIANKUN__) {
    return { type: RUNTIME_TYPES.QIANKUN, embedded: true };
  }

  return { type: RUNTIME_TYPES.STANDALONE, embedded: false };
}

export function isMicroAppRuntime() {
  return detectRuntime().type === RUNTIME_TYPES.MICRO_APP;
}

export function normalizeSubPath(value) {
  const rawValue = String(value || "").trim();
  if (!rawValue || rawValue === "/") {
    return "/";
  }

  return rawValue.startsWith("/") ? rawValue : `/${rawValue}`;
}

export function runWithRuntimeLifecycle({ mount, unmount }) {
  const runtime = detectRuntime();

  if (runtime.type === RUNTIME_TYPES.MICRO_APP) {
    waitForMicroAppData().then((data) => {
      mount(createHostContext(runtime.type, data));
    });
    return;
  }

  if (runtime.type === RUNTIME_TYPES.WUJIE) {
    window.__WUJIE_MOUNT = (...args) => mount(createHostContext(runtime.type, args[0]));
    window.__WUJIE_UNMOUNT = (...args) => unmount(...args);
    window.__WUJIE.mount();
    return;
  }

  if (runtime.type === RUNTIME_TYPES.QIANKUN) {
    renderWithQiankun({
      mount: (props) => mount(createHostContext(runtime.type, props)),
      unmount,
      update: (props) => {
        hostProps = props;
        hostContext = createHostContext(runtime.type, props);
      }
    });
    return;
  }

  mount(createHostContext(runtime.type));
}

export async function applyHostContext(context = getHostContext(), { loginByPlatformToken } = {}) {
  hostContext = context;
  const { type, data, eventBus } = context;

  setting.appRuntimeWindowObject = getRuntimeWindowObject(type);
  setting.appEventBus = eventBus;

  let { token, freshToken, ctoken, userCode, appCode } = data;

  const localToken = getToken();
  const lastHostTokenMarker = localStorage.getItem(HostTokenLoginMarkerKey);
  const shouldRefreshLogin = shouldLoginByHostToken({
    hostToken: ctoken,
    localToken,
    lastHostTokenMarker
  });

  if (ctoken && loginByPlatformToken && shouldRefreshLogin) {
    try {
      await loginByPlatformToken(ctoken);
      token = getToken();
      freshToken = getRefreshToken();
      localStorage.setItem(HostTokenLoginMarkerKey, createHostTokenLoginMarker(ctoken));
    } catch (error) {
      throw error;
    }
  } else if (ctoken && loginByPlatformToken) {
    token = localToken;
    freshToken = getRefreshToken();
  }

  if (appCode) {
    window.sessionStorage.setItem(`${setting.appNameSpace}.appCode`, appCode);
  }
  if (token) {
    setToken(token);
  }
  if (freshToken) {
    setRefreshToken(freshToken);
  }
  if (userCode) {
    localStorage.setItem(`${setting.appNameSpace}.userCode`, userCode);
  }
}

export function getHostContext() {
  if (!hostContext) {
    hostContext = createHostContext(detectRuntime().type, hostProps);
  }

  return hostContext;
}

export function getInitialSubPath() {
  if (!isMicroAppRuntime()) {
    return "/";
  }

  return normalizeSubPath(getHostContext().data.subPath);
}

export function onSubPathChange(callback) {
  if (!isMicroAppRuntime()) {
    return () => {};
  }

  const listener = (data) => callback(data?.subPath);
  window.microApp?.addDataListener?.(listener);

  return () => {
    window.microApp?.removeDataListener?.(listener);
  };
}

export function onHostContextChange(callback) {
  if (!isMicroAppRuntime()) {
    return () => {};
  }

  const listener = (data) => {
    const context = createHostContext(RUNTIME_TYPES.MICRO_APP, data);
    hostContext = context;
    callback(context);
  };
  window.microApp?.addDataListener?.(listener);

  return () => {
    window.microApp?.removeDataListener?.(listener);
  };
}

export function emitRouteChange(route) {
  if (!isMicroAppRuntime() || !shouldEmitRuntimeRouteChange(route)) {
    return;
  }

  window.microApp?.dispatch?.({
    type: "route-change",
    appCode: window.sessionStorage.getItem(`${setting.appNameSpace}.appCode`) || setting.appCode,
    subPath: resolveRuntimeHostSubPath(route.path, {
      outboundRoutePrefix: setting.outboundRoutePrefix
    }),
    title: route.meta?.title || ""
  });
}

export function emitRuntimeEvent(type, payload = {}) {
  const context = getHostContext();

  if (context.type === RUNTIME_TYPES.MICRO_APP) {
    window.microApp?.dispatch?.({ type, ...payload });
    return;
  }

  const eventBus = context.eventBus || setting.appEventBus;
  if (!eventBus) {
    return;
  }

  if (typeof eventBus.emit === "function") {
    eventBus.emit(type, payload);
  } else if (typeof eventBus.dispatch === "function") {
    eventBus.dispatch(type, payload);
  }
}

function createHostContext(type, props) {
  const adapter = runtimeAdapters[type] || runtimeAdapters[RUNTIME_TYPES.STANDALONE];
  const data = adapter.getData(props);

  return {
    type,
    embedded: type !== RUNTIME_TYPES.STANDALONE,
    data,
    eventBus: adapter.getEventBus(props)
  };
}

function getRuntimeWindowObject(type) {
  const names = {
    [RUNTIME_TYPES.MICRO_APP]: "microAppWindow",
    [RUNTIME_TYPES.WUJIE]: "wujieWindow",
    [RUNTIME_TYPES.QIANKUN]: "qiankunWindow",
    [RUNTIME_TYPES.STANDALONE]: "window"
  };

  return names[type] || "window";
}

const runtimeAdapters = {
  [RUNTIME_TYPES.MICRO_APP]: {
    getData(data) {
      return data || window.microApp?.getData?.() || {};
    },
    getEventBus() {
      return window.microApp || null;
    }
  },
  [RUNTIME_TYPES.WUJIE]: {
    getData(props = {}) {
      return props || {};
    },
    getEventBus(props = {}) {
      return props.events || props.eventBus || null;
    }
  },
  [RUNTIME_TYPES.QIANKUN]: {
    getData(props = {}) {
      return props || {};
    },
    getEventBus(props = {}) {
      return props.events || props.eventBus || null;
    }
  },
  [RUNTIME_TYPES.STANDALONE]: {
    getData() {
      return getUrlParams(window.location.href);
    },
    getEventBus() {
      return null;
    }
  }
};

function waitForMicroAppData() {
  const currentData = window.microApp?.getData?.() || {};
  if (hasHostData(currentData)) {
    return Promise.resolve(currentData);
  }

  return new Promise((resolve) => {
    let stop = () => {};
    const timer = window.setTimeout(() => {
      stop();
      const timeoutData = window.microApp?.getData?.() || {};
      resolve(timeoutData);
    }, 1500);

    const listener = (data) => {
      if (!hasHostData(data)) {
        return;
      }

      window.clearTimeout(timer);
      stop();
      resolve(data || {});
    };

    stop = () => {
      window.microApp?.removeDataListener?.(listener);
    };

    window.microApp?.addDataListener?.(listener, true);
  });
}

function hasHostData(data) {
  return Object.values(data || {}).some((value) => value !== undefined && value !== null && value !== "");
}
