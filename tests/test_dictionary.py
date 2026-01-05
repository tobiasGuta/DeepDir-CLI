import unittest
import tempfile
import os
from deepdir.core.dictionary import Dictionary
from deepdir.core.data import options

class TestDictionary(unittest.TestCase):
    def setUp(self):
        self.test_file = tempfile.NamedTemporaryFile(delete=False, mode='w')
        self.test_file.write("admin\nuser\n%EXT%\n")
        self.test_file.close()
        
        # Reset options
        options.extensions = ("php", "html")
        options.prefixes = ()
        options.suffixes = ()
        options.lowercase = False
        options.uppercase = False
        options.capitalization = False
        options.force_extensions = False
        options.overwrite_extensions = False
        options.exclude_extensions = ()

    def tearDown(self):
        os.unlink(self.test_file.name)

    def test_generate_basic(self):
        dictionary = Dictionary(files=[self.test_file.name])
        items = list(dictionary)
        
        self.assertIn("admin", items)
        self.assertIn("user", items)
        # %EXT% should be replaced
        self.assertIn("php", items)
        self.assertIn("html", items)
        self.assertNotIn("%EXT%", items)

    def test_force_extensions(self):
        options.force_extensions = True
        dictionary = Dictionary(files=[self.test_file.name])
        items = list(dictionary)
        
        self.assertIn("admin.php", items)
        self.assertIn("admin.html", items)
        self.assertIn("admin/", items)

    def test_prefixes_suffixes(self):
        options.prefixes = ("pre_",)
        options.suffixes = ("_suf",)
        
        dictionary = Dictionary(files=[self.test_file.name])
        items = list(dictionary)
        
        self.assertIn("pre_admin", items)
        self.assertIn("admin_suf", items)

if __name__ == '__main__':
    unittest.main()
