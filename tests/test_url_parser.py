import unittest
from deepdir.parse.url import clean_path, parse_path

class TestUrlParser(unittest.TestCase):
    def test_clean_path(self):
        self.assertEqual(clean_path("/admin//dashboard"), "/admin/dashboard")
        self.assertEqual(clean_path("admin/"), "admin/")
        
    def test_parse_path(self):
        self.assertEqual(parse_path("http://example.com/admin"), "/admin")
        self.assertEqual(parse_path("http://example.com/admin?q=1"), "/admin?q=1")

if __name__ == '__main__':
    unittest.main()
