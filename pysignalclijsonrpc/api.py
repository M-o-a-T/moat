"""
pysignalclijsonrpc
"""

from uuid import uuid4

from requests import Session


class SignalCliRestApiError(Exception):
    """
    SignalCliRestApiError
    """


class SignalCliRestApi:
    def __init__(self, endpoint: str, account: str, verify_ssl: bool = True):
        """
        SignalCliRestApi

        Args:
            endpoint (str): signal-cli JSON-RPC endpoint.
            account (str): signal-cli account to use.
            verify_ssl (bool): SSL verfification for https endpoints
                (defaults to True).
        """
        self._session = Session()
        self._endpoint = endpoint
        self._account = account
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
                url=f"{self._endpoint}", json=data, verify=self._verify_ssl
            )
            res.raise_for_status()
            ret = res.json()
            if ret.get("id") == request_id:
                if ret.get("error"):
                    raise SignalCliRestApiError(ret.get("error").get("message"))
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

    def send_message(self, message: str, recipients: list):
        """
        Send message.

        Args:
            message (str): Message to be sent.
            recipients (list): List of recipients.

        Returns:
            timestamp (int): The message timestamp.

        Raises:
            :exception:`pysignalclijsonrpc.api.SignalCliRestApiError`
        """
        return self._jsonrpc(
            method="send",
            params={
                "account": self._account,
                "recipient": recipients,
                "message": message,
            },
        ).get("timestamp")
