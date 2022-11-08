"""
pysignalclijsonrpc
"""

from uuid import uuid4

from requests import post


class SignalCliRestApiError(Exception):
    """
    SignalCliRestApiError
    """


class SignalCliRestApi:
    """
    SignalCliRestApi
    """

    def __init__(self, endpoint: str, verify_ssl: bool = True):
        self._endpoint = endpoint
        self._verify_ssl = verify_ssl

    def _jsonrpc(self, method: str, params: object = None):
        request_id = str(uuid4())
        if not params:
            params = {}
        data = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }
        try:
            res = post(url=f"{self._endpoint}", json=data).json()
            if res.get("id") == request_id:
                if res.get("error"):
                    raise SignalCliRestApiError(res.get("error").get("message"))
            return res.get("result")
        except Exception as err:  # pylint: disable=broad-except
            error = getattr(err, "message", repr(err))
            raise SignalCliRestApiError(
                f"signal-cli JSON RPC request failed: {error}"
            ) from err

    def version(self):
        """
        fetch version
        """
        return self._jsonrpc(method="version").get("version")
