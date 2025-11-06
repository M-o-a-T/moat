Register
========

Register an account w/ signal-cli using :meth:`.register`.

Prerequisites
-------------

- You will need a spare phone number to use for registration! (SIP numbers are fine)
- [How to get CAPTCHA!](https://github.com/AsamK/signal-cli/wiki/Registration-with-captcha)
- When using SIP numbers wo/ the ability to receive SMS, you'll need to use the `voice` option


Register
--------

   .. code-block:: python

      signal_cli_rest_api.register(
          captcha="....",
          voice=True,
      )

Next step is to :doc:`/usage/verify` the registration using the PIN received via voice call.
