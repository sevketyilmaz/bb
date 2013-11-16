#!/usr/bin/env python3
# This is bb server
"""
   /--->Q0--->\
Web            Hub --->Q2---> Log
   \<---Q1<---/

"""


def main(port, backstage, backdoor, options):
    import gc
    gc.disable()

    import logging
    from multiprocessing import Process
    from multiprocessing.queues import Queue, SimpleQueue

    debug = options.debug
    if debug:
        from threading import Thread as Process
        from redis import StrictRedis
        debug_db = StrictRedis(decode_responses=True)  # local redis
        from datetime import timedelta
        delay = timedelta(milliseconds=options.delay)

    Q0, Q1, Q2 = Queue(), SimpleQueue(), SimpleQueue()

    put = Q0.put
    get = Q1.get

    import bb.hub
    import bb.log

    sub_procs = {}

    def start():
        logging.info("starting sub processes...")
        if any(proc.is_alive() for proc in sub_procs.values()):
            logging.warning("sub processes are running, failed to start")
            return
        sub_procs["hub"] = Process(target=bb.hub.hub, args=(Q0, Q1, Q2, debug))
        sub_procs["log"] = Process(target=bb.log.log, args=(Q2, debug))
        for name, proc in sub_procs.items():
            proc.start()
            logging.info("%s started, pid:%d", name, getattr(proc, "pid", 0))
        logging.info("start sub processes success!")

    def stop():
        logging.info("stopping sub processes...")
        if all(proc.is_alive() for proc in sub_procs.values()):
            put(None)
        else:
            logging.warning("sub processes are not running, failed to stop")
        for name, proc in sub_procs.items():
            proc.join()
            logging.info("%s stopped, pid:%d", name, getattr(proc, "pid", 0))
        logging.info("stop sub processes success!")

    start()

    # main from here
    import time
    import weakref
    from functools import partial

    staffs = weakref.WeakValueDictionary()
    wheels = weakref.WeakValueDictionary()

    from tornado import ioloop
    io_loop = ioloop.IOLoop.instance()

    tokens = {}


    # SIGTERM
    import signal
    def term(signal_number, stack_frame):
        logging.info("will exit")
        io_loop.stop()
        stop()
    signal.signal(signal.SIGTERM, term)


    commands = {
        "shell": lambda s: [i.write(s.encode()) for i in wheels.values()],
    }

    def msg(fd, event):
        x = get()
        logging.debug("msg from hub: %r", x)
        if len(x) == 2:
            cmd, data = x
            cb = commands.get(cmd) or (HC[cmd].popleft() if HC[cmd] else None)
            #print(cmd, data, cb)
            cb(data) if cb else None
        else:
            i, cmd, data = x
            s = staffs.get(i)
            if s:
                s.send(cmd, data) if not debug else io_loop.add_timeout(delay, partial(s.send, cmd, data))
            else:
                logging.warning("%s is not online, failed to send %s %s",
                                i, cmd, data)
    io_loop.add_handler(Q1._reader.fileno(), msg, io_loop.READ)


    from bb.oc import record, recorder
    from tornado.web import RequestHandler, Application, asynchronous

    ioloop.PeriodicCallback(record, 3000).start()
    ioloop.PeriodicCallback(lambda: tokens.update(
        {1: "token", 2: "token", 3: "token"}
        ), 2000).start()

    class BaseHandler(RequestHandler):
        STEP = 25

        @property
        def browser(self):
            return self.request.host[0].isalpha()

        def get(self):
            """dummy"""

    import collections
    HC = collections.defaultdict(collections.deque)  # http commands


    class MainHandler(BaseHandler):
        commands = {
            "gc": lambda: gc.collect(),
            "HUB-RST": lambda: [gc.collect(), stop(), start()],
            "door-close": lambda: [i.close() for i in wheels.values()],
        }

        def get(self):
            """
            curl "localhost:8100/?cmd=gc"
            """
            cmd = self.get_argument("cmd", None)
            if cmd:
                logging.info("main_commands: %s", cmd)
                self.commands[cmd]()
            if self.browser:
                self.render("index.html",
                            qsize=Q0.qsize(),
                            wheels=wheels,
                            staffs=staffs)


    class HubHandler(BaseHandler):
        commands = {
            "status": lambda d: StatusHandler.recorders["hub"].update(d),
            "gc": lambda n: logging.info("hub gc collect return: %d", n),
            "beginner": lambda i: logging.info("begin %d", i),
            "amend": lambda args: logging.info("amend %d %s %r %r", *args),
            "run": lambda f: logging.info("run %s succeed" % f),
            "view_data": lambda x: logging.info("%r " % x),
            "view_logs": lambda x: logging.info("%r " % x),
        }

        history = collections.deque(maxlen=3)

        def _get(self):
            if self.browser:
                self.render("hub.html")
            else:
                self.finish()

        @asynchronous
        def get(self):
            """
            curl "localhost:8100/hub?cmd=gc"
            curl "localhost:8100/hub?cmd=beginner&args=42"
            """
            cmd = self.get_argument("cmd", None)
            if cmd:
                args = self.get_arguments("args")
                logging.info("hub_commands: %s, %s", cmd, args)
                t = time.strftime("%H:%M:%S")
                self.history.appendleft([t, cmd, args, None])
                put([cmd, args])
                HC[cmd].append(partial(self.deal_echoed, cmd))
            else:
                self._get()

        def deal_echoed(self, cmd, echo):
            self.history[0][-1] = echo
            if isinstance(echo, str) and echo.startswith("Traceback"):
                self.set_header("Content-Type", "text/plain")
                self.write(echo)
                self.finish()
            else:
                self.commands[cmd](echo)
                self._get()


    class IOHistoryHandler(BaseHandler):
        def get(self):
            if debug:
                page = int(self.get_argument("page", 1))
                s = self.STEP
                io = self.request.path.lstrip("/")
                pages = int((debug_db.llen(io) - 1) / s) + 1
                history = debug_db.lrange(io, s * (page - 1), s * page - 1)
                self.render("history.html",
                            io=io,
                            page=page,
                            pages=pages,
                            history=history)

    class CleanIOHistoryHandler(BaseHandler):
        def get(self, page=None):
            if debug:
                page = int(self.get_argument("page", 0))
                s = self.STEP
                io = self.request.path.partition("_")[2]
                if page:
                    debug_db.ltrim(io, s * (page - 1), -1)
                else:
                    debug_db.delete(io)
                self.redirect("/%s" % io)


    class StatusHandler(BaseHandler):
        recorders = {"web": recorder, "hub": {}, "log": {}}
        def get(self, key):
            self.render("status.html")


    class TokenUpdateHandler(BaseHandler):
        def get(self):
            """
            curl "localhost:8100/t?_=1&_=key"
            """
            i, t = self.get_arguments("_")
            logging.info("token_generation: %s, %r", i, t)
            tokens[int(i)] = t

    class ViewHubHandler(BaseHandler):
        @asynchronous
        def get(self, path):
            """
            curl "localhost:8100/view"
            curl "localhost:8100/view/bb.i/P?a=1"
            curl "localhost:8100/view/gc/isenabled?c="
            """
            path = list(filter(None, path.split("/")))
            logging.debug(path)
            attr = self.get_argument("a", None)
            call = self.get_argument("c", None)
            self._path = path[-1] if path else "view"
            put(["view", [path, attr, call]])
            HC["view"].append(self.deal_echoed)

        def deal_echoed(self, echo):
            if isinstance(echo, str) and echo.startswith("Traceback"):
                self.set_header("Content-Type", "text/plain")
                self.write(echo)
                self.finish()
            else:
                self.render("view.html", data=echo)

    from bb import conn

    conn.tcp(staffs, put, )().listen(port)
    conn.backdoor(wheels, put)().listen(backdoor)

    from tornado import autoreload
    #autoreload.start = lambda: None  # monkey patch, i don't like autoreload
    autoreload.add_reload_hook(stop)  # i like autoreload now :)

    Application([
        (r"/dummy", BaseHandler),
        (r"/", MainHandler),
        (r"/t", TokenUpdateHandler),
        (r"/hub", HubHandler),
        (r"/io", IOHistoryHandler),
        (r"/lo", IOHistoryHandler),
        (r"/clean_io", CleanIOHistoryHandler),
        (r"/clean_lo", CleanIOHistoryHandler),
        (r"/(.*)_status", StatusHandler),
        (r"/view(.*)", ViewHubHandler),
        (r"/ws", conn.websocket(staffs, put, )),
    ], static_path="_", template_path="tpl", debug=debug).listen(backstage)


    import os
    pid = "bb.pid"
    with open(pid, "w") as f: f.write(str(os.getpid()))

    gc.collect()
    io_loop.start()   # looping...

    logging.info("bye")
    if os.path.exists(pid): os.remove(pid)

