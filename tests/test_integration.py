import unittest
import threading
import http.server
import socketserver
import time
import requests
from deepdir.connection.requester import Requester
from deepdir.core.data import options

PORT = 8888

class MockHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/admin":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Admin Panel")
        elif self.path == "/403":
            self.send_response(403)
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

class TestIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = socketserver.TCPServer(("localhost", PORT), MockHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever)
        cls.thread.daemon = True
        cls.thread.start()
        time.sleep(1) # Wait for server to start

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        options.timeout = 1
        options.max_retries = 0
        options.proxies = []
        options.headers = {}
        options.http_method = "GET"
        options.follow_redirects = False
        options.bypass_waf = False
        options.auth = None
        options.data = None
        options.random_agents = False
        options.cert_file = None
        options.key_file = None
        options.network_interface = None
        options.proxy_auth = None
        options.max_rate = 0
        options.thread_count = 1

    def test_requester_hit(self):
        requester = Requester()
        requester.set_url(f"http://localhost:{PORT}/")
        
        response = requester.request("admin")
        self.assertEqual(response.status, 200)
        self.assertIn("Admin Panel", response.content)

    def test_requester_403(self):
        requester = Requester()
        requester.set_url(f"http://localhost:{PORT}/")
        
        response = requester.request("403")
        self.assertEqual(response.status, 403)

if __name__ == '__main__':
    unittest.main()
