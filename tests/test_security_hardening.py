import json
import unittest
from io import BytesIO

from cryptography.fernet import Fernet
from PIL import Image

import security
from image_security import _normalize_image


class EncryptionRotationTests(unittest.TestCase):
    def setUp(self):
        self.original = (
            security.ENCRYPTION_KEYS,
            security.ENCRYPTION_ACTIVE_KEY_ID,
            security.PERSONAL_DATA_ENCRYPTION_KEY,
            security.RECIPE_ENCRYPT_KEY,
            security.ENCRYPTION_KEY_FILE,
        )
        self.old_key = Fernet.generate_key().decode()
        self.new_key = Fernet.generate_key().decode()
        security.ENCRYPTION_KEYS = json.dumps({"old": self.old_key, "new": self.new_key})
        security.ENCRYPTION_ACTIVE_KEY_ID = "new"
        security.PERSONAL_DATA_ENCRYPTION_KEY = ""
        security.RECIPE_ENCRYPT_KEY = ""
        security.ENCRYPTION_KEY_FILE = ""
        security._keyring.cache_clear()

    def tearDown(self):
        (
            security.ENCRYPTION_KEYS,
            security.ENCRYPTION_ACTIVE_KEY_ID,
            security.PERSONAL_DATA_ENCRYPTION_KEY,
            security.RECIPE_ENCRYPT_KEY,
            security.ENCRYPTION_KEY_FILE,
        ) = self.original
        security._keyring.cache_clear()

    def test_ciphertext_has_version_and_key_id(self):
        encrypted = security.encrypt("云窑")
        self.assertTrue(encrypted.startswith("enc:v1:new:"))
        self.assertEqual(security.decrypt(encrypted), "云窑")

    def test_old_key_can_be_rotated(self):
        legacy = Fernet(self.old_key.encode()).encrypt("旧数据".encode()).decode()
        rotated = security.rotate(legacy)
        self.assertTrue(rotated.startswith("enc:v1:new:"))
        self.assertEqual(security.decrypt(rotated), "旧数据")

    def test_invalid_ciphertext_is_never_returned_as_plaintext(self):
        with self.assertRaises(security.EncryptionError):
            security.decrypt("gAAAA-invalid-token")

    def test_explicit_legacy_plaintext_compatibility(self):
        self.assertEqual(
            security.decrypt("卡斯特长石", allow_plaintext=True),
            "卡斯特长石",
        )
        with self.assertRaises(security.EncryptionError):
            security.decrypt("gAAAA-invalid-token", allow_plaintext=True)


class ImageNormalizationTests(unittest.TestCase):
    def test_reencoding_discards_trailing_payload_and_metadata(self):
        source = BytesIO()
        Image.new("RGB", (20, 20), "red").save(source, "JPEG", exif=b"Exif\x00\x00test")
        dirty = source.getvalue() + b"<script>unexpected payload</script>"
        clean, extension, content_type = _normalize_image(dirty, {"JPEG"}, 4096)
        self.assertEqual(extension, ".jpg")
        self.assertEqual(content_type, "image/jpeg")
        self.assertNotIn(b"unexpected payload", clean)
        with Image.open(BytesIO(clean)) as image:
            self.assertEqual(image.size, (20, 20))
            self.assertFalse(image.getexif())


if __name__ == "__main__":
    unittest.main()
