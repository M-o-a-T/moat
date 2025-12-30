"""
This module contains a heap of somewhat-random helper functions
and classes which are used throughout MoaT (and beyond)
but don't get their own package because they're too small,
or too interrelated … or the author was too lazy.
"""
# TODO split this up

# pylint: disable=cyclic-import,wrong-import-position
from __future__ import annotations

import logging as _logging

_log = _logging.getLogger(__name__)

NotGiven = Ellipsis

# Mapping of exported names to their source modules
_imports = {
    # impl
    "Cache": "impl",
    "NoLock": "impl",
    "NoneType": "impl",
    "OptCtx": "impl",
    "TimeOnlyFormatter": "impl",
    "acount": "impl",
    "byte2num": "impl",
    "count": "impl",
    "digits": "impl",
    "import_": "impl",
    "load_from_cfg": "impl",
    "num2byte": "impl",
    "num2id": "impl",
    "singleton": "impl",
    "split_arg": "impl",
    # dict
    "combine_dict": "dict",
    "drop_dict": "dict",
    "to_attrdict": "dict",
    "attrdict": "dict",
    # merge
    "merge": "_merge",
    # misc
    "OutOfData": "misc",
    "_add_obj": "misc",
    "get_codec": "misc",
    "pos2val": "misc",
    "srepr": "misc",
    "val2pos": "misc",
    # pp
    "pop_kw": "pp",
    "push_kw": "pp",
    # random
    "al_ascii": "random",
    "al_az": "random",
    "al_lower": "random",
    "al_unique": "random",
    "gen_ident": "random",
    "id2str": "random",
    # inexact
    "InexactFloat": "inexact",
    # event
    "ValueEvent": "event",
    # ctx
    "CtxObj": "ctx",
    "ctx_as": "ctx",
    "timed_ctx": "ctx",
    # queue
    "DelayedRead": "queue",
    "DelayedWrite": "queue",
    "Lockstep": "queue",
    "Queue": "queue",
    "QueueEmpty": "queue",
    "QueueFull": "queue",
    "create_queue": "queue",
    # module
    "Module": "module",
    "make_module": "module",
    "make_proc": "module",
    # msg
    "MsgReader": "msg",
    "MsgWriter": "msg",
    # msgpack
    "StdMsgpack": "msgpack",
    "std_ext": "msgpack",
    # path
    "PS": "path",
    "P": "path",
    "Path": "path",
    "PathElem": "path",
    "PathElemI": "path",
    "PathLongener": "path",
    "PathShortener": "path",
    "Root": "path",
    "RootPath": "path",
    "logger_for": "path",
    "path_eval": "path",
    "set_root": "path",
    "P_Root": "path",
    "Q_Root": "path",
    "S_Root": "path",
    # server
    "gen_ssl": "server",
    "run_tcp_server": "server",
    # spawn
    "spawn": "spawn",
    # systemd
    "as_service": "systemd",
    # yaml
    "add_repr": "yaml",
    "load_ansible_repr": "yaml",
    "yaml_parse": "yaml",
    "yaml_repr": "yaml",
    "yformat": "yaml",
    "yload": "yaml",
    "yprint": "yaml",
    # exc
    "ExpAttrError": "exc",
    "ExpKeyError": "exc",
    "ExpectedError": "exc",
    "exc_iter": "exc",
    "ungroup": "exc",
}

__all__ = list(_imports.keys())


def __getattr__(attr: str):
    try:
        mod = _imports[attr]
    except KeyError:
        raise AttributeError(attr) from None
    value = getattr(__import__(mod, globals(), None, True, 1), attr)
    globals()[attr] = value
    return value

def __dir__():
    return __all__
