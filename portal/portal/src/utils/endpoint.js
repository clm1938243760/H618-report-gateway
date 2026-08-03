const UPLOAD_PATH = "/api/client/uploadOriginalReport";

export function endpointToHost(endpoint) {
  try {
    const url = new URL(endpoint);
    return url.pathname === UPLOAD_PATH ? url.host : "";
  } catch {
    return "";
  }
}

export function buildUploadEndpoint(value) {
  const host = String(value || "").trim();
  const match = host.match(/^(\d{1,3}(?:\.\d{1,3}){3}):(\d{1,5})$/);
  if (!match) {
    throw new Error("请输入正确的 IPv4 地址和端口，例如 192.168.112.139:9061");
  }
  const octets = match[1].split(".").map(Number);
  const port = Number(match[2]);
  if (octets.some((octet) => octet < 0 || octet > 255) || port < 1 || port > 65535) {
    throw new Error("IP 地址或端口超出有效范围");
  }
  return `http://${match[1]}:${port}${UPLOAD_PATH}`;
}
