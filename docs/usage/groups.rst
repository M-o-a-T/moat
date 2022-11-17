Groups
======

You can create or update groups using :meth:`.update_group`.

   .. code-block:: python

      signal_cli_rest_api.update_group(
          name="Test Group",
          members=["memberA", "memberB"],
      )

Avatar
------

You can set/update a group avatar using `avatar` parameter.

`avatar` is a `bytearray` containing image data which can be created like this from file:

   .. code-block:: python

      with open("image-from-disk.png", "rb") as f:
          avatar = f.read()

If you want to use an remote image file, you can leverage `requests`:

   .. code-block:: python

      import requests

      session = requests.Session()
      response = session.get(
          "https://robohash.org/YBQ.png?set=set1&size=150x150",
          stream=True
      )
      response.raise_for_status()
      avatar = bytearray()
      for chunk in response.iter_content(1024):
          avatar.extend(chunk)

Now the resulting `avatar` can be used:

   .. code-block:: python

      signal_cli_rest_api.update_group(
          name="Test Group",
          members=["memberA", "memberB"],
          avatar=avatar,
      )
