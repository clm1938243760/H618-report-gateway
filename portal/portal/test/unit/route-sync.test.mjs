import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  createRuntimeRouteSyncCore,
  resolveRuntimeHostSubPath,
  resolveRuntimeRoutePath,
  shouldEmitRuntimeRouteChange
} from "../../src/micro-app/route-sync-core.js";

describe("runtime route sync", () => {
  it("resolves runtime sub path to the registered app route", () => {
    const routes = [
      { path: "/404", name: "404" },
      { path: "/el/template-standard-list", name: "template-standard-list" }
    ];

    assert.equal(resolveRuntimeRoutePath("/template-standard-list", { appName: "el", routes }), "/el/template-standard-list");
    assert.equal(resolveRuntimeRoutePath("/el/template-standard-list", { appName: "el", routes }), "/el/template-standard-list");
  });

  it("resolves extra host menu prefix to the registered app route", () => {
    const routes = [
      { path: "/404", name: "404" },
      { path: "/template-standard-list", name: "templateStandardList" }
    ];

    assert.equal(
      resolveRuntimeRoutePath("/portal/template-standard-list", {
        appName: "el",
        inboundRoutePrefixes: ["portal"],
        routes
      }),
      "/template-standard-list"
    );
  });

  it("resolves host menu prefix to dynamic child route", () => {
    const router = {
      resolve(path) {
        return {
          matched:
            path === "/system/users/2056687586618949634/edit"
              ? [{ path: "/system/users/:id/edit", name: "systemUserEdit" }]
              : []
        };
      }
    };

    assert.equal(
      resolveRuntimeRoutePath("/el/system/users/2056687586618949634/edit", {
        appName: "el",
        router
      }),
      "/system/users/2056687586618949634/edit"
    );
  });

  it("keeps registered app route when outbound route prefix is empty", () => {
    assert.equal(
      resolveRuntimeHostSubPath("/el/template-standard-list", {
        outboundRoutePrefix: ""
      }),
      "/el/template-standard-list"
    );
  });

  it("resolves registered app route back to configured host menu prefix", () => {
    assert.equal(
      resolveRuntimeHostSubPath("/template-standard-list", {
        outboundRoutePrefix: "portal"
      }),
      "/portal/template-standard-list"
    );
  });

  it("does not emit startup or fallback routes to the host", () => {
    assert.equal(shouldEmitRuntimeRouteChange({ path: "/", name: "app-entry" }), false);
    assert.equal(shouldEmitRuntimeRouteChange({ path: "/login", name: "Login" }), false);
    assert.equal(shouldEmitRuntimeRouteChange({ path: "/404", name: "404" }), false);
    assert.equal(shouldEmitRuntimeRouteChange({ path: "/el/template-standard-list", name: "templateStandardList" }), true);
  });

  it("ignores fallback routes when resolving runtime sub path", () => {
    const routes = [
      { path: "/template-standard-list", name: "404" },
      { path: "/el/template-standard-list", name: "template-standard-list" }
    ];

    assert.equal(resolveRuntimeRoutePath("/template-standard-list", { appName: "el", routes }), "/el/template-standard-list");
  });

  it("stores sub path until routes are ready and flushes it once", async () => {
    const replaces = [];
    const router = {
      currentRoute: {
        value: {
          path: "/"
        }
      },
      getRoutes() {
        return [{ path: "/el/template-standard-list", name: "template-standard-list" }];
      },
      replace(location) {
        replaces.push(location);
        this.currentRoute.value.path = location.path;
      }
    };
    const routeSync = createRuntimeRouteSyncCore({ router, appName: "el" });

    await routeSync.sync("/template-standard-list");
    assert.deepEqual(replaces, []);

    await routeSync.markReady();
    assert.deepEqual(replaces, [{ path: "/el/template-standard-list", replace: true }]);

    await routeSync.markReady();
    assert.equal(replaces.length, 1);
  });

  it("uses pending sub path instead of initial sub path when both exist", async () => {
    const replaces = [];
    const router = {
      currentRoute: {
        value: {
          path: "/"
        }
      },
      getRoutes() {
        return [
          { path: "/el/initial", name: "initial" },
          { path: "/el/pending", name: "pending" }
        ];
      },
      replace(location) {
        replaces.push(location);
        this.currentRoute.value.path = location.path;
      }
    };
    const routeSync = createRuntimeRouteSyncCore({ router, appName: "el" });

    await routeSync.sync("/pending");
    await routeSync.markReady("/initial");

    assert.deepEqual(replaces, [{ path: "/el/pending", replace: true }]);
  });

  it("uses initial sub path when no pending sub path exists", async () => {
    const replaces = [];
    const router = {
      currentRoute: {
        value: {
          path: "/"
        }
      },
      getRoutes() {
        return [{ path: "/el/initial", name: "initial" }];
      },
      replace(location) {
        replaces.push(location);
        this.currentRoute.value.path = location.path;
      }
    };
    const routeSync = createRuntimeRouteSyncCore({ router, appName: "el" });

    await routeSync.markReady("/initial");

    assert.deepEqual(replaces, [{ path: "/el/initial", replace: true }]);
  });

  it("starts runtime sub path listener and stops it", async () => {
    let listener = null;
    let stopped = false;
    const router = {
      currentRoute: {
        value: {
          path: "/"
        }
      },
      getRoutes() {
        return [{ path: "/el/list", name: "list" }];
      },
      replace(location) {
        this.currentRoute.value.path = location.path;
      }
    };
    const routeSync = createRuntimeRouteSyncCore({
      router,
      appName: "el",
      subscribeSubPathChange(callback) {
        listener = callback;
        return () => {
          stopped = true;
        };
      }
    });

    const stop = routeSync.start();
    await listener("/list");
    await routeSync.markReady();
    stop();

    assert.equal(router.currentRoute.value.path, "/el/list");
    assert.equal(stopped, true);
  });

  it("uses runtime initial sub path from factory options", async () => {
    const replaces = [];
    const router = {
      currentRoute: {
        value: {
          path: "/"
        }
      },
      getRoutes() {
        return [{ path: "/el/initial", name: "initial" }];
      },
      replace(location) {
        replaces.push(location);
        this.currentRoute.value.path = location.path;
      }
    };
    const routeSync = createRuntimeRouteSyncCore({
      router,
      appName: "el",
      getInitialSubPath() {
        return "/initial";
      }
    });

    await routeSync.markReady();

    assert.deepEqual(replaces, [{ path: "/el/initial", replace: true }]);
  });
});
