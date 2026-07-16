import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models import Complaint, ComplaintReply, User
from fastapi import HTTPException

from routes.complaints import _sanitize_complaint_images, serialize_complaint


class ComplaintWorkflowTests(unittest.TestCase):
    def test_only_uploaded_complaint_images_are_accepted(self):
        self.assertEqual(
            _sanitize_complaint_images("private://complaints/a.png,private://complaints/b.jpg"),
            "private://complaints/a.png,private://complaints/b.jpg",
        )
        with self.assertRaises(HTTPException):
            _sanitize_complaint_images("/media/yunyao-uploads/misc/a.png")
        with self.assertRaises(HTTPException):
            _sanitize_complaint_images("javascript:alert(1)\" onerror=\"alert(1)")

    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.owner = User(username="owner", nickname="提问人", password="", is_admin=False)
        self.admin = User(username="admin", nickname="客服", password="", is_admin=True)
        self.db.add_all([self.owner, self.admin])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_serializes_multiple_replies_and_workflow_statuses(self):
        complaint = Complaint(
            user_id=self.owner.id,
            content="第一次反馈",
            is_resolved=False,
            is_closed=True,
        )
        self.db.add(complaint)
        self.db.commit()
        self.db.add_all([
            ComplaintReply(complaint_id=complaint.id, admin_id=self.admin.id, content="第一次答复"),
            ComplaintReply(complaint_id=complaint.id, admin_id=self.admin.id, content="补充答复"),
        ])
        self.db.commit()

        result = serialize_complaint(complaint, self.db, include_user=True)

        self.assertTrue(result["is_answered"])
        self.assertFalse(result["is_resolved"])
        self.assertTrue(result["is_closed"])
        self.assertEqual([reply["content"] for reply in result["replies"]], ["第一次答复", "补充答复"])
        self.assertEqual(result["user"]["nickname"], "提问人")

    def test_keeps_legacy_reply_visible(self):
        complaint = Complaint(
            user_id=self.owner.id,
            content="旧反馈",
            reply="旧版单条回复",
            admin_id=self.admin.id,
        )
        self.db.add(complaint)
        self.db.commit()

        result = serialize_complaint(complaint, self.db)

        self.assertTrue(result["is_answered"])
        self.assertEqual(len(result["replies"]), 1)
        self.assertEqual(result["replies"][0]["content"], "旧版单条回复")



if __name__ == "__main__":
    unittest.main()
