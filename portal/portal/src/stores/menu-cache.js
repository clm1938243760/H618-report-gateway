import setting from "../setting.js";

const storage = window.localStorage;
const CacheVersion = "v1";
const CacheKeyPrefix = `${setting.appNameSpace}.app-menu-permissions.${CacheVersion}.`;

function getStorageKey({ appCode, userCode }) {
  if (!appCode || !userCode) {
    return "";
  }

  return `${CacheKeyPrefix}${appCode}.${userCode}`;
}

export function getAppMenuPermissions({ appCode, userCode }, targetStorage = storage) {
  const key = getStorageKey({ appCode, userCode });
  if (!key) {
    return null;
  }

  const value = targetStorage.getItem(key);
  if (!value) {
    return null;
  }

  try {
    const data = JSON.parse(value);
    return {
      appCode: data.appCode,
      userCode: data.userCode,
      menus: Array.isArray(data.menus) ? data.menus : [],
      buttons: Array.isArray(data.buttons) ? data.buttons : []
    };
  } catch (error) {
    targetStorage.removeItem(key);
    return null;
  }
}

export function setAppMenuPermissions({ appCode, userCode, menus, buttons }, targetStorage = storage) {
  const key = getStorageKey({ appCode, userCode });
  if (!key) {
    return;
  }

  targetStorage.setItem(
    key,
    JSON.stringify({
      appCode,
      userCode,
      menus: Array.isArray(menus) ? menus : [],
      buttons: Array.isArray(buttons) ? buttons : []
    })
  );
}

export function clearAppMenuPermissions({ appCode, userCode } = {}, targetStorage = storage) {
  const key = getStorageKey({ appCode, userCode });
  if (!key) {
    const keys = [];
    for (let index = 0; index < targetStorage.length; index += 1) {
      const storageKey = targetStorage.key(index);
      if (storageKey?.startsWith(CacheKeyPrefix)) {
        keys.push(storageKey);
      }
    }
    keys.forEach((storageKey) => targetStorage.removeItem(storageKey));
    return;
  }

  targetStorage.removeItem(key);
}
