import { createSqlTraceController } from "@jlkj/jl-components-vue3";

const sqlTraceController = createSqlTraceController({
  endpointPath: "/yjstation/api/v1/debug/sql-trace",
  enabled: false,
  visible: false,
  preserveLogs: false,
  maxHistory: 50
});

sqlTraceController.resetAccess();

function initAppSqlTrace(options = {}) {
  const { service, router, checkPermission } = options;

  if (typeof checkPermission === "function") {
    sqlTraceController.configureAccess({
      checkPermission
    });
  }

  return sqlTraceController.install({
    service,
    router,
    mode: "path"
  });
}

async function refreshAppSqlTraceAccess(params, options = {}) {
  const checkPermission = options.checkPermission;

  if (typeof checkPermission === "function") {
    sqlTraceController.configureAccess({
      checkPermission
    });
  }

  return sqlTraceController.refreshAccess(params, options);
}

function resetAppSqlTraceAccess() {
  sqlTraceController.resetAccess();
}

export { initAppSqlTrace, refreshAppSqlTraceAccess, resetAppSqlTraceAccess, sqlTraceController };
