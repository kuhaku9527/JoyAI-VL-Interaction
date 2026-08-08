from http.server import BaseHTTPRequestHandler, HTTPServer


class R(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status":"fake-listener-on-8996"}')

    def log_message(self, *a):
        pass


HTTPServer(("127.0.0.1", 8996), R).serve_forever()
