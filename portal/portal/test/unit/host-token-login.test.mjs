import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  createHostTokenLoginMarker,
  shouldLoginByHostToken
} from "../../src/micro-app/host-token-login.js";

describe("host token login reuse", () => {
  it("skips platform login when local token exists for the same host token", () => {
    assert.equal(
      shouldLoginByHostToken({
        hostToken: "host-token-a",
        localToken: "child-token",
        lastHostTokenMarker: createHostTokenLoginMarker("host-token-a")
      }),
      false
    );
  });

  it("requires platform login when local token is missing", () => {
    assert.equal(
      shouldLoginByHostToken({
        hostToken: "host-token-a",
        localToken: "",
        lastHostTokenMarker: createHostTokenLoginMarker("host-token-a")
      }),
      true
    );
  });

  it("requires platform login when host token changes", () => {
    assert.equal(
      shouldLoginByHostToken({
        hostToken: "host-token-b",
        localToken: "child-token",
        lastHostTokenMarker: createHostTokenLoginMarker("host-token-a")
      }),
      true
    );
  });

  it("uses a stable marker without storing the full host token", () => {
    const marker = createHostTokenLoginMarker("host-token-a");

    assert.equal(marker, createHostTokenLoginMarker("host-token-a"));
    assert.notEqual(marker, "host-token-a");
    assert.notEqual(marker, createHostTokenLoginMarker("host-token-b"));
  });
});
