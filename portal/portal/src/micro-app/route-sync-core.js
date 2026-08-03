// Host subPath is the child-app route requested by the shell; it may include the app prefix or omit it.
// Sync waits for dynamic routes because permission routes are registered after login.
const ROUTE_NAMES_TO_IGNORE = new Set(["pre-loading", "every-to-not-found", "404", "401"]);
const ROUTE_PATHS_TO_IGNORE = new Set(["/", "/login", "/404", "/401"]);

function normalizeSubPath(value) {
  const rawValue = String(value || "").trim();
  if (!rawValue || rawValue === "/") {
    return "/";
  }

  return rawValue.startsWith("/") ? rawValue : `/${rawValue}`;
}

export function createRuntimeRouteSyncCore({
  router,
  appName,
  inboundRoutePrefixes,
  getInitialSubPath = () => "/",
  subscribeSubPathChange = () => () => {},
  mark = () => {}
}) {
  let routesReady = false;
  let pendingSubPath = "";

  function start() {
    return subscribeSubPathChange(sync);
  }

  async function sync(subPath) {
    const normalizedSubPath = normalizeSubPath(subPath);
    if (normalizedSubPath === "/") {
      return false;
    }

    // Host subPath can arrive before dynamic routes are registered.
    if (!routesReady) {
      pendingSubPath = normalizedSubPath;
      return false;
    }

    const targetPath = resolveRuntimeRoutePath(normalizedSubPath, {
      appName,
      inboundRoutePrefixes,
      router,
      routes: router.getRoutes()
    });

    if (targetPath !== router.currentRoute.value.path) {
      mark("route-sync:replace-start", {
        subPath: normalizedSubPath,
        targetPath,
        currentPath: router.currentRoute.value.path
      });
      await router.replace({ path: targetPath, replace: true });
      mark("route-sync:replace-done", {
        subPath: normalizedSubPath,
        targetPath,
        currentPath: router.currentRoute.value.path
      });
    }

    return true;
  }

  async function markReady(initialSubPath = getInitialSubPath()) {
    routesReady = true;
    // Prefer the latest host update over the initial subPath snapshot.
    const subPath = pendingSubPath || normalizeSubPath(initialSubPath);
    pendingSubPath = "";

    if (subPath === "/") {
      return false;
    }

    return sync(subPath);
  }

  return {
    markReady,
    start,
    sync
  };
}

export function resolveRuntimeRoutePath(subPath, { appName, inboundRoutePrefixes, router, routes = [] }) {
  const normalizedSubPath = normalizeSubPath(subPath);
  const prefixes = normalizeRoutePrefixes(appName, inboundRoutePrefixes);
  // Shell menus and child routes may disagree on the app prefix, so both shapes are valid candidates.
  const candidates = new Set([normalizedSubPath]);

  prefixes.forEach((prefix) => {
    const routePrefix = `/${prefix}`;
    if (normalizedSubPath.startsWith(`${routePrefix}/`)) {
      candidates.add(normalizeSubPath(normalizedSubPath.slice(routePrefix.length)));
    } else {
      candidates.add(`${routePrefix}${normalizedSubPath}`);
    }
  });

  const matchedPath = Array.from(candidates).find((candidate) => isKnownRoute(candidate, { router, routes }));

  return matchedPath || normalizedSubPath;
}

export function resolveRuntimeHostSubPath(routePath, { outboundRoutePrefix } = {}) {
  const normalizedRoutePath = normalizeSubPath(routePath);
  const prefix = String(outboundRoutePrefix || "").trim().replace(/^\/+|\/+$/g, "");
  if (!prefix || normalizedRoutePath === "/") {
    return normalizedRoutePath;
  }

  const routePrefix = `/${prefix}`;
  if (normalizedRoutePath === routePrefix || normalizedRoutePath.startsWith(`${routePrefix}/`)) {
    return normalizedRoutePath;
  }

  return `${routePrefix}${normalizedRoutePath}`;
}

export function shouldEmitRuntimeRouteChange(route) {
  if (!route?.path || ROUTE_PATHS_TO_IGNORE.has(route.path)) {
    return false;
  }

  return !ROUTE_NAMES_TO_IGNORE.has(String(route.name));
}

function normalizeRoutePrefixes(appName, inboundRoutePrefixes = []) {
  return [appName, ...inboundRoutePrefixes]
    .map((prefix) => String(prefix || "").trim().replace(/^\/+|\/+$/g, ""))
    .filter(Boolean)
    .filter((prefix, index, prefixes) => prefixes.indexOf(prefix) === index);
}

function isKnownRoute(candidate, { router, routes }) {
  if (router?.resolve) {
    const resolvedRoute = router.resolve(candidate);
    if (resolvedRoute?.matched?.some((route) => !ROUTE_NAMES_TO_IGNORE.has(String(route.name)))) {
      return true;
    }
  }

  const route = routes.find((item) => item.path === candidate);
  return Boolean(route && !ROUTE_NAMES_TO_IGNORE.has(String(route.name)));
}
