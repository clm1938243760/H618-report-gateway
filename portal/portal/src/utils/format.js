import dayjs from "dayjs";

export function formatBytes(value) {
  const bytes = Number(value || 0);
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / 1024 ** index).toFixed(index >= 3 ? 1 : 2)} ${units[index]}`;
}

export function formatTime(value) {
  const timestamp = Number(value || 0);
  if (!timestamp) return "-";
  return dayjs(timestamp * 1000).format("YYYY-MM-DD HH:mm:ss");
}

export function formatDateTime(value) {
  if (value === null || value === undefined || value === "") return "-";
  if (typeof value === "number") return formatTime(value);
  const parsed = dayjs(value);
  return parsed.isValid() ? parsed.format("YYYY-MM-DD HH:mm:ss.SSS") : "-";
}
