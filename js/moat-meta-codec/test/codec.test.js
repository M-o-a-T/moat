import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { encode, decode, encMsg, decMsg } from "../lib/codec.js";

describe("encode/decode round-trip", () => {
  test("simple string", () => {
    const data = ["hello"];
    const encoded = encode(data);
    assert.equal(encoded, "hello");
    assert.deepEqual(decode(encoded), data);
  });

  test("multiple strings", () => {
    const data = ["foo", "bar", "baz"];
    const encoded = encode(data);
    assert.equal(encoded, "foo/bar/baz");
    assert.deepEqual(decode(encoded), data);
  });

  test("string with slash becomes data", () => {
    const data = ["foo", "bar/baz"];
    const encoded = encode(data);
    // "bar/baz" contains "/" so it's encoded as data
    assert.notEqual(encoded, "foo/bar/baz");
    assert.deepEqual(decode(encoded), data);
  });

  test("string with backslash becomes data", () => {
    const data = ["foo", "bar\\baz"];
    const encoded = encode(data);
    assert.notEqual(encoded, "foo/bar\\baz");
    assert.deepEqual(decode(encoded), data);
  });

  test("null element", () => {
    const data = ["foo", null];
    const encoded = encode(data);
    assert.deepEqual(decode(encoded), data);
  });

  test("empty string element (encoded as zero-length data)", () => {
    // Empty strings are encoded as zero-length "other data" elements (\ with
    // nothing after).  Due to the format's trailing-element limitation, a
    // trailing empty string is lost on decode — this is inherent to the
    // wire format and matches the Python implementation's behaviour.
    const data = ["foo", ""];
    const encoded = encode(data);
    assert.equal(encoded, "foo\\");
  });

  test("number element", () => {
    const data = ["foo", 42];
    const encoded = encode(data);
    assert.deepEqual(decode(encoded), data);
  });

  test("object element", () => {
    const data = ["foo", { key: "val" }];
    const encoded = encode(data);
    assert.deepEqual(decode(encoded), data);
  });

  test("array element", () => {
    const data = ["foo", [1, 2, 3]];
    const encoded = encode(data);
    assert.deepEqual(decode(encoded), data);
  });

  test("first element must be a non-empty string", () => {
    assert.throws(() => encode([""]), /No non-string origins/);
    assert.throws(() => encode([42]), /No non-string origins/);
    assert.throws(() => encode([null]), /No non-string origins/);
  });
});

describe("encMsg / decMsg", () => {
  test("encMsg sets userProperties.MoaT", () => {
    const node = { moat: { name: "Foo", time: 12.75 } };
    encMsg(node);
    assert.ok(node.userProperties);
    assert.ok(node.userProperties.MoaT);
    assert.equal(typeof node.userProperties.MoaT, "string");
  });

  test("encMsg with args and kwargs", () => {
    const node = {
      moat: { name: "Foo", time: 100, a: [1, 2], kw: { x: 1 } },
    };
    encMsg(node);
    assert.ok(node.userProperties.MoaT);
  });

  test("encMsg defaults name and time", () => {
    const node = { moat: {} };
    encMsg(node);
    assert.ok(node.userProperties.MoaT);
  });

  test("encMsg skips if moat is undefined", () => {
    const node = {};
    encMsg(node);
    assert.equal(node.userProperties, undefined);
  });

  test("decMsg reverses encMsg", () => {
    const node = { moat: { name: "Foo", time: 12.75 } };
    encMsg(node);

    const node2 = { userProperties: { MoaT: node.userProperties.MoaT } };
    decMsg(node2);
    assert.ok(node2.moat);
    assert.equal(node2.moat.name, "Foo");
    assert.equal(node2.moat.time, 12.75);
    assert.deepEqual(node2.moat.a, []);
    assert.deepEqual(node2.moat.kw, {});
  });

  test("decMsg with args", () => {
    const node = { moat: { name: "Foo", time: 12.75, a: [1, 2, 3] } };
    encMsg(node);

    const node2 = { userProperties: { MoaT: node.userProperties.MoaT } };
    decMsg(node2);
    assert.deepEqual(node2.moat.a, [1, 2, 3]);
  });

  test("decMsg with kwargs", () => {
    const node = {
      moat: { name: "Foo", time: 12.75, kw: { x: 1, y: 2 } },
    };
    encMsg(node);

    const node2 = { userProperties: { MoaT: node.userProperties.MoaT } };
    decMsg(node2);
    assert.deepEqual(node2.moat.kw, { x: 1, y: 2 });
  });

  test("decMsg skips if userProperties is undefined", () => {
    const node = {};
    decMsg(node);
    assert.equal(node.moat, undefined);
  });

  test("decMsg skips if MoaT property is missing", () => {
    const node = { userProperties: {} };
    decMsg(node);
    assert.equal(node.moat, undefined);
  });
});
