export function shouldLoginByHostToken({ hostToken, localToken, lastHostTokenMarker }) {
  if (!hostToken) {
    return false;
  }

  if (!localToken) {
    return true;
  }

  return lastHostTokenMarker !== createHostTokenLoginMarker(hostToken);
}

export function createHostTokenLoginMarker(hostToken) {
  const value = String(hostToken || "");
  let hash = 0;

  for (let index = 0; index < value.length; index += 1) {
    hash = (hash * 31 + value.charCodeAt(index)) >>> 0;
  }

  return hash.toString(36);
}
