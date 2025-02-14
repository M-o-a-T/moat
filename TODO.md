* moat-link
  * writing the log still saves with a cancel error
  * we send WILL messages but need to react by writing a new
    designated-server record
  * need to tell active clients to reconnect cleanly
  * see TODO at the end of moat/link/server/\_server.py::Server.serve()

* moat-micro
  * test console data
    * write an app for it
  * the single-channel listener+connect apps must be converted to streams
    * so that we can put a Reliable above them
  * BaseCmdMsg dispatcher: multiplex remote iterators locally
  * more flex build of stream structure?
  * security, esp. for specific subtrees / apps
  * test for iterators
  * test for remote cancellation
  * test for reconnecting
  * implement start/stop/restart of subsystems more cleanly
  * teach a subdispatcher to refresh themselves if their destination
    terminates / restarts
  
  * link path. Right now an app doesn't know where it itself is.
    Does it need to?
  
  * docstrings for commands?
  
  * implement (and test) all the fancy pin and relay features
  
  * NamedSerial should open a device if running on Unix-µPy
