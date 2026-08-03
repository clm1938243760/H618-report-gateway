import setting from "@/setting";

export class Storage {
  static set(key, value) {
    key = key + "";
    if (!key.startsWith(setting.appNameSpace)) {
      //
      key = setting.appNameSpace + "." + key;
    }
    localStorage.setItem(key, JSON.stringify(value));
  }

  static get(key, defaultValue = null) {
    key = key + "";
    if (!key.startsWith(setting.appNameSpace)) {
      //
      key = setting.appNameSpace + "." + key;
    }
    const value = localStorage.getItem(key);
    if (value !== null) {
      let res = null;
      try {
        res = JSON.parse(value);
      } catch (e) {
        console.error(`${key} 读取错误`, e);
      }
      return res;
    }
    return defaultValue;
  }

  static remove(key) {
    key = key + "";
    if (!key.startsWith(setting.appNameSpace)) {
      //
      key = setting.appNameSpace + "." + key;
    }
    localStorage.removeItem(key);
  }

  static clear() {
    localStorage.clear();
  }
}
