# Apps

Apps are the building blocks for MoaT-RPC and MoaT-micro.

MoaT comes with some building blocks (structure, communication, data
transfer) which you can connect to seamlessly run more than one service in
a MoaT process or on a MoaT-micro satellite.

… and if the predefined parts are not sufficient, it's easy to write your
own.

## Structure

### Coding guidelines

* `moat.lib.micro` is your friend, ensuring that you can run your app
  unmodified on CPython or MicroPython (assuming it doesn't talk to
  dedicated hardware).
* **Never** call `asyncio.create_task`. In fact, don't import from
  `asyncio` at all.
* When you want to do more than one thing at once, use a taskgroup.
* Apps should do one thing well. Want to do two things? Use two apps.
* Delegate short-but-blocking tasks to a different thread, using
  `moat.lib.micro.to_thread`.
* Don't write long-but-blocking tasks.
* Calling other apps should be top-down. A relay calls the pin it controls,
  a temperature sensor calls the i²c bus to start the sensor and read the data.
* If you're unsure wich app is the top, chances are good that neither is.
  Code both to be passive and use an instance of our transfer app to shuffle
  data from one to the other.
