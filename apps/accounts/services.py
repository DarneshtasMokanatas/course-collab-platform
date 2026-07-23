from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction

from apps.courses.models import Course, Enrolment

from .models import Skill, StudentCollaborationProfile, User


def can_view_collaboration_profile(*, actor, target):
    if target.role != User.Role.STUDENT:
        return False
    if actor.id == target.id or actor.is_staff:
        return True
    active_courses = Enrolment.objects.filter(
        student=target,
        status=Enrolment.Status.ACTIVE,
    ).exclude(course__status=Course.Status.ARCHIVED)
    if actor.role == User.Role.STUDENT:
        return active_courses.filter(
            course__enrolments__student=actor,
            course__enrolments__status=Enrolment.Status.ACTIVE,
        ).exists()
    if actor.role == User.Role.INSTRUCTOR:
        return active_courses.filter(course__instructor=actor).exists()
    return False


def create_student_collaboration_profile(*, user):
    if user.role != User.Role.STUDENT:
        raise ValidationError("Only students have collaboration profiles.")
    profile = StudentCollaborationProfile(user=user)
    profile.full_clean()
    profile.save()
    return profile


def _resolve_new_skill(name):
    existing = Skill.objects.filter(name__iexact=name).first()
    if existing is not None:
        return existing
    try:
        with transaction.atomic():
            skill = Skill(name=name)
            skill.full_clean()
            skill.save()
            return skill
    except IntegrityError:
        return Skill.objects.get(name__iexact=name)


def update_collaboration_profile(
    *,
    actor,
    profile,
    collaboration_mode,
    availability,
    selected_skills,
    new_skill_names,
):
    if actor.role != User.Role.STUDENT or actor.id != profile.user_id:
        raise PermissionDenied("You may edit only your own collaboration profile.")
    with transaction.atomic():
        profile = (
            StudentCollaborationProfile.objects.select_for_update()
            .select_related("user")
            .get(pk=profile.pk)
        )
        if actor.id != profile.user_id:
            raise PermissionDenied("You may edit only your own collaboration profile.")
        profile.collaboration_mode = collaboration_mode
        profile.availability = availability
        profile.full_clean()
        profile.save(update_fields=["collaboration_mode", "availability", "updated_at"])
        skills_by_id = {skill.id: skill for skill in selected_skills}
        for name in new_skill_names:
            skill = _resolve_new_skill(name)
            skills_by_id[skill.id] = skill
        if len(skills_by_id) > 25:
            raise ValidationError("Choose no more than 25 skills for one profile.")
        profile.skills.set(skills_by_id.values())
    return profile
