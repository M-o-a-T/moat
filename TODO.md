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
  * app for multiplexed I/O
  * app for Triac control

  * Refactor dispatching to use active hook-in of subpaths
  * move some dispatch code to moat.lib.cmd

  * hook the MoaT loop into dupterm

  * create a separate library for MoaT streams
    * clean-up etc

  * test console data
    * write an app for it
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
