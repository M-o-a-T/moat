"""
MoaT.signal API
"""

from __future__ import annotations

from base64 import b64encode
from io import BytesIO
from os import remove as os_remove
from re import search as re_search
from re import sub as re_sub
from uuid import uuid4
from warnings import warn

from httpx import AsyncClient
from jmespath import search as j_search
from magic import from_buffer, from_file
from packaging.version import parse as version_parse


def bytearray_to_rfc_2397_data_url(byte_array: bytearray):
    """
    Convert bytearray to RFC 2397 data url.

    Args:
        byte_array (bytearray)

    Returns:
        result (str): RFC 2397 data url
    """
    attachment_io_bytes = BytesIO()
    attachment_io_bytes.write(bytes(byte_array))
    mime = from_buffer(attachment_io_bytes.getvalue(), mime=True)
    return f"data:{mime};base64,{b64encode(bytes(byte_array)).decode()}"


def get_attachments(attachments_as_files, attachments_as_bytes):
    """
    Get attachments from either files and/or bytes.

    Args:
        attachments_as_files: (list, optional): List of `str` w/ files to send as attachment(s).
        attachments_as_bytes (list, optional): List of `bytearray` to send as attachment(s).

    Returns:
        attachments (list): List of attachments to send.
    """
    attachments = []
    if attachments_as_files is not None:
        for filename in attachments_as_files:
            mime = from_file(filename, mime=True)
            with open(filename, "rb") as f_h:
                base64 = b64encode(f_h.read()).decode()
            attachments.append(f"data:{mime};base64,{base64}")
    if attachments_as_bytes is not None:
        for attachment in attachments_as_bytes:
            attachments.append(bytearray_to_rfc_2397_data_url(attachment))
    return attachments


class SignalError(Exception):
    """
    Exception
    """


