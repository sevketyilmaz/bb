#!/usr/bin/env python

r"""
>>> commands["shell_push"]("1 + 6")
'7\n>>> '
"""

# {1: func_1, 2: func_2, ...}
processes = {}

instructions_list = [
    "ping",
    "pong",
    "type",
]

# {"ping": 1, "pong": 2, ...}
instructions = dict(zip(instructions_list, range(1, 2**16)))


def handle(func):
    assert callable(func), func
    alias = func.__name__
    assert alias in instructions, alias
    signal = instructions[alias]
    assert signal not in processes, "%s:%d" % (alias, signal)
    processes[signal] = func
    return func


import gc
from bb.i import I, P
from bb.bd import BackdoorShell
from bb.oc import record, recorder
from bb.util import list_to_tuple

recorder.clear()
shell = BackdoorShell()

def _beginner(i):
    if isinstance(i, int) and i not in P:
        P[i] = I(i)
    else:
        return i  # send back if error

commands = {
    "shell": lambda line: shell.push(line),
    "status": lambda _: record() or dict(recorder),
    "gc": lambda _: gc.collect(),
    "beginner": lambda args: _beginner(int(args[0])),
    "render": lambda r: P[1].apply(P[1].render(list_to_tuple(r)), "from web")
}



if __name__ == "__main__":
    print("doctest:")
    import doctest
    doctest.testmod()
