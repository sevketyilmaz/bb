#!/usr/bin/env python3

import logging

import tornado.httpclient
import tornado.ioloop
import tornado.web
import tornado.options

from tencent import mk_url

args = [
    "openid",
    "openkey",
    "pf",
]

class MainHandler(tornado.web.RequestHandler):
    @tornado.web.asynchronous
    def get(self):
        http = tornado.httpclient.AsyncHTTPClient()
        url = mk_url(
            {k: self.get_argument(k) for k in args},
            "v3/user/get_info"
            )
        http.fetch(url, self.on_response)

    def on_response(self, response):
        if response.error:
            logging.warning(response)
            raise tornado.web.HTTPError(500)
        print(response.body.decode())
        self.finish()

application = tornado.web.Application([
    (r"/", MainHandler),
])

if __name__ == "__main__":
    application.listen(1024)
    tornado.ioloop.IOLoop.instance().start()