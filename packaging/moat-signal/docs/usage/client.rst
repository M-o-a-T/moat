Client
======

All API requests will be handled by the :class:`moat.signal.api.SignalClient`.

Create a client
---------------

   .. code-block:: python

      from moat.signal.api import Client
      
      signal_api = Client(
          endpoint="http://localhost:3000/api/v1/rpc",
          account="+1234567890" # one of your registered signal-cli accounts
      )

Create a client with basic authentication
-----------------------------------------

   .. code-block:: python

      from moat.signal.api import Client
      
      signal_api = Client(
          endpoint="http://localhost:8080/api/v1/rpc",
          account="+1234567890",
          auth=("user", "password")
      )

Create a client using HTTPS w/ self-signed certificates
------------------------------------------------------

   .. code-block:: python

      from moat.signal.api import Client
      
      signal_api = Client(
          endpoint="https://localhost:8443/api/v1/rpc",
          account="+1234567890",
          verify_ssl=False
      )
