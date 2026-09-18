"use strict";

/**
 * CommonJS wrapper for @moat/meta-codec.
 *
 * Node-RED loads nodes via ``require()``, so this CJS shim re-exports
 * the ESM module. It also serves as the default-export entry point
 * for environments that don't support ESM.
 */

const cbor2 = require("cbor2");
const base85 = require("base85-full");

const { encode: cborEncode, decode: cborDecode, cdeEncodeOptions } = cbor2;

function decode(data) {
  const ddec = [];
  let encoded = false;
  while (data) {
    let nextEnc;
    let cc;
    const c1 = data.indexOf("/");
    const c2 = data.indexOf("\\");
    if (c1 === -1) {
      cc = c2;
      nextEnc = true;
    } else if (c2 === -1) {
      cc = c1;
      nextEnc = false;
    } else {
      cc = Math.min(c1, c2);
      nextEnc = cc === c2;
    }
    let d;
    if (cc === -1) {
      d = data;
      data = "";
    } else {
      d = data.substring(0, cc);
      data = data.substring(cc + 1);
    }
    if (encoded) {
      if (d !== "") {
        d = cborDecode(Buffer.from(base85.decode(d, "btoa")));
      }
    } else if (d === "") {
      d = null;
    }
    ddec.push(d);
    encoded = nextEnc;
  }
  return ddec;
}

function encode(data) {
  const res = [];
  for (const d of data) {
    if (
      typeof d === "string" &&
      d !== "" &&
      !d.includes("/") &&
      !d.includes("\\")
    ) {
      if (res.length > 0) {
        res.push("/");
      }
      if (d !== null) {
        res.push(d);
      }
      continue;
    }
    if (res.length === 0) {
      throw new Error("No non-string origins");
    }
    res.push("\\");
    if (d !== "") {
      res.push(
        base85.encode(Buffer.from(cborEncode(d, cdeEncodeOptions)), "btoa"),
      );
    }
  }
  return res.join("");
}

function isObject(obj) {
  return (
    obj !== null &&
    obj !== undefined &&
    typeof obj === "object" &&
    !Array.isArray(obj)
  );
}

function isEmpty(obj) {
  for (const prop in obj) {
    if (Object.hasOwn(obj, prop)) {
      return false;
    }
  }
  return true;
}

function encMsg(node) {
  const mt = node.moat;
  if (mt === undefined) {
    return;
  }
  if (mt.name === undefined) {
    mt.name = "NodeRed";
  }
  if (mt.time === undefined) {
    mt.time = Date.now() / 1000;
  }
  let d = [mt.name, mt.time];
  if (mt.a !== undefined) {
    d = d.concat(mt.a);
  }
  const kw = mt.kw ?? {};
  if (isObject(d[d.length - 1]) || !isEmpty(kw)) {
    d.push(kw);
  }
  if (!("userProperties" in node)) {
    node.userProperties = {};
  }
  node.userProperties.MoaT = encode(d);
}

function decMsg(node) {
  let mt = node.userProperties;
  if (mt === undefined) {
    return;
  }
  mt = mt.MoaT;
  if (mt === undefined) {
    return;
  }
  mt = decode(mt);
  if (mt.length && isObject(mt[mt.length - 1])) {
    node.moat = {
      name: mt[0],
      time: mt[1],
      delay: Date.now() / 1000 - mt[1],
      a: mt.slice(2),
      kw: mt[mt.length - 1],
    };
  } else {
    node.moat = {
      name: mt[0],
      time: mt[1],
      delay: Date.now() / 1000 - mt[1],
      a: mt.slice(2),
      kw: {},
    };
  }
}

module.exports = function (RED) {
  function Encoder(config) {
    RED.nodes.createNode(this, config);
    const node = this;
    node.on("input", function (msg) {
      encMsg(msg);
      node.send(msg);
    });
  }
  function Decoder(config) {
    RED.nodes.createNode(this, config);
    const node = this;
    node.on("input", function (msg) {
      decMsg(msg);
      node.send(msg);
    });
  }
  RED.nodes.registerType("moat-meta-encode", Encoder);
  RED.nodes.registerType("moat-meta-decode", Decoder);
};

module.exports.encode = encode;
module.exports.decode = decode;
module.exports.encMsg = encMsg;
module.exports.decMsg = decMsg;
