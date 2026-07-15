from django.core.exceptions import PermissionDenied
from django.db import transaction

from .models import Course, Enrolment


def enrol_student(*, actor, course):
    if actor.role != actor.Role.STUDENT:
        raise PermissionDenied("Student access is required.")
    with transaction.atomic():
        course = Course.objects.select_for_update().get(pk=course.pk)
        if (
            course.status != Course.Status.PUBLISHED
            or course.enrolment_mode != Course.EnrolmentMode.OPEN
        ):
            raise PermissionDenied("This course is not open for enrolment.")
        enrolment = (
            Enrolment.objects.select_for_update()
            .filter(course=course, student=actor)
            .first()
        )
        if enrolment is None:
            enrolment = Enrolment.objects.create(course=course, student=actor)
        elif enrolment.status == Enrolment.Status.WITHDRAWN:
            enrolment.status = Enrolment.Status.ACTIVE
            enrolment.withdrawn_at = None
            enrolment.save(update_fields=["status", "withdrawn_at"])
    return enrolment
