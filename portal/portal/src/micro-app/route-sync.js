import { getInitialSubPath, onSubPathChange } from "./runtime.js";
import { createRuntimeRouteSyncCore, resolveRuntimeHostSubPath, resolveRuntimeRoutePath } from "./route-sync-core.js";

export function createRuntimeRouteSync({ router, appName, inboundRoutePrefixes }) {
  return createRuntimeRouteSyncCore({
    router,
    appName,
    inboundRoutePrefixes,
    getInitialSubPath,
    subscribeSubPathChange: onSubPathChange
  });
}

export { resolveRuntimeHostSubPath, resolveRuntimeRoutePath };
