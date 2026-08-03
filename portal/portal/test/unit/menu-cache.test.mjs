import assert from "node:assert/strict";
import { beforeEach, describe, it } from "node:test";

class MemoryStorage {
  constructor() {
    this.data = new Map();
  }

  getItem(key) {
    return this.data.has(key) ? this.data.get(key) : null;
  }

  setItem(key, value) {
    this.data.set(key, String(value));
  }

  removeItem(key) {
    this.data.delete(key);
  }

  key(index) {
    return Array.from(this.data.keys())[index] || null;
  }

  get length() {
    return this.data.size;
  }
}

globalThis.window = {
  localStorage: new MemoryStorage()
};

const {
  clearAppMenuPermissions,
  getAppMenuPermissions,
  setAppMenuPermissions
} = await import("../../src/stores/menu-cache.js");

describe("app menu permission cache", () => {
  let storage;

  beforeEach(() => {
    storage = new MemoryStorage();
  });

  it("stores menus and buttons by app code and user code", () => {
    const menus = [{ id: "menu-1", routeVisitPath: "/system/users" }];
    const buttons = ["user:create"];

    setAppMenuPermissions({ appCode: "app-template", userCode: "u001", menus, buttons }, storage);

    assert.deepEqual(getAppMenuPermissions({ appCode: "app-template", userCode: "u001" }, storage), {
      appCode: "app-template",
      userCode: "u001",
      menus,
      buttons
    });
  });

  it("keeps different apps and users isolated", () => {
    setAppMenuPermissions(
      {
        appCode: "app-template",
        userCode: "u001",
        menus: [{ id: "menu-1" }],
        buttons: ["user:create"]
      },
      storage
    );

    assert.equal(getAppMenuPermissions({ appCode: "message-central", userCode: "u001" }, storage), null);
    assert.equal(getAppMenuPermissions({ appCode: "app-template", userCode: "u002" }, storage), null);
  });

  it("clears one user's app menu permissions", () => {
    setAppMenuPermissions(
      {
        appCode: "app-template",
        userCode: "u001",
        menus: [{ id: "menu-1" }],
        buttons: ["user:create"]
      },
      storage
    );

    clearAppMenuPermissions({ appCode: "app-template", userCode: "u001" }, storage);

    assert.equal(getAppMenuPermissions({ appCode: "app-template", userCode: "u001" }, storage), null);
  });

  it("clears all app menu permissions when no app and user are provided", () => {
    setAppMenuPermissions(
      {
        appCode: "app-template",
        userCode: "u001",
        menus: [{ id: "menu-1" }],
        buttons: ["user:create"]
      },
      storage
    );
    setAppMenuPermissions(
      {
        appCode: "message-central",
        userCode: "u002",
        menus: [{ id: "menu-2" }],
        buttons: ["message:create"]
      },
      storage
    );
    storage.setItem("other-key", "1");

    clearAppMenuPermissions(undefined, storage);

    assert.equal(getAppMenuPermissions({ appCode: "app-template", userCode: "u001" }, storage), null);
    assert.equal(getAppMenuPermissions({ appCode: "message-central", userCode: "u002" }, storage), null);
    assert.equal(storage.getItem("other-key"), "1");
  });
});
