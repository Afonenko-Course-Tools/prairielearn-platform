"""Synthetic upstream used only by the opt-in proxy integration test."""
import base64
import hashlib
import http.server
import json
class Probe(http.server.BaseHTTPRequestHandler):
    protocol_version='HTTP/1.1'
    def do_GET(self):
        if self.headers.get('Upgrade','').lower()=='websocket':
            key=self.headers.get('Sec-WebSocket-Key','')
            accept=base64.b64encode(hashlib.sha1((key+'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()
            self.send_response(101);self.send_header('Upgrade','websocket');self.send_header('Connection','Upgrade');self.send_header('Sec-WebSocket-Accept',accept);self.end_headers();self.close_connection=True
            return
        body=json.dumps({'path':self.path,'headers':dict(self.headers)}).encode()
        self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    def log_message(self,*args):pass
http.server.ThreadingHTTPServer(('0.0.0.0',3000),Probe).serve_forever()
