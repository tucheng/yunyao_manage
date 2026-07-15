import unittest

from routes.works import _sanitize_work_images


class WorkImageHandlingTests(unittest.TestCase):
    def test_uses_uploaded_image_when_primary_is_blob(self):
        primary, images = _sanitize_work_images(
            "blob:http://127.0.0.1:5173/temporary",
            [
                "blob:http://127.0.0.1:5173/temporary",
                "/uploads/works/persisted.png",
            ],
        )

        self.assertEqual(primary, "/uploads/works/persisted.png")
        self.assertEqual(images, ["/uploads/works/persisted.png"])

    def test_preserves_durable_primary_and_deduplicates(self):
        primary, images = _sanitize_work_images(
            "https://cdn.example.com/works/cover.webp",
            [
                "https://cdn.example.com/works/cover.webp",
                "/media/works/detail.jpg",
            ],
        )

        self.assertEqual(primary, "https://cdn.example.com/works/cover.webp")
        self.assertEqual(
            images,
            [
                "https://cdn.example.com/works/cover.webp",
                "/media/works/detail.jpg",
            ],
        )

    def test_rejects_only_temporary_images(self):
        self.assertEqual(
            _sanitize_work_images(
                "blob:http://localhost/temp",
                ["data:image/png;base64,abc"],
            ),
            ("", []),
        )


if __name__ == "__main__":
    unittest.main()
