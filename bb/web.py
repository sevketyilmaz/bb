#!/usr/bin/env python
# This is bb server
"""
   /--->Q0--->\
Web            Hub --->Q2---> Log
   \<---Q1<---/

"""


def main(port, backstage):
    import gc
    gc.disable()

    import logging
    from multiprocessing import Process
    from multiprocessing.queues import Queue, SimpleQueue
    Q0, Q1, Q2 = Queue(), SimpleQueue(), SimpleQueue()

    from imp import reload

    import bb.hub
    import bb.log

    sub_procs = {}

    def start():
        for proc in sub_procs.values():
            if proc.is_alive():
                logging.warning("process:%d is running, failed to start",
                                proc.pid)
                return
        logging.info("starting sub processes...")
        reload(bb.hub)
        reload(bb.log)
        sub_procs["hub"] = Process(target=bb.hub.hub, args=(Q0, Q1, Q2))
        sub_procs["log"] = Process(target=bb.log.log, args=(Q2,))
        for name, proc in sub_procs.items():
            proc.start()
            logging.info("%s started, pid:%d", name, proc.pid)
        logging.info("start sub processes success!")

    def stop():
        logging.info("stopping sub processes...")
        Q0.put(None)
        for name, proc in sub_procs.items():
            proc.join()
            logging.info("%s stopped, pid:%s", name, proc.pid)
        logging.info("stop sub processes success!")

    start()

    # main from here
    import time
    import weakref
    from struct import pack, unpack

    staffs = weakref.WeakValueDictionary()

    from tornado import ioloop
    from tornado.tcpserver import TCPServer
    io_loop = ioloop.IOLoop.instance()

    class Connection(object):
        def __init__(self, stream, address):
            self.stream = stream
            self.address = address
            #self.stream.read_bytes(1, self.msg_byte)
            #self.stream.read_until(b'\n', self.msg_print)
            self.stream.read_until(b'\n', self.login)
            logging.info("%s try in", address)

        def login(self, auth):
            i = int(auth)
            if i in range(10):   # lots todo :)
                self.i = i
                staffs[i] = self
                self.stream.set_close_callback(self.logout)
                self.stream.read_bytes(4, self.msg_head)
                logging.info("%s %s login", self.address, i)
            else:
                logging.warning("failed to auth %s %s", self.address, i)
                self.stream.close()

        def msg_byte(self, byte):
            self.stream.write(byte)
            self.stream.read_bytes(1, self.msg_byte)

        def msg_print(self, chunk):
            logging.info(chunk)
            self.stream.read_until(b'\n', self.msg_print)

        def msg_head(self, chunk):
            #logging.info("head: %s", chunk)
            instruction, length_of_body = unpack("!HH", chunk)
            #logging.info("%d, %d", instruction, length_of_body)
            self.instruction = instruction
            if not self.stream.closed():
                self.stream.read_bytes(length_of_body, self.msg_body)

        def msg_body(self, chunk):
            #logging.info("body: %s", chunk)
            if not chunk:
                chunk = b'0'
            Q0.put([self.i, self.instruction, chunk])
            if not self.stream.closed():
                self.stream.read_bytes(4, self.msg_head)

        def logout(self):
            self.stream.close()
            logging.info("%s %s logout", self.address, self.i)


    class BBServer(TCPServer):
        def handle_stream(self, stream, address):
            Connection(stream, address)

    # SIGTERM
    import signal
    def term(signal_number, stack_frame):
        logging.info("will exit")
        io_loop.stop()
        stop()
    signal.signal(signal.SIGTERM, term)

    def msg(fd, event):
        i, cmd, data = Q1.get()
        if i in staffs:
            stream = staffs[i].stream
            if not stream.closed():
                stream.write(data)
        else:
            logging.warning("%s is not online, failed to send %s %s",
                            i, cmd, data)
    io_loop.add_handler(Q1._reader.fileno(), msg, io_loop.READ)

    server = BBServer()
    server.listen(port)

    # web interface
    from bb.oc import record, recorder
    from tornado.web import RequestHandler, Application

    ioloop.PeriodicCallback(record, 3000).start()

    class MainHandler(RequestHandler):
        def get(self):
            self.render("stat.html", recorder=recorder, staffs=staffs)

    class GcHandler(RequestHandler):
        def get(self):
            gc.collect()
            self.redirect("/")

    class ReloadHandler(RequestHandler):
        def get(self):
            stop()
            start()
            self.redirect("/")

    Application([
        (r"/", MainHandler),
        (r"/gc", GcHandler),
        (r"/reload", ReloadHandler),
    ]).listen(backstage)

    gc.collect()
    io_loop.start()   # looping...

    logging.info("bye")



if __name__ == "__main__":
    from tornado.options import define, options, parse_command_line
    define("port", default=8000, type=int, help="main port(TCP)")
    define("backstage", default=8100, type=int, help="backstage port(HTTP)")
    define("leader", default="localhost:80", type=str, help="central controller")
    parse_command_line()

    main(options.port, options.backstage)
