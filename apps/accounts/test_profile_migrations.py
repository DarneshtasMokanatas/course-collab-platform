from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class CollaborationProfileMigrationTests(TransactionTestCase):
    migrate_from = ("accounts", "0001_initial")
    migrate_to = ("accounts", "0002_collaboration_profiles")

    def setUp(self):
        super().setUp()
        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_from])
        old_apps = executor.loader.project_state([self.migrate_from]).apps
        user_model = old_apps.get_model("accounts", "User")
        self.student_id = user_model.objects.create(
            username="existing.student",
            email="existing.student@example.test",
            display_name="Existing Student",
            role="STUDENT",
            password="unused",
        ).id
        self.instructor_id = user_model.objects.create(
            username="existing.instructor",
            email="existing.instructor@example.test",
            display_name="Existing Instructor",
            role="INSTRUCTOR",
            password="unused",
        ).id

        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_to])
        self.apps = executor.loader.project_state([self.migrate_to]).apps

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def test_existing_students_receive_one_default_profile(self):
        profile_model = self.apps.get_model("accounts", "StudentCollaborationProfile")

        self.assertEqual(
            profile_model.objects.filter(user_id=self.student_id).count(),
            1,
        )
        profile = profile_model.objects.get(user_id=self.student_id)
        self.assertEqual(profile.collaboration_mode, "ONLINE")
        self.assertEqual(profile.availability, "")
        self.assertFalse(
            profile_model.objects.filter(user_id=self.instructor_id).exists()
        )
