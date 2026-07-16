import asyncio
import unittest

import app_config
from services.business_errors import QuotaExceeded


class QuotaResponseContractTests(unittest.TestCase):
    def test_quota_rejection_keeps_frontend_detail_and_adds_business_code(self):
        # Importing the application must not try to open the developer's live
        # rotating log file while the test suite is running.
        app_config.LOG_TO_FILE = False
        from main import quota_exceeded_handler

        response = asyncio.run(quota_exceeded_handler(
            None,
            QuotaExceeded("recipe", "今天发布配方的额度已用完！"),
        ))

        self.assertEqual(403, response.status_code)
        self.assertEqual(
            {
                "detail": "今天发布配方的额度已用完！",
                "code": "QUOTA_EXHAUSTED",
                "quota_kind": "recipe",
                "remaining": 0,
            },
            __import__("json").loads(response.body),
        )


if __name__ == "__main__":
    unittest.main()
