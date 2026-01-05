import unittest
from unittest.mock import MagicMock
from deepdir.core.waf import WAF

class TestWAF(unittest.TestCase):
    def test_cloudflare_detection(self):
        response = MagicMock()
        response.headers = {"server": "cloudflare"}
        response.content = "Attention Required! Cloudflare"
        
        result = WAF.analyze(response)
        self.assertTrue(result["waf_present"])
        self.assertIn("Cloudflare", result["source"])

    def test_aws_detection(self):
        response = MagicMock()
        response.headers = {"x-amzn-errortype": "ForbiddenException"}
        response.content = ""
        
        result = WAF.analyze(response)
        self.assertTrue(result["waf_present"])
        self.assertIn("AWS", result["source"])

    def test_no_waf(self):
        response = MagicMock()
        response.headers = {"server": "apache"}
        response.content = "Hello World"
        
        result = WAF.analyze(response)
        self.assertFalse(result["waf_present"])

if __name__ == '__main__':
    unittest.main()
