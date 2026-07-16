import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models import Notification, User, UserSettings
from routes.notifications import (
    NotificationPreferencesUpdate,
    add_notification,
    get_notification_preferences,
    update_preferences,
)


class NotificationPreferenceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.owner = User(username="owner", nickname="作品作者", password="")
        self.actor = User(username="actor", nickname="互动用户", password="")
        self.db.add_all([self.owner, self.actor])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_preferences_default_to_enabled(self):
        preferences = get_notification_preferences(self.db, self.owner.id)
        self.assertTrue(all(preferences.values()))
        self.assertIn("complaint_reply", preferences)

    def test_disabled_type_is_not_created_and_existing_unread_is_cleared(self):
        self.db.add(Notification(
            user_id=self.owner.id,
            from_user_id=self.actor.id,
            type="like",
            content="旧点赞提醒",
        ))
        self.db.commit()

        result = update_preferences(NotificationPreferencesUpdate(
            user_id=self.owner.id,
            preferences={"like": False},
        ), self.db)
        self.assertFalse(result["preferences"]["like"])
        self.assertTrue(self.db.query(Notification).one().is_read)

        add_notification(
            self.db,
            user_id=self.owner.id,
            from_user_id=self.actor.id,
            type="like",
            content="新点赞提醒",
        )
        self.assertEqual(self.db.query(Notification).count(), 1)
        settings = self.db.query(UserSettings).filter_by(user_id=self.owner.id).one()
        self.assertIn('"like": false', settings.notification_preferences)


if __name__ == "__main__":
    unittest.main()