class SignalClient:
    """
    SignalClient
    """

    def __init__(self, endpoint: str, account: str, auth: tuple = (), **kw):
        """
        SignalClient

        Args:
            endpoint (str): signal-cli JSON-RPC endpoint.
            account (str): signal-cli account to use.
            auth (tuple): basic authentication credentials (e.g. `("user", "pass")`)
        … and any other arguments of `httpx.AsyncClient`.

        """
        self._session = AsyncClient(**kw)
        self._endpoint = endpoint
        self._account = account
        self._auth = auth or None

    async def _jsonrpc(self, method: str, params: object = None, **kwargs):
        """
        Args:
            method (str): JSON-RPC method. Equals signal-cli command.
            params (dict): Method parameters.
            **kwargs: Arbitrary keyword arguments.

        Returns:
            result (dict): The JSON-RPC result.

        Raises:
            :exc:`moat.signal.api.SignalError`
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
            res = await self._session.post(
                url=f"{self._endpoint}",
                json=data,
                auth=self._auth,
            )
            res.raise_for_status()
            ret = res.json()
            if ret.get("id") == request_id and ret.get("error"):
                error = ret.get("error").get("message")
                raise SignalError(error)
            return ret.get("result")
        except Exception as err:  # pylint: disable=broad-except
            error = getattr(err, "message", repr(err))
            raise SignalError(f"signal-cli JSON RPC request failed: {error}") from err

    @property
    async def version(self):
        """
        Fetch version.

        Returns:
            version (str): Version of signal-cli

        Raises:
            :exc:`moat.signal.api.SignalError`
        """
        return (await self._jsonrpc(method="version")).get("version")

    async def send_message(
        self,
        message: str,
        recipients: list,
        mention: str = "",
        attachments_as_files: list | None = None,
        attachments_as_bytes: list | None = None,
        cleanup_attachments: bool = False,
        **kwargs,
    ):  # pylint: disable=too-many-arguments,too-many-locals
        """
        Send message.

        Args:
            message (str): Message to be sent.
            recipients (list): List of recipients.
            mention (str, optional): Mention string (`start:end:recipientNumber`).
            attachments_as_files: (list, optional):
                List of `str` w/ files to send as attachment(s).
            attachments_as_bytes (list, optional):
                List of `bytearray` to send as attachment(s).
            cleanup_attachments (bool, optional):
                Wether to remove files in `attachments_as_files`
                after message(s) has been sent. Defaults to False.
            **kwargs: Arbitrary keyword arguments passed to
                :meth:`._jsonrpc`.

        Returns:
            result (dict): Dictionary of timestamps and related recipients.
                Example: `{'timestamps': {timestamp: {'recipients': ['...']}}}`

        Raises:
            :exc:`moat.signal.api.SignalError`
        """
        response_method_mapping = {
            "recipient": "recipientAddress.number",
        }
        timestamps = {}
        contacts = []
        groups = []
        attachments = []
        attachments = get_attachments(
            attachments_as_files,
            attachments_as_bytes,
        )
        try:
            _unknown, contacts, groups = await self.get_recipients(recipients)
            params = {
                "account": self._account,
                "message": message,
                "attachment": attachments,
            }
            if mention:  # pragma: no cover
                # covered in tests/test_quit_group.py
                params.update({"mention": mention})
            for key, value in {"recipient": contacts, "groupId": groups}.items():
                if value:
                    t_params = params.copy()
                    t_params.update({key: value})
                    t_res = await self._jsonrpc(
                        method="send",
                        params=t_params,
                        **kwargs,
                    )
                    t_timestamp = t_res.get("timestamp")
                    if t_timestamp:
                        search_for = f"[*].{response_method_mapping.get(key, key)}"
                        timestamps.update(
                            {
                                t_timestamp: {
                                    "recipients": list(
                                        set(
                                            j_search(
                                                search_for,
                                                t_res.get("results"),
                                            ),
                                        ),
                                    ),
                                },
                            },
                        )
            return {"timestamps": timestamps}
        finally:
            if cleanup_attachments:
                for filename in attachments_as_files:
                    os_remove(filename)

    async def update_group(
        self,
        name: str,
        members: list,
        add_member_permissions: str = "only-admins",
        edit_group_permissions: str = "only-admins",
        group_link: str = "disabled",
        admins: list | None = None,
        description: str = "",
        message_expiration_timer: int = 0,
        avatar_as_bytes: bytearray = bytearray(),
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
            avatar_as_bytes (bytearray, optional): `bytearray` containing image to set as avatar.
                Supported since signal-cli 0.11.6.
            **kwargs: Arbitrary keyword arguments passed to
                :meth:`._jsonrpc`.

        Returns:
            group_id (str): The group id.

        Raises:
            :exc:`moat.signal.api.SignalError`
        """
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
        if avatar_as_bytes:  # pragma: no cover
            if version_parse(self.version) < version_parse("0.11.6"):
                warn("'avatar_as_bytes' not supported (>= 0.11.6), skipping.")
            else:
                params.update({"avatarFile": bytearray_to_rfc_2397_data_url(avatar_as_bytes)})
        ret = await self._jsonrpc(method="updateGroup", params=params, **kwargs)
        return ret.get("groupId")

    async def quit_group(
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
            :exc:`moat.signal.api.SignalError`
        """
        params = {
            "groupId": groupid,
            "delete": delete,
        }
        return await self._jsonrpc(method="quitGroup", params=params, **kwargs)

    async def list_groups(
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
             :exc:`moat.signal.api.SignalError`
        """
        res = await self._jsonrpc(
            method="listGroups",
            **kwargs,
        )
        return res or []

    async def get_group(self, groupid: str):
        """
        Get group details.

        Args:
            groupid (str): Group id to fetch information for.

        Returns:
            result (dict)

        Raises:
            :exc:`moat.signal.api.SignalError`
        """
        groups = await self.list_groups()
        return j_search(f"[?id==`{groupid}`]", groups) or [{}]

    async def join_group(
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
            :exc:`moat.signal.api.SignalError`
        """
        params = {
            "uri": uri,
        }
        return await self._jsonrpc(method="joinGroup", params=params, **kwargs)

    async def update_profile(
        self,
        given_name: str = "",
        family_name: str = "",
        about: str = "",
        avatar_as_bytes: bytearray = bytearray(),
        **kwargs,
    ):
        """
        Update profile.

        Args:
            given_name (str, optional): Given name.
            family_name (str, optional): Family name.
            about (str, optional): About information.
            avatar_as_bytes (bytearray, optional): `bytearray` containing image to set as avatar.
                Supported since signal-cli 0.11.6.

        Returns:
            result (bool): True for success.

        Raises:
            :exc:`moat.signal.api.SignalError`
        """
        params = {}
        if given_name:
            params.update({"givenName": family_name})
        if family_name:
            params.update({"familyName": family_name})
        if about:
            params.update({"about": about})
        if avatar_as_bytes:  # pragma: no cover
            if version_parse(self.version) < version_parse("0.11.6"):
                warn("'avatar_as_bytes' not supported (>= 0.11.6), skipping.")
            else:
                params.update({"avatar": bytearray_to_rfc_2397_data_url(avatar_as_bytes)})
        if params:
            await self._jsonrpc(method="updateProfile", params=params, **kwargs)
        return True

    async def send_reaction(
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

        """
        params = {
            "emoji": emoji,
            "remove": remove,
            "targetAuthor": target_author,
            "targetTimestamp": target_timestamp,
            "recipient": recipient,
        }
        if groupid:  # pragma: no cover
            params.update({"groupId": groupid})
        ret = await self._jsonrpc(method="sendReaction", params=params, **kwargs)
        return ret.get("timestamp")

    async def get_user_status(self, recipients: list, **kwargs):
        """
        Get user network status (is registered?).

        Args:
            recipients (list): List of `str` where each item is a phone number.
            **kwargs: Arbitrary keyword arguments passed to
                :meth:`._jsonrpc`.

        Returns:
            result (dict): The network result.

        Raises:
            :exc:`moat.signal.api.SignalError`
        """
        recipients[:] = [re_sub("^([1-9])[0-9]+$", r"+\1", s) for s in recipients]
        return await self._jsonrpc(
            method="getUserStatus",
            params={
                "recipient": recipients,
            },
            **kwargs,
        )

    async def register(self, captcha: str = "", voice: bool = False, **kwargs):
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
            :exc:`moat.signal.api.SignalError`
        """
        params = {}
        if captcha:  # pragma: no cover
            params.update({"captcha": captcha})
        if voice:  # pragma: no cover
            params.update({"voice": voice})
        return await self._jsonrpc(method="register", params=params, **kwargs)

    async def verify(self, verification_code: str, pin: str = "", **kwargs):
        """
        Verify pending account registration.

        Args:
            verification_code (str): The verification code you received via sms or voice call.
            pin (str, optional): The registration lock PIN, that was set by the user.
            **kwargs: Arbitrary keyword arguments passed to
                :meth:`moat.signal.api.SignalClient._jsonrpc`.

        Returns:
            result: The network result. `{}` if successful.

        Raises:
            :exc:`moat.signal.api.SignalError`
        """
        params = {
            "verificationCode": verification_code,
        }
        if pin:  # pragma: no cover
            params.update({"pin": pin})
        return await self._jsonrpc(method="verify", params=params, **kwargs)

    async def get_recipients(self, recipients: list):
        """
        Get recipients. Could be either a valid recipient
        registered with the network or a group.

        Args:
            recipients (list): List of recipients

        Returns:
            result (tuple): Tuple of `(unknown, contacts, groups)`
        """
        unknown = []
        contacts = []
        groups = []
        check_registered = []
        for recipient in recipients:
            if j_search(f"[?id==`{recipient}`]", await self.list_groups()):  # pragma: no cover
                groups.append(recipient)
                continue
            if re_search("[a-zA-Z/=]", recipient):  # pragma: no cover
                unknown.append(recipient)
                continue
            check_registered.append(recipient)
        if check_registered:
            registered = await self.get_user_status(recipients=check_registered)
        for recipient in check_registered:
            if j_search(f"[?number==`{recipient}`]", registered):
                contacts.append(recipient)
                continue
            unknown.append(recipient)  # pragma: no cover
        return (unknown, contacts, groups)
