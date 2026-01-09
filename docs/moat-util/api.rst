API
===

.. automodule:: moat.util
   :members:
   :exclude-members: al_unique al_lower al_ascii al_az
   :show-inheritance:

.. autoclass:: moat.util.msg._MsgRW

.. py:data:: moat.util.al_unique

   An alphabet intended to be unambiguous: both cases, no special characters, no vowels.

.. py:data:: moat.util.al_lower

   Lowercase letters and digits, e.g. for restricted-alphabet labels.

.. py:data:: moat.util.al_ascii

   All printable ASCII characters (except for backslash, just to be safe).

.. py:data:: moat.util.al_az

   Lowercase letters.

.. autoclass:: moat.util.server._Server
