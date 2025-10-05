---
hero: Any spare days that are not in the calendar?
---

* moat.ALL
  * ruff it all
  * pyright?
  * test coverage?

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
  * a way to release them
  * auto-release after some time / max cache size?

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

  * create a separate library for MoaT streams
    * clean  up etc

  * test console data
    * write an app for it
  * the single-channel listener+connect apps must be converted to streams
    * so that we can put a Reliable above them
  * BaseCmdMsg dispatcher: multiplex remote iterators locally
  * more flex build of stream structure?
  * security, esp. for specific subtrees / apps
  * implement start/stop/restart of subsystems more cleanly
  * teach a subdispatcher to refresh themselves if their destination
    terminates / restarts

  * link path. Right now an app doesn't know where it itself is.
    Does it need to?

  * implement (and test) all the fancy pin and relay features

  * NamedSerial should open a device if running on Unix-µPy
