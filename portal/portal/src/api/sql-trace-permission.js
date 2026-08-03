import qs from "qs";
import request from "@/utils/request";

export function checkSqlTracePermission(params) {
  return request({
    url: `/yjstation/api/v1/debug/sql-trace/permissions/check?${qs.stringify(params || {})}`,
    method: "get"
  });
}
