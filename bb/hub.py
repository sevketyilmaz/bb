#!/usr/bin/env python3

"""
>>> import queue
>>> q0 = queue.Queue()
>>> q1 = queue.Queue()
>>> q2 = queue.Queue()
>>> q0.put([1, 0, "0"])
>>> q0.put(None)
>>> hub(q0, q1, q2)

>>> q1.get() == [1, 0, "0"]
True
>>> q2.get() is None 
True

>>> q0.qsize(), q1.qsize(), q2.qsize()
(0, 0, 0)

"""


def hub(Q_in, Q_out, Q_err):
    import functools
    import logging
    import sys
    import traceback

    _in = Q_in.get
    _out = Q_out.put
    _err = Q_err.put

    try:
        from .i import P
        from .msg import loads, dumps
        from .const import INSTRUCTIONS, PING, DEBUG_OUTPUT
        from .exc import exc_map, exc_recorder
        from .inst import processes, commands
        from .srv import load_data, build_all, check_all, import_others
        import this
        this
    except Exception:
        logging.exception("init error")
        _out(None)
        _err(None)
        return

    if __debug__:
        from time import strftime
        _log_file = open(DEBUG_OUTPUT, "w", 1)
        def _log(io_type, value):
            print(strftime("%H:%M:%S"), io_type, value, file=_log_file)

        def _in():
            v = Q_in.get()
            _log("I", v)
            return v
        def _out(v):
            _log("O", v)
            Q_out.put(v)
        def _err(v):
            _log("E", v)
            Q_err.put(v)

    while True:
        try:
            v = _in()
        except Exception as e:
            logging.error(e)
            continue

        if v is None:
            logging.info("hub exit")
            _err(None)
            break

        try:
            i, cmd, data = v
            if i is None:
                try:
                    output = commands[cmd](data)
                except Exception:
                    output = traceback.format_exc()
                    logging.exception(v)
                _out([None, cmd, output])   # echo cmd and result(or error)
            else:
                #cmd, data = loads(data)
                #cmd, data = INSTRUCTIONS[cmd], dumps(data)
                producer = processes[cmd]
                try:
                    if producer:
                        outs = producer(P[i], loads(data))
                    else:
                        raise NotImplementedError(cmd)
                except Exception:
                    err = sys.exc_info()[0].__name__
                    _out([i, PING, dumps(exc_map.get(err, 0))])
                    exc_recorder[i][err] += 1
                    raise
                if outs:
                    for x in outs:
                        if isinstance(x[0], int):
                            i, cmd, data = x
                            #cmd, data = "ping", [cmd, data]
                            _out([i, INSTRUCTIONS[cmd], dumps(data)])
                        else:
                            _err(x)
        except Exception:
            logging.exception(v)



if __name__ == "__main__":
    print("doctest:")
    import doctest
    doctest.testmod()
