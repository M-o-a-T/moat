# Register

Register an account w/ signal-cli using `.register`.

## Prerequisites

- You will need a spare phone number to use for registration! (SIP
  numbers are fine)
- \[How to get
  CAPTCHA!\](<https://github.com/AsamK/signal-cli/wiki/Registration-with-captcha>)
- When using SIP numbers wo/ the ability to receive SMS, you'll need to
  use the <span class="title-ref">voice</span> option

## Register

> ``` python
> signal_cli_rest_api.register(
>     captcha="....",
>     voice=True,
> )
> ```

Next step is to `/usage/verify` the registration using the PIN received
via voice call.
