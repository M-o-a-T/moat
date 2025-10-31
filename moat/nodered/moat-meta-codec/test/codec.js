var helper = require("node-red-node-test-helper");
var codec = require("../lib/codec.js");

describe('MoaT Encoder', function () {
  afterEach(function () {
    helper.unload();
  });

  it('should be loaded', function (done) {
    var flow = [{ id: "n1", type: "moat-meta-encode", name: "test name" }];
    helper.load(codec, flow, function () {
      var n1 = helper.getNode("n1");
      n1.should.have.property('name', 'test name');
      done();
    });
  });

  it('should encode MoaT data', function (done) {
    var flow = [{ id: "n1", type: "moat-meta-encode", name: "test name",wires:[["n2"]] },
    { id: "n2", type: "helper" }];
    helper.load(codec, flow, function () {
      var n2 = helper.getNode("n2");
      var n1 = helper.getNode("n1");
      n2.on("input", function (msg) {
        msg.should.have.property('moat.name', 'Foo');
        msg.should.have.property('moat.time', 12.75);
        done();
      });
      n1.receive({ payload: "SomeData", userProperties: { MoaT: 'Foo\\`AT2' }});
    });
  });
});

describe('MoaT Decoder', function () {
  afterEach(function () {
    helper.unload();
  });

  it('should be loaded', function (done) {
    var flow = [{ id: "n1", type: "moat-meta-decode", name: "test name" }];
    helper.load(codec, flow, function () {
      var n1 = helper.getNode("n1");
      n1.should.have.property('name', 'test name');
      done();
    });
  });

  it('should decode MoaT data', function (done) {
    var flow = [{ id: "n1", type: "moat-meta-decode", name: "test name",wires:[["n2"]] },
    { id: "n2", type: "helper" }];
    helper.load(codec, flow, function () {
      var n2 = helper.getNode("n2");
      var n1 = helper.getNode("n1");
      n2.on("input", function (msg) {
        msg.should.have.property('userProperties.MoaT', 'Foo\\`AT2');
        done();
      });
      n1.receive({ payload: "SomeData", moat: { name: 'Foo', time: 12.75 }});
    });
  });
});
