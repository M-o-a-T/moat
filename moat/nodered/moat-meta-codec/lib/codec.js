const base85 = require('base85-full');
const cbor = require('cbor');

function decode(data) {
    /**
     * Decode a string to a MsgMeta object.
     *
     * Reverses the effect of encode.
     */
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
                d = cbor.decode(base85.decode(Buffer.from(d),"btoa"));
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
    /**
     * Encode this object to a string.
     *
     * Elements are either UTF-8 strings, introduced by `/`, or
     * some other data, introduced by `\`. Strings that include
     * either of these characters are treated as "other data".
     *
     * Empty strings are encoded as zero-length "other data" elements.
     * A value of `None` is encoded as an empty string.
     *
     * The first item is not marked explicitly.
     * It must be a non-empty string.
     *
     * Other data are encoded to CBOR, then base85-encoded
     * (btoa alphabet).
     *
     * The last element may be a dict with free-form content.
     */
    const res = [];

    for (const d of data) {
        if (typeof d === 'string' && d !== "" && !d.includes("/") && !d.includes("\\")) {
            if (!d && res.length === 0) {
                throw new Error("No empty origins");
            }
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
            res.push(base85.encode(cbor.encodeCanonical(d), "btoa"));
        }
    }
    return res.join("");
}

function isObject(obj)
{
    return obj != null && obj.constructor.name === "Object"
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
    var mt = node.moat;
    if (mt === undefined) {
        return;
    }
    if (mt.name === undefined) {
        mt.name = "NodeRed"
    }
    if (mt.time === undefined) {
        mt.time = Date.now()/1000;
    }
    var d = [ mt.name, mt.time ];

    if (mt.a !== undefined) {
        d = d.concat(mt.a);
    }

    var kw;
    if (mt.kw === undefined) {
        kw = {};
    } else {
        kw = mt.kw;
    }
    if (isObject(d[d.length-1]) || ! isEmpty(kw)) {
        d.append(kw)
    }

    if (! ("userProperties" in node)) {
        node.userProperties = {}
    }
    node.userProperties.MoaT = encode(d);
}

function decMsg(node) {
    var mt = node.userProperties;
    if (mt === undefined) { return; }
    mt = mt.MoaT;
    if (mt === undefined) { return; }
    mt = decode(mt);
    console.log("MT",mt)
    if (mt.length && isObject(mt.length-1)) {
        kw = mt.pop();
    } else {
        kw = {};
    }
    var res = {};
    if (mt.length) {
        res.name = mt.shift()
    }
    if (mt.length) {
        res.time = mt.shift()
        res.delay = Date.now()/1000 - res.time;
    }
    res.a = mt
    res.kw = kw

    node.moat = res;
}


module.exports = function(RED) {
    function Encoder(config) {
        RED.nodes.createNode(this,config);
        var node = this;
        node.on('input', function(msg) {
            encMsg(msg);
            node.send(msg);
        });
    }
    function Decoder(config) {
        RED.nodes.createNode(this,config);
        var node = this;
        node.on('input', function(msg) {
            decMsg(msg);
            node.send(msg);
        });
    }
    RED.nodes.registerType("moat-meta-encode",Encoder);
    RED.nodes.registerType("moat-meta-decode",Decoder);
}


module.exports = { decode, encode, encMsg,decMsg };
