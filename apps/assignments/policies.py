from dataclasses import dataclass

from apps.accounts.models import User

from .models import Assignment

NON_MEMBER_RESUBMISSION_LIMIT = 2
NON_MEMBER_MAX_VERSION = NON_MEMBER_RESUBMISSION_LIMIT + 1


@dataclass(frozen=True, slots=True)
class ResubmissionPolicy:
    is_member: bool
    allowance_message: str
    current_version_number: int | None
    resubmissions_used: int
    resubmissions_remaining: int | None
    limit_reached: bool
    can_resubmit: bool
    blocked_message: str | None


def _current_version_number(submission):
    if submission is None:
        return None
    prefetched = getattr(submission, "_prefetched_objects_cache", {}).get("versions")
    if prefetched is not None:
        return max(
            (version.version_number for version in prefetched),
            default=None,
        )
    return (
        submission.versions.order_by("-version_number")
        .values_list("version_number", flat=True)
        .first()
    )


def resubmission_policy(*, user, assignment, submission, now):
    current_version_number = _current_version_number(submission)
    resubmissions_used = max((current_version_number or 1) - 1, 0)
    is_member = user.membership_status == User.MembershipStatus.MEMBER
    remaining = (
        None
        if is_member
        else max(NON_MEMBER_RESUBMISSION_LIMIT - resubmissions_used, 0)
    )
    limit_reached = not is_member and remaining == 0
    blocked_message = None
    if submission is None or current_version_number is None:
        blocked_message = "Submit an initial version before resubmitting."
    elif assignment.status != Assignment.Status.PUBLISHED:
        blocked_message = "This assignment is not accepting submissions."
    elif not assignment.allow_resubmission:
        blocked_message = "Resubmission is not enabled for this assignment."
    elif now >= assignment.due_at:
        blocked_message = (
            "The resubmission deadline has passed. "
            "Resubmissions must be received before the deadline."
        )
    elif limit_reached:
        blocked_message = "You have reached the non-member limit of 2 resubmissions."
    return ResubmissionPolicy(
        is_member=is_member,
        allowance_message=(
            "Unlimited resubmissions before the deadline."
            if is_member
            else "2 resubmissions allowed."
        ),
        current_version_number=current_version_number,
        resubmissions_used=resubmissions_used,
        resubmissions_remaining=remaining,
        limit_reached=limit_reached,
        can_resubmit=blocked_message is None,
        blocked_message=blocked_message,
    )
