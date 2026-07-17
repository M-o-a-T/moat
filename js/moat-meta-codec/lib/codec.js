/**
 * MoaT metadata codec for Node-RED.
 *
 * Encodes/decodes MoaT message metadata to/from the ``MoaT`` MQTT user property.
 * Elements are either UTF-8 strings (introduced by ``/``) or arbitrary data
 * (introduced by ``\\``). Arbitrary data is CBOR-encoded then base85-encoded
 * (btoa alphabet).
 *
 * @module @moat/meta-codec
 */

import { encode as cborEncode, decode as cborDecode, cdeEncodeOptions } from "cbor2";
import base85 from "base85-full";

/**
 * Decode a MoaT metadata string to an array of elements.
 *
 * Reverses {@link encode}.
 *
 * @param {string} data — the encoded string
 * @returns {unknown[]} — array of decoded elements
 */
export function decode(data) {
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

/**
 * Encode an array of elements to a MoaT metadata string.
 *
 * Elements are either UTF-8 strings (introduced by ``/``) or some other
 * data (introduced by ``\\``). Strings that include ``/`` or ``\\`` are
 * treated as "other data".
 *
 * Empty strings are encoded as zero-length "other data" elements.
 * A value of ``null`` is encoded as an empty string.
 *
 * The first item is not marked explicitly. It must be a non-empty string.
 *
 * Other data are encoded to CBOR (canonical), then base85-encoded (btoa
 * alphabet).
 *
 * @param {unknown[]} data — array of elements to encode
 * @returns {string} — the encoded string
 */
export function encode(data) {
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

/**
 * Check whether a value is a plain object (not an array, not null).
 *
 * @param {*} obj
 * @returns {boolean}
 */
function isObject(obj) {
  return (
    obj !== null &&
    obj !== undefined &&
    typeof obj === "object" &&
    !Array.isArray(obj)
  );
}

/**
 * Check whether an object has no own enumerable properties.
 *
 * @param {Record<string, unknown>} obj
 * @returns {boolean}
 */
function isEmpty(obj) {
  for (const prop in obj) {
    if (Object.hasOwn(obj, prop)) {
      return false;
    }
  }
  return true;
}

/**
 * Encode a Node-RED message's MoaT metadata to the ``MoaT`` user property.
 *
 * Reads ``msg.moat`` and writes ``msg.userProperties.MoaT``.
 *
 * @param {{ moat?: Record<string, unknown>, userProperties?: Record<string, string> }} node — the Node-RED message
 */
export function encMsg(node) {
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

/**
 * Decode a Node-RED message's ``MoaT`` user property to ``msg.moat``.
 *
 * @param {{ moat?: Record<string, unknown>, userProperties?: Record<string, string> }} node — the Node-RED message
 */
export function decMsg(node) {
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

/**
 * Node-RED node registration.
 *
 * Called by Node-RED when loading this node.
 *
 * @param {import("node-red").NodeAPI} RED — the Node-RED runtime API
 */
export default function (RED) {
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
}
