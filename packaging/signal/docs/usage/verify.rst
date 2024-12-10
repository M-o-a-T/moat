Verify
======

Verify a pending account registration using :meth:`.verify`.

   .. code-block:: python

      signal_cli_rest_api.verify(
          verification_code="....",
      )

If the account has previously been secured with a PIN:

   .. code-block:: python

      signal_cli_rest_api.verify(
          verification_code="....",
          pin="....",
      )
