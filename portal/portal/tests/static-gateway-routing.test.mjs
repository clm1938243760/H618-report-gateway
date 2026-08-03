import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const projectRoot = resolve(import.meta.dirname, "..");

function read(relativePath) {
  return readFileSync(resolve(projectRoot, relativePath), "utf8");
}

test("gateway uses static hash routes for every management page", () => {
  const source = read("src/router/index.js");

  assert.equal(source.includes("history: createWebHashHistory()"), true);
  assert.equal(source.includes('path: "/login"'), true);
  assert.equal(source.includes('path: "config"'), true);
  assert.equal(source.includes('path: "reports"'), true);
  assert.equal(source.includes('path: "maintenance"'), true);
  assert.equal(source.includes("dynamic_routes"), false);
});

test("protected routes restore the local gateway session", () => {
  const source = read("src/router/index.js");

  assert.equal(source.includes("await session.restore();"), true);
  assert.equal(source.includes('return session.authenticated ? true : "/login";'), true);
});

test("gateway application mounts one router view", () => {
  const source = read("src/App.vue");

  assert.equal(source.includes("<router-view />"), true);
  assert.equal(source.includes("loginAndInitApp"), false);
});

test("login page identifies the K2B report gateway", () => {
  const source = read("src/views/login/login.vue");

  assert.equal(source.includes("K2B 报告上传网关"), true);
});

test("configuration page exposes all four USB gadget modes", () => {
  const source = read("src/views/gateway/ConfigView.vue");

  for (const mode of ["msc_hid", "printer_hid", "msc", "printer"]) {
    assert.equal(source.includes(`changeMode('${mode}')`), true, mode);
  }
});
