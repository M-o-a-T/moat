"""
pysignalclijsonrpc.api
"""

from base64 import b64encode
from io import BytesIO
from uuid import uuid4

from magic import from_buffer, from_file
from requests import Session


class SignalCliRestApiError(Exception):
    """
    SignalCliRestApiError
    """


class SignalCliRestApi:
    """
    SignalCliRestApi
    """

    def __init__(
        self, endpoint: str, account: str, auth: tuple = (), verify_ssl: bool = True
    ):
        """
        SignalCliRestApi

        Args:
            endpoint (str): signal-cli JSON-RPC endpoint.
            account (str): signal-cli account to use.
            auth (tuple): basic authentication credentials (e.g. `("user", "pass")`)
            verify_ssl (bool): SSL verfification for https endpoints
                (defaults to True).
        """
        self._session = Session()
        self._endpoint = endpoint
        self._account = account
        self._auth = auth
        self._verify_ssl = verify_ssl

    def _jsonrpc(self, method: str, params: object = None):
        request_id = str(uuid4())
        if not params:
            params = {}
        params.update({"account": self._account})
        data = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }
        try:
            res = self._session.post(
                url=f"{self._endpoint}",
                json=data,
                auth=self._auth,
                verify=self._verify_ssl,
            )
            res.raise_for_status()
            ret = res.json()
            if ret.get("id") == request_id:
                if ret.get("error"):
                    error = ret.get("error").get("message")
                    raise SignalCliRestApiError(error)
            return ret.get("result")
        except Exception as err:  # pylint: disable=broad-except
            error = getattr(err, "message", repr(err))
            raise SignalCliRestApiError(
                f"signal-cli JSON RPC request failed: {error}"
            ) from err

    @property
    def version(self):
        """
        Fetch version.

        Returns:
            version (str): Version of signal-cli

        Raises:
            :exception:`pysignalclijsonrpc.api.SignalCliRestApiError`
        """
        return self._jsonrpc(method="version").get("version")

    def send_message(
        self,
        message: str,
        recipients: list,
        filenames: list = None,
        attachments_as_bytes: list = None,
    ):
        """
        Send message.

        Args:
            message (str): Message to be sent.
            recipients (list): List of recipients.
            filenames (list): List of `str` w/ filenames to send as attachment(s).
            attachments_as_bytes (list): List of `bytearray` to send as attachment(s).

        Returns:
            timestamp (int): The message timestamp.

        Raises:
            :exception:`pysignalclijsonrpc.api.SignalCliRestApiError`
        """
        attachments = []
        if filenames is not None:
            for filename in filenames:
                try:
                    mime = from_file(filename, mime=True)
                    with open(filename, "rb") as f_h:
                        base64 = b64encode(f_h.read()).decode()
                    attachments.append(
                        f"data:{mime};base64,{base64}"
                    )
                except Exception as err:  # pylint: disable=broad-except
                    error = getattr(err, "message", repr(err))
                    raise SignalCliRestApiError(
                        f"signal-cli JSON RPC request failed: {error}"
                    ) from err
        if attachments_as_bytes is not None:
            for attachment in attachments_as_bytes:
                try:
                    attachment_io_bytes = BytesIO()
                    attachment_io_bytes.write(bytes(attachment))
                    mime = from_buffer(attachment_io_bytes.getvalue(), mime=True)
                    attachments.append(
                        f"data:{mime};base64,{b64encode(bytes(attachment)).decode()}"
                    )
                except Exception as err:  # pylint: disable=broad-except
                    error = getattr(err, "message", repr(err))
                    raise SignalCliRestApiError(
                        f"signal-cli JSON RPC request failed: {error}"
                    ) from err
        return self._jsonrpc(
            method="send",
            params={
                "account": self._account,
                "recipient": recipients,
                "message": message,
                "attachment": attachments,
            },
        ).get("timestamp")
