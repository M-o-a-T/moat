Send messages
=============

Using :meth:`.send_message`.

Plain text message
------------------

   .. code-block:: python

      signal_cli_rest_api.send_message("Test")

Plain text message w/ attachment from file
------------------------------------------

   .. code-block:: python

      signal_cli_rest_api.send_message("Test", filenames=["/tmp/some-image.png"])
