import { test, describe, before, after } from "node:test";
import assert from "node:assert/strict";

// Node-RED test helper uses CommonJS, so we use dynamic import
// of the CJS wrapper for these tests.
let helper;
let codecMod;

before(async () => {
  helper = (await import("node-red-node-test-helper")).default;
  codecMod = await import("../lib/codec.cjs");
});

after(() => {
  if (helper && helper.unload) {
    helper.unload();
  }
});

describe("MoaT Encoder (Node-RED)", () => {
  test("should be loaded", {}, (_t, done) => {
    const flow = [{ id: "n1", type: "moat-meta-encode", name: "test name" }];
    helper.load(codecMod.default, flow, function () {
      const n1 = helper.getNode("n1");
      assert.equal(n1.name, "test name");
      helper.unload();
      done();
    });
  });

  test("should encode MoaT data", {}, (_t, done) => {
    const flow = [
      {
        id: "n1",
        type: "moat-meta-encode",
        name: "test name",
        wires: [["n2"]],
      },
      { id: "n2", type: "helper" },
    ];
    helper.load(codecMod.default, flow, function () {
      const n2 = helper.getNode("n2");
      const n1 = helper.getNode("n1");
      n2.on("input", function (msg) {
        assert.ok(msg.userProperties);
        assert.ok(msg.userProperties.MoaT);
        helper.unload();
        done();
      });
      n1.receive({
        payload: "SomeData",
        moat: { name: "Foo", time: 12.75 },
      });
    });
  });
});

describe("MoaT Decoder (Node-RED)", () => {
  test("should be loaded", {}, (_t, done) => {
    const flow = [{ id: "n1", type: "moat-meta-decode", name: "test name" }];
    helper.load(codecMod.default, flow, function () {
      const n1 = helper.getNode("n1");
      assert.equal(n1.name, "test name");
      helper.unload();
      done();
    });
  });

  test("should decode MoaT data", {}, (_t, done) => {
    const flow = [
      {
        id: "n1",
        type: "moat-meta-decode",
        name: "test name",
        wires: [["n2"]],
      },
      { id: "n2", type: "helper" },
    ];
    helper.load(codecMod.default, flow, function () {
      const n2 = helper.getNode("n2");
      const n1 = helper.getNode("n1");
      n2.on("input", function (msg) {
        assert.ok(msg.moat);
        assert.equal(msg.moat.name, "Foo");
        assert.equal(msg.moat.time, 12.75);
        helper.unload();
        done();
      });
      // First encode, then feed the encoded string to the decoder
      const encNode = {
        moat: { name: "Foo", time: 12.75 },
      };
      codecMod.encMsg(encNode);
      n1.receive({
        payload: "SomeData",
        userProperties: { MoaT: encNode.userProperties.MoaT },
      });
    });
  });
});
