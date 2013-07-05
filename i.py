#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import division, print_function, unicode_literals


import collections
import sys


# map looks like this:
#    {"func_name": func, ...}
# why prefer "func_name" mapping instead of use function directly:
#   * reload functions at running
#   * persist this "function-link" at shutdown
#   * easy to read
_cbs = {}

def register_log_callback(callback):
    name = callback.__name__
    assert name not in _cbs, name
    _cbs[name] = callback
    return callback

class I(dict):
    """
    >>> i = I(42, {"a": 1, "b": 3})
    >>> i.i
    42
    >>> i["a"]
    1
    >>> i["b"]
    3
    >>> i["foo"]
    5
    >>> a = i["foobar"]
    >>> b = i["foobar"]
    >>> id(a) == id(b)
    True
    >>> i.logs.append("over")
    >>> #i.listeners["foo"].add("bar")
    >>> i.bind("go", callback_example, 1)
    >>> i.listeners["go"] == set([("callback_example", (1,))])
    True
    >>> i.unbind("go", "callback_example", 1)
    >>> i.listeners["go"] == set()
    True
    >>> i.bind("go", callback_example, 1, 2, 3)
    >>> i.bind("go", callback_example2)
    >>> i.listeners["go"] == set([("callback_example", (1, 2, 3)), ("callback_example2", ())])
    True
    >>> i.log("go")
    >>> len(i.cache)
    5
    >>> i.listeners["go"] == set([("callback_example2", ())])
    True

    >>> i.bind("gogogo", callback_example)
    >>> i.bind("gogogogo", callback_example)
    >>> len(i.listeners)
    3
    >>> check(i, "tower", compile("i.a > 1", "<string>", "eval"), {"i": i}, f, "gogo")
    >>> len(i.listeners["gogo"])  # daemon launched
    1
    >>> i["a"] = 1
    >>> i.log("gogo")  # "i["a"] > 1" is False, daemon is watching
    >>> len(i.listeners["gogo"])
    1
    >>> i["a"] = 2
    >>> i.log("gogo")
    >>> len(i.listeners["gogo"])  # daemon quited
    0

    """

    __slots__ = ["_i", "_cache", "_logs", "_listeners"]

    def __init__(self, n, source=None):
        self._i = int(n)
        self._cache = []
        self._logs = collections.deque(maxlen=100)
        self._listeners = collections.defaultdict(set)
        if source is not None:
            assert isinstance(source, dict)
            for k, v in source.items():
                wrap = getattr(self, "_wrap_%s" % k, None)
                self[k] = wrap(v) if wrap else v

    def __missing__(self, k):
        self[k] = self.__getattribute__("_default_" + k)
        return self[k]

    def __getattr__(self, k):   # use this prudently
        return self[k]

    # i, cache, logs, listeners are protected and readonly
    @property
    def i(self):
        return self._i

    @property
    def cache(self):
        return self._cache

    @property
    def logs(self):
        return self._logs

    @property
    def listeners(self):
        return self._listeners

    def bind(self, log, cb, *args):
        if callable(cb):
            cb = cb.__name__
        assert cb in _cbs, cb
        assert isinstance(log, str), log
        cb_args = cb, args
        self.listeners[log].add(cb_args)

    def unbind(self, log, cb, *args):
        if callable(cb):
            cb = cb.__name__
        assert cb in _cbs, cb
        assert isinstance(log, str), log
        all_cb_args = self.listeners[log]
        cb_args = cb, args
        if cb_args in all_cb_args:
            all_cb_args.remove(cb_args)

    def send(self, k, v):
        self.cache.append(["save", self.i, k, v])

    def log(self, k, infos=None, n=1):
        self.cache.append(["log", self.i, k, infos, n])
        self.logs.append([k, infos, n])
        all_cb_args = self.listeners[k]
        for cb_args in list(all_cb_args):
            _cbs[cb_args[0]](self, k, infos, n, *cb_args[1])

    def save(self, k):
        self.cache.append(["save", self.i, k, self[k]])

    @property
    def _default_foo(self):
        return 5

    @property
    def _default_bar(self):
        return list()

    @property
    def _default_foobar(self):
        return collections.Counter()

    @staticmethod
    def _wrap_foobar(raw):
        return collections.Counter(
            {int(k) if k.isdigit() else k: v for k, v in raw.items()}
            )



# examples here:
@register_log_callback
def callback_example(i, k, infos, n, *args):
    i.unbind(k, callback_example, *args)
    # or:
    #   i.unbind(k, "callback_example")
    #   i.unbind(k, callback_example.__name__)
    i.save("foo")
    i.send("msg", "haha")

@register_log_callback
def callback_example2(i, k, infos, n, *args):
    i.save("foobar")
    i.save("a")


def check(i, key, evaluation, env, callback, k):
    daemon = "%s_daemon" % key
    if eval(evaluation, None, env):
        callback(key)
        i.unbind(k, daemon, evaluation, callback)
    else:
        i.bind(k, daemon, evaluation, callback)


def f(func_name):
    print(func_name, "--> ok", file=sys.stderr)

@register_log_callback
def tower_daemon(i, k, infos, n, evaluation, callback):
    #print(evaluation, callback, file=sys.stderr)
    check(i, "tower", evaluation, None, callback, k)


if __name__ == "__main__":
    print("doctest:")
    import doctest
    doctest.testmod()
