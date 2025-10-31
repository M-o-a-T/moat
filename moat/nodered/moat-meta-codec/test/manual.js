var codec = require("../lib/codec.js");

base = { payload: "SomeData", userProperties: { MoaT: 'Foo\\`AT2' }};
codec.decMsg(base);
console.log(base);

base = { payload: "SomeData", moat: { name: 'Foo', time: 12.75 }};
codec.encMsg(base);
console.log(base);
