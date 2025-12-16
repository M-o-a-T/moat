# Send messages

Using `.send_message`.

## Plain text message

> ``` python
> signal_cli_rest_api.send_message("Test")
> ```

## Plain text message w/ attachment from file

> ``` python
> signal_cli_rest_api.send_message("Test", filenames=["/tmp/some-image.png"])
> ```
