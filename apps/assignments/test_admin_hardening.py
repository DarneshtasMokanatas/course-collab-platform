from django.contrib import admin
from django.test import SimpleTestCase

from .admin import AssignmentAdmin, GradeRevisionAdmin, SubmissionAdmin
from .models import Assignment, GradeRevision, Submission


class AcademicHistoryAdminHardeningTests(SimpleTestCase):
    def test_submission_and_grade_history_cannot_be_mutated_in_admin(self):
        request = object()
        submission_admin = SubmissionAdmin(Submission, admin.site)
        grade_admin = GradeRevisionAdmin(GradeRevision, admin.site)
        assignment_admin = AssignmentAdmin(Assignment, admin.site)
        for model_admin in (assignment_admin, submission_admin, grade_admin):
            self.assertFalse(model_admin.has_add_permission(request))
            self.assertFalse(model_admin.has_change_permission(request))
            self.assertFalse(model_admin.has_delete_permission(request))
