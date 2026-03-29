#!/usr/bin/env python3
"""Dev server with no-cache headers."""
import http.server, functools, os

class NoCacheHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        super().end_headers()

os.chdir(os.path.dirname(os.path.abspath(__file__)))
server = http.server.HTTPServer(('', 8081), NoCacheHandler)
print('Serving on http://localhost:8081 (no-cache)')
server.serve_forever()
