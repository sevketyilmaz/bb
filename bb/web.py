#!/usr/bin/env python
# This is bb server
"""
   /--->Q0--->\
Web            Hub --->Q2---> Log
   \<---Q1<---/

"""


def main(port, backstage, backdoor, web_debug=0):
    import gc
    gc.disable()

    import logging
    from multiprocessing import Process
    from multiprocessing.queues import Queue, SimpleQueue
    Q0, Q1, Q2 = Queue(), SimpleQueue(), SimpleQueue()

    import bb.hub
    import bb.log

    sub_procs = {}

    def start():
        if web_debug:
            return
        logging.info("starting sub processes...")
        if any(proc.is_alive() for proc in sub_procs.values()):
            logging.warning("sub processes are running, failed to start")
            return
        sub_procs["hub"] = Process(target=bb.hub.hub, args=(Q0, Q1, Q2))
        sub_procs["log"] = Process(target=bb.log.log, args=(Q2,))
        for name, proc in sub_procs.items():
            proc.start()
            logging.info("%s started, pid:%d", name, proc.pid)
        logging.info("start sub processes success!")

    def stop():
        logging.info("stopping sub processes...")
        if all(proc.is_alive() for proc in sub_procs.values()):
            Q0.put(None)
        else:
            logging.warning("sub processes are not running, failed to stop")
        for name, proc in sub_procs.items():
            proc.join()
            logging.info("%s stopped, pid:%s", name, proc.pid)
        logging.info("stop sub processes success!")

    start()

    # main from here
    import time
    import weakref
    from struct import pack, unpack
    from json import dumps, loads

    staffs = weakref.WeakValueDictionary()
    wheels = weakref.WeakValueDictionary()
    wss = weakref.WeakValueDictionary()

    from tornado import ioloop
    from tornado.tcpserver import TCPServer
    io_loop = ioloop.IOLoop.instance()

    tokens = {1: "token"}
    class Connection(object):
        def __init__(self, stream, address):
            self.stream = stream
            self.address = address
            self.stream.read_until(b'\n', self.login)
            logging.info("%s try in", address)

        def login(self, auth):
            """format: id token\n
            token can be generated by visit //bb/t?it=1&it=token
            """
            try:
                i, k = auth.split()
                i = int(i)
                k = k.decode()
                t = tokens.pop(i)
                if k != t:
                    raise Warning("error token: %s != %s" % (k, t))
                self.i = i
                if i in staffs:
                    staffs[i].close()
                    logging.info("tcp kick %s", i)
                staffs[i] = self.stream
                self.stream.set_close_callback(self.logout)
                self.stream.read_bytes(4, self.msg_head)
                logging.info("%s %s login", self.address, i)
            except Exception as e:
                self.stream.close()
                logging.error("failed to auth: %s: %s", type(e).__name__, e)

        def msg_head(self, chunk):
            logging.debug("head: %s", chunk)
            instruction, length_of_body = unpack("!HH", chunk)
            logging.debug("%d, %d", instruction, length_of_body)
            self.instruction = instruction
            if not self.stream.closed():
                self.stream.read_bytes(length_of_body, self.msg_body)

        def msg_body(self, chunk):
            logging.debug("body: %s", chunk)
            Q0.put([self.i, self.instruction, chunk.decode() or "0"])
            if not self.stream.closed():
                self.stream.read_bytes(4, self.msg_head)

        def logout(self):
            self.stream.close()
            Q0.put([self.i, 4, "false"])  # see inst.py, "online" is 4
            logging.info("%s %s logout", self.address, self.i)

    class BBServer(TCPServer):
        def handle_stream(self, stream, address):
            Connection(stream, address)
    BBServer().listen(port)

    # SIGTERM
    import signal
    def term(signal_number, stack_frame):
        logging.info("will exit")
        io_loop.stop()
        stop()
    if not web_debug:
        signal.signal(signal.SIGTERM, term)


    commands = {
        "shell": lambda s: [i.write(s.encode()) for i in wheels.values()],
    }

    def msg(fd, event):
        x = Q1.get()
        if len(x) == 2:
            cmd, data = x
            cb = commands.get(cmd) or (HC[cmd].popleft() if HC[cmd] else None)
            #print(cmd, data, cb)
            cb(data) if cb else None
        else:
            i, cmd, data = x
            stream = staffs.get(i)  # ws use `stream` too, for compatible
            if stream:
                if hasattr(stream, "write_message"):  # ws
                    stream.write_message(data)
                elif not stream.closed():  # tcp
                    stream.write(data.encode())
            else:
                logging.warning("%s is not online, failed to send %s %s",
                                i, cmd, data)
    io_loop.add_handler(Q1._reader.fileno(), msg, io_loop.READ)

    class BackdoorConnection(object):
        def __init__(self, stream, address):
            self.stream = stream
            wheels[address] = stream
            self.stream.set_close_callback(self.stream.close)
            self.stream.write(b"Backdoor\n>>> ")
            self.stream.read_until(b'\n', self.handle_input)

        def handle_input(self, line):
            Q0.put(["shell", line.decode()])
            self.stream.read_until(b'\n', self.handle_input)

    class BackdoorServer(TCPServer):
        def handle_stream(self, stream, address):
            BackdoorConnection(stream, address)
    BackdoorServer().listen(backdoor)

    from bb.oc import record, recorder
    from tornado.web import RequestHandler, Application, StaticFileHandler, \
                            asynchronous

    ioloop.PeriodicCallback(record, 3000).start()

    class BaseHandler(RequestHandler):
        def back(self):
            if self.request.host[0].isalpha():
                self.redirect("")

    import collections
    HC = collections.defaultdict(collections.deque)  # http commands

    from functools import partial

    class MainHandler(BaseHandler):
        commands = {
            "": lambda: None,
            "gc": lambda: gc.collect(),
            "HUB-RST": lambda: [gc.collect(), stop(), start()],
            "door-close": lambda: [i.close() for i in wheels.values()],
        }

        def get(self):
            self.render("index.html",
                        qsize=Q0.qsize(),
                        options=self.commands,
                        wheels=wheels,
                        staffs=staffs)

        def post(self):
            """example:
            wget -O - localhost:8100 --post-data="cmd=gc"
            """
            cmd = self.get_argument("cmd", None)
            if cmd:
                logging.info("main_commands: %s", cmd)
                self.commands[cmd]()
            self.back()


    class HubHandler(BaseHandler):
        commands = {
            "": None,
            "status": lambda d: StatusHandler.recorders["hub"].update(d),
            "gc": lambda n: logging.info("hub gc collect return: %d", n),
            "beginner": lambda i: logging.info("beginner error: %d", i) if i else i,
            "amend": lambda args: logging.info("amend %d %s %r %r", *args),
            "run": lambda f: logging.info("run %s succeed" % f),
        }

        def get(self):
            self.render("hub.html", options=self.commands)

        @asynchronous
        def post(self):
            """example:
            wget -O - localhost:8100/hub --post-data="cmd=gc"
            wget -O - localhost:8100/hub --post-data="cmd=status"
            wget -O - localhost:8100/hub --post-data="cmd=beginner&args=42"
            wget -O - localhost:8100/hub --post-data='cmd=amend&args=1&args=foobar&args={"1":1,"2":2}'
            wget -O - localhost:8100/hub --post-data="cmd=run&args=plus"
            """
            cmd = self.get_argument("cmd", None)
            args = self.get_arguments("args")
            if cmd:
                logging.info("hub_commands: %s, %s", cmd, args)
                Q0.put([cmd, args])
                HC[cmd].append(partial(self.deal_echo, cmd))
            else:
                self.back()

        def deal_echo(self, cmd, data):
            self.commands[cmd](data)
            self.back()


    class StatusHandler(BaseHandler):
        recorders = {"web": recorder, "hub": {}, "log": {}}
        def get(self, key):
            self.render("status.html", recorder=self.recorders[key])


    class TokenUpdateHandler(BaseHandler):
        def get(self):
            """example:
            wget -O - "localhost:8100/t?_=1&_=key"
            """
            i, t = self.get_arguments("_")
            logging.info("token_generation: %s, %r", i, t)
            tokens[int(i)] = t


    Application([
        (r"/", MainHandler),
        (r"/t", TokenUpdateHandler),
        (r"/hub", HubHandler),
        (r"/(.*)_status", StatusHandler),
    ], static_path="_", debug=web_debug).listen(backstage)

    from tornado.websocket import WebSocketHandler

    class WebSocket(WebSocketHandler):
        def open(self):
            print(id(self))

        def on_close(self):
            i = self.i
            logging.info("%s %s logout", "ws", i)
            if staffs.get(i) is self:  # have to do it (without gc enable)
                staffs.pop(i)

        def on_message(self, message):
            inst, msg = loads(message)
            try:
                Q0.put([self.i, inst, msg or "0"])
            except AttributeError:  # has no attribute `i`
                i = int(msg)
                if i in range(10):  # lots todo :)
                    self.i = i
                    if i in staffs:
                        staffs[i].close()
                        logging.info("ws kick %s", i)
                    staffs[i] = self
                    logging.info("%s %s login", "ws", i)
                else:
                    logging.warning("failed to auth %s %s", "ws", i)
                    self.close()

    Application([
        (r"/ws", WebSocket),
    ]).listen(port + 50)


    import os
    pid = "bb.pid"
    with open(pid, "w") as f: f.write(str(os.getpid()))

    gc.collect()
    io_loop.start()   # looping...

    logging.info("bye")
    if os.path.exists(pid): os.remove(pid)




if __name__ == "__main__":
    from tornado.options import define, options, parse_command_line
    define("port", default=8000, type=int, help="main port(TCP)")
    define("backstage", default=8100, type=int, help="backstage port(HTTP)")
    define("backdoor", default=8200, type=int, help="backdoor port(TCP)")
    define("leader", default="localhost:80", type=str, help="central controller")
    parse_command_line()

    main(options.port, options.backstage, options.backdoor)
