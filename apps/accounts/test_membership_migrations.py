from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class MembershipMigrationTests(TransactionTestCase):
    migrate_from = ("accounts", "0002_collaboration_profiles")
    migrate_to = ("accounts", "0003_membership_status")

    def setUp(self):
        super().setUp()
        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_from])
        old_apps = executor.loader.project_state([self.migrate_from]).apps
        user_model = old_apps.get_model("accounts", "User")
        self.user_id = user_model.objects.create(
            username="existing.membership.user",
            email="existing.membership.user@example.test",
            display_name="Existing Membership User",
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

    def test_existing_users_default_to_non_member(self):
        user_model = self.apps.get_model("accounts", "User")

        user = user_model.objects.get(pk=self.user_id)
        self.assertEqual(user.membership_status, "NON_MEMBER")
