"""
pysignalclijsonrpc.api
"""

from base64 import b64encode
from io import BytesIO
from os import remove as os_remove
from re import sub as re_sub
from uuid import uuid4

from jmespath import search as j_search
from magic import from_buffer, from_file
from requests import Session


class SignalCliJSONRPCError(Exception):
    """
    SignalCliJSONRPCError
    """


class SignalCliJSONRPCApi:
    """
    SignalCliJSONRPCApi
    """

    def __init__(
        self, endpoint: str, account: str, auth: tuple = (), verify_ssl: bool = True
    ):
        """
        SignalCliJSONRPCApi

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

    def _jsonrpc(self, method: str, params: object = None, **kwargs):
        """
        Args:
            method (str): JSON-RPC method. Equals signal-cli command.
            params (dict): Method parameters.
            **kwargs: Arbitrary keyword arguments.

        Returns:
            result (dict): The JSON-RPC result.

        Raises:
            :exc:`pysignalclijsonrpc.api.SignalCliJSONRPCError`
        """
        request_id = kwargs.get("request_id") or str(uuid4())
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
                    raise SignalCliJSONRPCError(error)
            return ret.get("result")
        except Exception as err:  # pylint: disable=broad-except
            error = getattr(err, "message", repr(err))
            raise SignalCliJSONRPCError(
                f"signal-cli JSON RPC request failed: {error}"
            ) from err

    @property
    def version(self):
        """
        Fetch version.

        Returns:
            version (str): Version of signal-cli

        Raises:
            :exc:`pysignalclijsonrpc.api.SignalCliJSONRPCError`
        """
        return self._jsonrpc(method="version").get("version")

    def send_message(
        self,
        message: str,
        recipients: list,
        mention: str = "",
        attachments_as_files: list = None,
        attachments_as_bytes: list = None,
        cleanup_attachments: bool = False,
        **kwargs,
    ):  # pylint: disable=too-many-arguments,too-many-locals
        """
        Send message.

        Args:
            message (str): Message to be sent.
            recipients (list): List of recipients.
            mention (str, optional): Mention string (`start:end:recipientNumber`).
            attachments_as_files: (list, optional): List of `str` w/ files to send as attachment(s).
            attachments_as_bytes (list, optional): List of `bytearray` to send as attachment(s).
            cleanup_attachments (bool, optional): Wether to remove files in `attachments_as_files`
                after message(s) has been sent. Defaults to False.
            **kwargs: Arbitrary keyword arguments passed to
                :meth:`._jsonrpc`.

        Returns:
            timestamp (int): The message timestamp.

        Raises:
            :exc:`pysignalclijsonrpc.api.SignalCliJSONRPCError`
        """
        try:
            attachments = []
            if attachments_as_files is not None:
                for filename in attachments_as_files:
                    mime = from_file(filename, mime=True)
                    with open(filename, "rb") as f_h:
                        base64 = b64encode(f_h.read()).decode()
                    attachments.append(f"data:{mime};base64,{base64}")
            if attachments_as_bytes is not None:
                for attachment in attachments_as_bytes:
                    attachment_io_bytes = BytesIO()
                    attachment_io_bytes.write(bytes(attachment))
                    mime = from_buffer(attachment_io_bytes.getvalue(), mime=True)
                    attachments.append(
                        f"data:{mime};base64,{b64encode(bytes(attachment)).decode()}"
                    )
            params = {
                "account": self._account,
                "recipient": recipients,
                "message": message,
                "attachment": attachments,
            }
            if mention:  # pragma: no cover
                # covered in tests/test_quit_group.py
                params.update({"mention": mention})
            ret = self._jsonrpc(
                method="send",
                params=params,
                **kwargs,
            )
            return ret.get("timestamp")
        except Exception as err:  # pylint: disable=broad-except
            error = getattr(err, "message", repr(err))
            raise SignalCliJSONRPCError(
                f"signal-cli JSON RPC request failed: {error}"
            ) from err
        finally:
            if cleanup_attachments:
                for filename in attachments_as_files:
                    os_remove(filename)

    def update_group(
        self,
        name: str,
        members: list,
        add_member_permissions: str = "only-admins",
        edit_group_permissions: str = "only-admins",
        group_link: str = "disabled",
        admins: list = None,
        description: str = "",
        message_expiration_timer: int = 0,
        **kwargs,
    ):  # pylint: disable=too-many-arguments
        """
        Update (create) a group.

        Args:
            name (str): Group name.
            members (list): Group members. List of strings.
            add_member_permissions (str, optional): Group permissions for adding members.
                `every-member` or `only-admins` (default).
            edit_group_permissions (str, optional): Group permissions for editing settings/details.
                `every-member` or `only-admins` (default).
            group_link (GroupLinkChoices, optional): Group Link settings.
                One of `disabled` (default), `enabled` or `enabled-with-approval`.
            admins (list, optional): List of additional group admins.
            description (str, optional): Group description.
            message_expiration_timer (int, optional): Message expiration timer in seconds.
                Defaults to 0 (disabled).
            **kwargs: Arbitrary keyword arguments passed to
                :meth:`._jsonrpc`.

        Returns:
            group_id (str): The group id.

        Raises:
            :exc:`pysignalclijsonrpc.api.SignalCliJSONRPCError`
        """
        try:
            params = {
                "name": name,
                "member": members,
                "setPermissionAddMember": add_member_permissions,
                "setPermissionEditDetails": edit_group_permissions,
                "link": group_link,
                "admin": admins,
                "description": description,
                "expiration": message_expiration_timer,
            }
            ret = self._jsonrpc(method="updateGroup", params=params, **kwargs)
            return ret.get("groupId")
        except Exception as err:  # pylint: disable=broad-except
            error = getattr(err, "message", repr(err))
            raise SignalCliJSONRPCError(
                f"signal-cli JSON RPC request failed: {error}"
            ) from err

    def quit_group(
        self,
        groupid: str,
        delete: bool = False,
        **kwargs,
    ):
        """
        Quit (leave) group.

        Args:
            groupid (str): Group id to quit (leave).
            delete (bool, optional): Also delete group.
                Defaults to `False`.
            **kwargs: Arbitrary keyword arguments passed to
                :meth:`._jsonrpc`.

        Returns:
            result (dict)

        Raises:
            :exc:`pysignalclijsonrpc.api.SignalCliJSONRPCError`
        """
        try:
            params = {
                "groupId": groupid,
                "delete": delete,
            }
            return self._jsonrpc(method="quitGroup", params=params, **kwargs)
        except Exception as err:  # pylint: disable=broad-except
            error = getattr(err, "message", repr(err))
            raise SignalCliJSONRPCError(
                f"signal-cli JSON RPC request failed: {error}"
            ) from err

    def list_groups(
        self,
        **kwargs,
    ):
        """
         List groups.

        Args:
             **kwargs: Arbitrary keyword arguments passed to
                 :meth:`._jsonrpc`.

         Returns:
             result (list)

         Raises:
             :exc:`pysignalclijsonrpc.api.SignalCliJSONRPCError`
        """
        try:
            res = self._jsonrpc(
                method="listGroups",
                **kwargs,
            )
            return res or []
        except Exception as err:  # pylint: disable=broad-except
            error = getattr(err, "message", repr(err))
            raise SignalCliJSONRPCError(
                f"signal-cli JSON RPC request failed: {error}"
            ) from err

    def get_group(self, groupid: str):
        """
        Get group details.

        Args:
            groupid (str): Group id to fetch information for.

        Returns:
            result (dict)

        Raises:
            :exc:`pysignalclijsonrpc.api.SignalCliJSONRPCError`
        """
        try:
            groups = self.list_groups()
            return j_search(f"[?id==`{groupid}`]", groups) or [{}]
        except Exception as err:  # pylint: disable=broad-except  # pragma: no cover
            error = getattr(err, "message", repr(err))
            raise SignalCliJSONRPCError(
                f"signal-cli JSON RPC request failed: {error}"
            ) from err

    def join_group(
        self,
        uri: str,
        **kwargs,
    ):
        """
        Join group.

        Args:
            uri (str): Group invite link like https://signal.group/#...
            **kwargs: Arbitrary keyword arguments passed to
                :meth:`._jsonrpc`.

        Raises:
            :exc:`pysignalclijsonrpc.api.SignalCliJSONRPCError`
        """
        try:
            params = {
                "uri": uri,
            }
            return self._jsonrpc(method="joinGroup", params=params, **kwargs)
        except Exception as err:  # pylint: disable=broad-except
            error = getattr(err, "message", repr(err))
            raise SignalCliJSONRPCError(
                f"signal-cli JSON RPC request failed: {error}"
            ) from err

    def update_profile(
        self, given_name: str = "", family_name: str = "", about: str = "", **kwargs
    ):
        """
        Update profile.

        Args:
            given_name (str, optional): Given name.
            family_name (str, optional): Family name.
            about (str, optional): About information.

        Returns:
            result (bool): True for success.

        Raises:
            :exc:`pysignalclijsonrpc.api.SignalCliJSONRPCError`
        """
        try:
            params = {}
            if given_name:
                params.update({"givenName": family_name})
            if family_name:
                params.update({"familyName": family_name})
            if about:
                params.update({"about": about})
            if params:
                self._jsonrpc(method="updateProfile", params=params, **kwargs)
            return True
        except Exception as err:  # pylint: disable=broad-except
            error = getattr(err, "message", repr(err))
            raise SignalCliJSONRPCError(
                f"signal-cli JSON RPC request failed: {error}"
            ) from err

    def send_reaction(
        self,
        recipient: str,
        emoji: str,
        target_author: str,
        target_timestamp: int,
        remove: bool = False,
        groupid: str = "",
        **kwargs,
    ):  # pylint: disable=too-many-arguments
        """
        Send reaction.

        Args:
            recipient (str): Specify the recipients' phone number.
            emoji (str): Specify the emoji, should be a single unicode grapheme cluster.
            target_author (str): Specify the number of the author of the message to which to react.
            target_timestamp (int): Specify the timestamp of the message to which to react.
            remove (bool, optional): Remove an existing reaction.
                Defaults to `False`.
            groupid (str, optional): Specify the recipient group ID.
            **kwargs: Arbitrary keyword arguments passed to
                :meth:`._jsonrpc`.

        Returns:
            timestamp (int): Timestamp of reaction.

        Raises:
            :exc:`pysignalclijsonrpc.api.SignalCliJSONRPCError`

        Raises:
            :exc:`pysignalclijsonrpc.api.SignalCliJSONRPCError`
        """
        try:
            params = {
                "emoji": emoji,
                "remove": remove,
                "targetAuthor": target_author,
                "targetTimestamp": target_timestamp,
                "recipient": recipient,
            }
            if groupid:  # pragma: no cover
                params.update({"groupId": groupid})
            ret = self._jsonrpc(method="sendReaction", params=params, **kwargs)
            return ret.get("timestamp")
        except Exception as err:  # pylint: disable=broad-except
            error = getattr(err, "message", repr(err))
            raise SignalCliJSONRPCError(
                f"signal-cli JSON RPC request failed: {error}"
            ) from err

    def get_user_status(self, recipients: list, **kwargs):
        """
        Get user network status (is registered?).

        Args:
            recipients (list): List of `str` where each item is a phone number.
            **kwargs: Arbitrary keyword arguments passed to
                :meth:`._jsonrpc`.

        Returns:
            result (dict): The network result.

        Raises:
            :exc:`pysignalclijsonrpc.api.SignalCliJSONRPCError`
        """
        try:
            recipients[:] = [re_sub("^([1-9])[0-9]+$", r"+\1", s) for s in recipients]
            return self._jsonrpc(
                method="getUserStatus",
                params={
                    "recipient": recipients,
                },
                **kwargs,
            )
        except Exception as err:  # pylint: disable=broad-except
            error = getattr(err, "message", repr(err))
            raise SignalCliJSONRPCError(
                f"signal-cli JSON RPC request failed: {error}"
            ) from err

    def register(self, captcha: str = "", voice: bool = False, **kwargs):
        """
        Register account.

        Args:
            captcha (str, optional): The captcha token, required if registration
                failed with a captcha required error.
            voice (bool): The verification should be done over voice, not SMS.
                Defaults to `False`.
            **kwargs: Arbitrary keyword arguments passed to
                :meth:`._jsonrpc`.

        Returns:
            result: The network result. `{}` if successful.

        Raises:
            :exc:`pysignalclijsonrpc.api.SignalCliJSONRPCError`
        """
        try:
            params = {}
            if captcha:  # pragma: no cover
                params.update({"captcha": captcha})
            if voice:  # pragma: no cover
                params.update({"voice": voice})
            return self._jsonrpc(method="register", params=params, **kwargs)
        except Exception as err:  # pylint: disable=broad-except
            error = getattr(err, "message", repr(err))
            raise SignalCliJSONRPCError(
                f"signal-cli JSON RPC request failed: {error}"
            ) from err

    def verify(self, verification_code: str, pin: str = "", **kwargs):
        """
        Verify pending account registration.

        Args:
            verification_code (str): The verification code you received via sms or voice call.
            pin (str, optional): The registration lock PIN, that was set by the user.
            **kwargs: Arbitrary keyword arguments passed to
                :meth:`pysignalclijsonrpc.SignalCliJSONRPCApi._jsonrpc`.

        Returns:
            result: The network result. `{}` if successful.

        Raises:
            :exc:`pysignalclijsonrpc.api.SignalCliJSONRPCError`
        """
        try:
            params = {
                "verificationCode": verification_code,
            }
            if pin:  # pragma: no cover
                params.update({"pin": pin})
            return self._jsonrpc(method="verify", params=params, **kwargs)
        except Exception as err:  # pylint: disable=broad-except
            error = getattr(err, "message", repr(err))
            raise SignalCliJSONRPCError(
                f"signal-cli JSON RPC request failed: {error}"
            ) from err
