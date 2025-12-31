---
hero: Any spare days that are not in the calendar?
---

* moat.ALL
  * ruff it all
  * pyright?
  * test coverage?

* link vs. lib.cmd vs. micro
  * unify command handling, directory, readiness, etc.

* moat.lib.cmd
  * Add support for tunneling through websockets

* moat.bms
  * get it to work, dammit

* moat.kv
  * migrate code handling to moat.link
  * migrate jobs to moat.link
    * simplify error handling
  * migrate extensions to moat.link

* moat.src
  * migrator
    * auto-migrate updates
    * option to create a workspace

* moat.lib.cbor
  * auto-generated proxies
  * add a way to release them
    * idea: store a reference in the codec and use weakrefs in the actual
      proxy dict

* moat.lib.pid
  * bumpless parameter changes

* moat.util
  * config
    * move to moat.lib.config
    * reload with NotGiven: first assemble the whole thing with NotGiven
      intact, then apply to existing config en bloc
  * attrdict
    * drop dict compatibility and methods

* moat.link
  * host
    * monitoring by creating an error
  * error
    * mirror errors to notify, according to some rules
  * monitor
    * watch for data that doesn't change, create errors

  * [recovery from network split]{#todo-link-mqtt}
    * replay data that MQTT has replaced with older versions;
      see TODO in moat.link.server.\_server:Server.recover\_split

* moat.micro
  * stream file contents
  * "safe" config reload, i.e. with fallback
  * remote file system for MPy

  * Refactor dispatching to use active hook-in of subpaths
  * move some dispatch code to moat.lib.cmd

  * app for multiplexed I/O
  * app for Triac control

  * create a separate library for MoaT streams
    * clean-up etc

  * the single-channel listener+connect apps must be converted to streams
    * so that we can put a Reliable above them
  * BaseCmdMsg dispatcher: multiplex remote iterators locally
  * more flex build of stream structure?
  * security, esp. for specific subtrees / apps
  * implement start/stop/restart of subsystems more cleanly
  * teach a subdispatcher to refresh itself if their destination
    terminates / restarts

  * link path. Right now an app doesn't know where it itself is.
    Does it need to?

  * implement (and test) all the fancy pin and relay features

  * NamedSerial should open a device if running on Unix-µPy

  * tell mpy-cross about the destination architecture
    so that `@micropython.native` works

  * MicroPython port
    * 4beafa4e919bf2fe8ea424290fc97b5782e1040d still required?
    * native: 36ae50aa9629871ae597ec530127dace6ba01bee
    * native: e82d9b7881d20bef5347c40f0cf7543a11104e0c
    * 8ca55e2c1ae21afdb2e7cabf738b064a30d725e7

    To look into:
    * f7635bbaee4eed4926dd78d03eff99c7430bb1ce

    To add to MoaT recipes:
    * deecb269153d591dadb2eebd34cea5d573874433
