from django.contrib import admin
from django.test import SimpleTestCase

from .admin import MaterialAdmin, MaterialVersionAdmin
from .models import Material, MaterialVersion


class MaterialHistoryAdminHardeningTests(SimpleTestCase):
    def test_material_versions_cannot_be_mutated_in_admin(self):
        request = object()
        for model_admin in (
            MaterialAdmin(Material, admin.site),
            MaterialVersionAdmin(MaterialVersion, admin.site),
        ):
            self.assertFalse(model_admin.has_add_permission(request))
            self.assertFalse(model_admin.has_change_permission(request))
            self.assertFalse(model_admin.has_delete_permission(request))
