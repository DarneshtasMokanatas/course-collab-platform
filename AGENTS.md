# Course Collaboration Platform - Repository Instructions

This file is the implementation contract for the Course Collaboration Platform described in `Vertex_XBAU2114N_1stSub_Jan26.pdf`. All coding agents and developers must read this file before changing the project.

The objective is a reliable academic course workspace for two roles: students and instructors. It centralizes course setup, enrolment, learning materials, announcements, assignments, submissions, resubmissions, grading, and participation monitoring.

The system must remain easy to understand, easy to demonstrate, and realistic for a three-person student team. Prefer boring, well-supported technology and database constraints over clever abstractions.

## 1. Non-negotiable product principles

1. The assignment requirements in this file are the product source of truth.
2. Build a modular monolith, not microservices.
3. Use one server-rendered web application. Do not add a separate React/Vue frontend or a public REST API unless a new requirement makes one necessary.
4. Use PostgreSQL from the first migration. Do not design against SQLite and switch later.
5. Create the custom user model before the first migration.
6. Store uploaded file bytes outside PostgreSQL. Store authoritative file metadata, versions, ownership, hashes, and timestamps in PostgreSQL.
7. Never overwrite or delete a historical material or submission version during normal use. The newest version is displayed as current, but history stays immutable.
8. Treat authorization as a server-side rule. Hiding a button is not authorization.
9. Use database constraints for invariants that PostgreSQL can enforce.
10. Keep derived dashboards query-based. Do not add caches, background queues, Redis, or search services for the initial system.
11. Announcements are a durable database-backed feed. WebSockets are not required by the functional requirements. Add real-time delivery only if a later requirement explicitly demands live push behavior.
12. Use UTC in the database. Display dates in `Asia/Kuala_Lumpur`.
13. Every feature must include validation, permission tests, happy-path tests, and important failure-path tests.
14. Do not add speculative features such as chat, video calls, plagiarism detection, AI grading, attendance scanning, payment, or institution-wide administration.

## 2. Product scope

### 2.1 Student capabilities

- FR-STU-01: Register and authenticate securely.
- FR-STU-02: Browse courses that are published and open for enrolment, then enrol.
- FR-STU-03: View and download the latest published learning material while retaining access to its version history where allowed.
- FR-STU-04: View assignment requirements and deadlines, upload a submission, receive a server-generated timestamp, and see its status.
- FR-STU-05: Resubmit before the deadline when resubmission is enabled. Each resubmission becomes a new immutable version.
- FR-STU-06: Read course announcements in one chronological feed.
- Dashboard: See enrolled courses, unread/recent announcements, upcoming deadlines, submission states, and released grades.

### 2.2 Instructor capabilities

- FR-INS-01: Create and configure a course, syllabus, and ordered weekly/topic sections.
- FR-INS-02: Create material entries and upload new material versions.
- FR-INS-03: Create, edit, pin, publish, and archive course announcements.
- FR-INS-04: Create and manage assignments and their submission rules.
- FR-INS-05: Review submission versions and record/release grades and feedback.
- FR-INS-06: Monitor enrolment, platform activity, submission status, lateness, and released results.
- Dashboard: See owned courses, enrolment totals, assignments needing grading, late/missing submissions, and recently inactive students.

### 2.3 Explicit non-goals for the first release

- No direct messaging or group chat.
- No email, SMS, or push-notification integration.
- No live video or conferencing.
- No collaborative document editing.
- No external Google Drive or OneDrive integration.
- No plagiarism checker.
- No automatic grading.
- No mobile application; the website must be responsive instead.
- No multi-tenant institution hierarchy.
- No complex role/permission builder.
- No Kubernetes, message broker, Redis, Celery, or microservices.
- No WebSocket infrastructure for a feed that works correctly with normal HTTP.

### 2.4 Week 8 collaboration and membership requirement change

Student collaboration profiles extend the accounts domain without adding messaging,
matching, endorsements, proficiency rankings, or scheduling infrastructure.

- Every student has one collaboration profile.
- A profile records exactly one preferred collaboration mode: `ONLINE` or `OFFLINE`.
- Availability is optional, validated text with a maximum length of 300 characters.
- Skills are reusable normalized rows with UUID primary keys and case-insensitively
  unique names. Profiles use an explicit unique profile-to-skill relationship.
- Students may view and edit their own profile. Staff may view profiles for
  maintenance. Another student may view a profile only while both students have
  active enrolments in the same non-archived course. An instructor may view an
  actively enrolled student's profile only for a non-archived course they own.
- Public collaboration profile pages show only display name, skills, collaboration
  mode, and availability. They never expose email, authentication, membership, or
  enrolment-administration data.

Membership is a separate account classification controlled through trusted staff
administration. Its initial values are `NON_MEMBER` and `MEMBER`; existing and new
users default to `NON_MEMBER`. Actual membership changes create append-only audit
events. Ordinary account and profile forms never accept membership state. No
payment, billing, renewal, checkout, or subscription platform is in scope.

For resubmissions, version 1 is the initial submission and does not consume a
resubmission. A `NON_MEMBER` may create at most two resubmissions, so versions 1,
2, and 3 are accepted and version 4 is rejected. A `MEMBER` has no count ceiling,
but membership never bypasses publication status, active enrolment, ownership,
upload validation, `allow_resubmission`, or the strict `now < due_at` rule.
Existing histories above version 3 remain immutable; a non-member with such a
history cannot add another version. Enforce the count under the submission row
lock before saving uploaded bytes.

## 3. Architecture decision

### 3.1 Selected stack

- Operating environment: WSL2, preferably Ubuntu.
- Language: Python 3.13.
- Dependency and virtual-environment manager: `uv` with committed `pyproject.toml` and `uv.lock`.
- Web framework: Django 5.2 LTS, pinned to the latest compatible 5.2 patch release.
- Database: PostgreSQL 18 in Docker Compose. PostgreSQL 17 is acceptable when the team's local Docker installation cannot run 18, but all developers must use the same major version.
- Database driver: `psycopg` 3.
- HTML rendering: Django templates.
- Browser behavior: small, local vanilla JavaScript modules only where HTML alone is insufficient.
- Styling: project-owned CSS. Do not introduce a Node build pipeline for the initial release.
- Local infrastructure: Docker Compose for PostgreSQL only. Running Django directly through `uv` gives the simplest debugging loop in WSL.
- Production process: Gunicorn or another supported WSGI server behind a reverse proxy. This is a deployment detail and must not leak into domain code.
- Tests: Django's built-in test framework and PostgreSQL test database.
- Formatting/linting: Ruff.

### 3.2 Why this architecture

Django is a good fit because authentication, authorization primitives, CSRF protection, forms, migrations, an ORM, server-rendered pages, file-upload handling, and an administrative interface are available in one maintained framework. Django 5.2 is an LTS release and therefore favors stability over adopting the newest feature release.

A single Django application avoids duplicated validation and types across a frontend and backend. PostgreSQL provides durable relational constraints for enrolment, file versioning, submissions, and grades. `uv` provides a reproducible lockfile and a consistent WSL setup.

### 3.3 Architecture boundaries

Use a modular monolith with these Django apps:

```text
config/             Django settings, root URLs, WSGI/ASGI
apps/
  accounts/         custom User, registration, authentication, role guards
  courses/          Course, CourseSection, Enrolment, course pages
  announcements/    Announcement, AnnouncementRead, feed
  materials/        Material, MaterialVersion, protected downloads
  assignments/      Assignment, Submission, SubmissionVersion, GradeRevision
  analytics/        ActivityEvent and instructor/student dashboard queries
  audit/            append-only AuditEvent and helpers
templates/          shared and app templates
static/             project CSS, icons, and small JavaScript modules
media/              development uploads only; never commit
tests/              optional cross-app integration tests
```

Models stay in the app that owns the data. Cross-app workflows belong in explicit service functions, not signals. Signals are allowed only for framework-adjacent actions that cannot be expressed clearly in the calling workflow.

Use this request flow:

```text
browser -> Django URL/view -> form validation -> domain service -> ORM transaction
        -> PostgreSQL + file storage -> template response/redirect
```

## 4. Roles and authorization

### 4.1 Account roles

`User.role` has exactly these application values:

- `STUDENT`
- `INSTRUCTOR`

Use Django's `is_staff` and `is_superuser` only for maintenance/admin access. They are not course roles.

The first migration must contain the custom user model. Do not change `AUTH_USER_MODEL` after migrations have been shared.

### 4.2 Permission matrix

| Action | Anonymous | Student | Course instructor | Staff admin |
| --- | --- | --- | --- | --- |
| Register/login | Yes | Yes | Yes | Yes |
| Browse published open courses | No | Yes | Optional read-only | Yes |
| Enrol in a course | No | Yes | No | Yes |
| View course content | No | Enrolled only | Owned course only | Yes |
| Download published material | No | Enrolled only | Owned course only | Yes |
| Create/edit course | No | No | Own course only | Yes |
| Upload material/version | No | No | Own course only | Yes |
| Read announcements | No | Enrolled only | Own course only | Yes |
| Publish announcements | No | No | Own course only | Yes |
| Submit/resubmit | No | Enrolled student only | No | No by default |
| View a student's submission | No | Own submission only | Owned course only | Yes |
| Grade/release feedback | No | No | Owned course only | Yes |
| View participation dashboard | No | No | Owned course only | Yes |

Always load the parent course before authorizing a nested resource. Never trust a course ID, user ID, or object ID supplied by the browser.

## 5. Database design

### 5.1 General conventions

- Use UUID primary keys for all domain tables exposed in URLs.
- Use Django's normal internal primary keys for framework tables.
- Every mutable domain row has `created_at` and `updated_at` using timezone-aware timestamps.
- Immutable event/version rows have `created_at` or a more specific event timestamp and no `updated_at`.
- Foreign keys must declare intentional `on_delete` behavior.
- Prefer `PROTECT` for referenced academic records and version history.
- Use `CASCADE` only for data that has no meaning without its parent and is safe to remove before the parent is used operationally.
- Production records are archived rather than hard-deleted.
- Name constraints and indexes explicitly.
- Use `TextChoices` for finite states and validate transitions in domain services.
- Do not store comma-separated relationships.
- Do not store file bytes in PostgreSQL.
- Do not use JSON for core relationships or fields that need relational constraints. JSON is acceptable only for small event metadata and validated configuration lists.

### 5.2 `accounts_user`

Custom model based on `AbstractUser`.

| Column | Type | Rules |
| --- | --- | --- |
| `id` | UUID | Primary key, generated server-side |
| `username` | varchar | Required, unique, normalized |
| `email` | varchar | Required, case-insensitively unique |
| `role` | varchar | `STUDENT` or `INSTRUCTOR` |
| `display_name` | varchar | Required, trimmed |
| `is_active` | boolean | Defaults true |
| framework fields | standard | Password hash, staff flags, last login, date joined |

Rules:

- Login accepts either username or email through one small authentication backend.
- Passwords are handled only by Django password hashers and validators.
- Never log passwords, raw session tokens, or password reset tokens.
- Changing a user role after the user owns courses or has enrolments is an administrative operation and must be rejected unless the related records are resolved.

### 5.3 `courses_course`

| Column | Type | Rules |
| --- | --- | --- |
| `id` | UUID | Primary key |
| `code` | varchar(32) | Required, stored uppercase, unique |
| `slug` | varchar | Required, unique, stable after publication |
| `title` | varchar(200) | Required |
| `description` | text | Required |
| `syllabus` | text | Optional |
| `instructor_id` | FK User | Required; referenced user must be an instructor |
| `status` | varchar | `DRAFT`, `PUBLISHED`, `ARCHIVED` |
| `enrolment_mode` | varchar | `OPEN` or `CLOSED` for initial release |
| `created_at` | timestamptz | Required |
| `updated_at` | timestamptz | Required |

Indexes and rules:

- Unique constraint on normalized `code`.
- Index on `(status, enrolment_mode)` for course browsing.
- Index on `(instructor_id, status)` for the instructor dashboard.
- Only a published course can be shown in the student catalogue.
- Only a published and open course accepts self-enrolment.
- Archive instead of deleting a course that has enrolments, uploads, assignments, or activity.

### 5.4 `courses_coursesection`

Represents a week or topic inside a course.

| Column | Type | Rules |
| --- | --- | --- |
| `id` | UUID | Primary key |
| `course_id` | FK Course | Required |
| `title` | varchar(200) | Required |
| `description` | text | Optional |
| `position` | positive integer | Required |
| timestamps | timestamptz | Required |

Constraints:

- Unique `(course_id, position)`.
- Check `position >= 1`.
- Default ordering is `(course_id, position)`.
- Reordering must run in one transaction to avoid duplicate positions.

### 5.5 `courses_enrolment`

| Column | Type | Rules |
| --- | --- | --- |
| `id` | UUID | Primary key |
| `course_id` | FK Course | Required |
| `student_id` | FK User | Required; user must be a student |
| `status` | varchar | `ACTIVE`, `WITHDRAWN` |
| `enrolled_at` | timestamptz | Server-generated |
| `withdrawn_at` | timestamptz | Nullable |

Constraints and indexes:

- Unique `(course_id, student_id)` so repeated clicks cannot create duplicate enrolments.
- Index `(student_id, status)` for the student dashboard.
- Index `(course_id, status)` for instructor rosters.
- A withdrawn record is reactivated rather than duplicated if re-enrolment is allowed.
- Enrolment creation must lock/check the course in a transaction and verify that it is published and open.

### 5.6 `announcements_announcement`

| Column | Type | Rules |
| --- | --- | --- |
| `id` | UUID | Primary key |
| `course_id` | FK Course | Required |
| `author_id` | FK User | Required |
| `title` | varchar(200) | Required |
| `body` | text | Required |
| `is_pinned` | boolean | Defaults false |
| `status` | varchar | `DRAFT`, `PUBLISHED`, `ARCHIVED` |
| `published_at` | timestamptz | Required only when published |
| timestamps | timestamptz | Required |

Indexes:

- `(course_id, status, published_at DESC)` for the course feed.
- `(course_id, is_pinned, published_at DESC)` for pinned-first display.

Only published announcements appear to students. Editing a published announcement updates `updated_at` and creates an audit event.

### 5.7 `announcements_announcementread`

| Column | Type | Rules |
| --- | --- | --- |
| `id` | UUID | Primary key |
| `announcement_id` | FK Announcement | Required |
| `student_id` | FK User | Required |
| `read_at` | timestamptz | Server-generated |

Constraint: unique `(announcement_id, student_id)`. Marking an item read is idempotent.

### 5.8 `materials_material`

A material is a logical resource such as "Week 2 Slides". Versions contain physical files.

| Column | Type | Rules |
| --- | --- | --- |
| `id` | UUID | Primary key |
| `course_id` | FK Course | Required |
| `section_id` | nullable FK CourseSection | Must belong to same course |
| `title` | varchar(200) | Required |
| `description` | text | Optional |
| `status` | varchar | `DRAFT`, `PUBLISHED`, `ARCHIVED` |
| `created_by_id` | FK User | Required |
| `published_at` | timestamptz | Nullable |
| timestamps | timestamptz | Required |

Index `(course_id, status, section_id, created_at)`.

### 5.9 `materials_materialversion`

| Column | Type | Rules |
| --- | --- | --- |
| `id` | UUID | Primary key |
| `material_id` | FK Material | Required, `PROTECT` |
| `version_number` | positive integer | Starts at 1 |
| `storage_key` | varchar | Generated path/key, unique |
| `original_filename` | varchar | Sanitized display name only |
| `content_type` | varchar | Server-validated |
| `size_bytes` | bigint | Required |
| `sha256` | char(64) | Lowercase hexadecimal digest |
| `uploaded_by_id` | FK User | Required |
| `created_at` | timestamptz | Immutable upload time |

Constraints and behavior:

- Unique `(material_id, version_number)`.
- Unique `storage_key`.
- Check `version_number >= 1` and `size_bytes > 0`.
- Creating a version locks the material row, calculates the next number, writes the file, then commits metadata. Clean up the file if the database transaction fails.
- Latest version is the row with highest `version_number`; do not maintain an unnecessary mutable `current_version_id` pointer.
- Students can download only versions of published material in a course where they have an active enrolment.

### 5.10 `assignments_assignment`

| Column | Type | Rules |
| --- | --- | --- |
| `id` | UUID | Primary key |
| `course_id` | FK Course | Required |
| `section_id` | nullable FK CourseSection | Must belong to same course |
| `title` | varchar(200) | Required |
| `instructions` | text | Required |
| `due_at` | timestamptz | Required |
| `max_score` | decimal(8,2) | Required, greater than zero |
| `max_upload_bytes` | bigint | Required; safe project default |
| `allowed_extensions` | JSON array | Validated lowercase extensions such as `['pdf', 'docx', 'zip']` |
| `allow_late_submissions` | boolean | Defaults false unless the course policy requires late status |
| `allow_resubmission` | boolean | Defaults true |
| `status` | varchar | `DRAFT`, `PUBLISHED`, `CLOSED`, `ARCHIVED` |
| `published_at` | timestamptz | Nullable |
| `created_by_id` | FK User | Required |
| timestamps | timestamptz | Required |

Constraints and indexes:

- Check `max_score > 0` and `max_upload_bytes > 0`.
- Index `(course_id, status, due_at)` for dashboards.
- Index `(status, due_at)` for deadline queries.
- Only published assignments are visible to students.
- Once the first submission exists, changing `due_at`, `max_score`, or late/resubmission policy requires an audit event and an explicit confirmation screen.
- Store the assignment's active deadline; do not copy it into every submission. Each version stores whether it was late at the moment it was received.

### 5.11 `assignments_submission`

One row represents one student's submission container for one assignment. File attempts/versions are children.

| Column | Type | Rules |
| --- | --- | --- |
| `id` | UUID | Primary key |
| `assignment_id` | FK Assignment | Required, `PROTECT` |
| `student_id` | FK User | Required, `PROTECT` |
| `created_at` | timestamptz | Time of first accepted submission |

Constraints and indexes:

- Unique `(assignment_id, student_id)`.
- Index `(student_id, created_at)`.
- Index `(assignment_id, created_at)`.
- Do not store a manually editable status column. The status is derived from versions and grade revisions:
  - no `Submission` row: `NOT_SUBMITTED`;
  - latest version on time and no released grade: `SUBMITTED`;
  - latest version late and no released grade: `LATE`;
  - a released grade exists: `GRADED`.

### 5.12 `assignments_submissionversion`

| Column | Type | Rules |
| --- | --- | --- |
| `id` | UUID | Primary key |
| `submission_id` | FK Submission | Required, `PROTECT` |
| `version_number` | positive integer | Starts at 1 |
| `storage_key` | varchar | Unique generated file key |
| `original_filename` | varchar | Sanitized display name |
| `content_type` | varchar | Server-validated |
| `size_bytes` | bigint | Required |
| `sha256` | char(64) | Required |
| `submitted_at` | timestamptz | Generated by server, immutable |
| `was_late` | boolean | Computed when accepted |

Constraints and behavior:

- Unique `(submission_id, version_number)`.
- Unique `storage_key`.
- Check `version_number >= 1` and `size_bytes > 0`.
- The server timestamp is authoritative; never accept a submission timestamp from the browser.
- First submission after the deadline is accepted only when `allow_late_submissions` is true and is marked late.
- Resubmission is accepted only when `allow_resubmission` is true and current server time is strictly before `due_at`.
- Use `transaction.atomic()` and lock the `Submission` row while calculating the next version number.
- Historical versions remain instructor-viewable and student-viewable. The UI labels the newest version "Current".

### 5.13 `assignments_graderevision`

Grades are append-only revisions so assessment changes remain traceable.

| Column | Type | Rules |
| --- | --- | --- |
| `id` | UUID | Primary key |
| `submission_id` | FK Submission | Required, `PROTECT` |
| `submission_version_id` | FK SubmissionVersion | Required, `PROTECT` |
| `revision_number` | positive integer | Starts at 1 |
| `score` | decimal(8,2) | Required |
| `feedback` | text | Optional |
| `graded_by_id` | FK User | Required |
| `created_at` | timestamptz | Immutable |
| `released_at` | timestamptz | Nullable; visible to student only when set |

Constraints and behavior:

- Unique `(submission_id, revision_number)`.
- Check `score >= 0`.
- Service validation ensures `score <= assignment.max_score` and the selected version belongs to the submission.
- Latest revision is current for the instructor.
- Latest released revision is current for the student.
- Editing a grade creates a new revision; it does not update the old row.
- Releasing and withdrawing a release are audited actions. Prefer a new revision when grade content changes.

### 5.14 `analytics_activityevent`

This table supports participation monitoring without pretending to measure physical class attendance.

| Column | Type | Rules |
| --- | --- | --- |
| `id` | big integer or UUID | Primary key |
| `course_id` | FK Course | Required |
| `user_id` | FK User | Required |
| `event_type` | varchar | Controlled choices |
| `object_type` | varchar | Optional controlled label |
| `object_id` | UUID | Optional related domain ID |
| `metadata` | JSON object | Small validated details only; no secrets |
| `occurred_at` | timestamptz | Server-generated |

Initial event types:

- `COURSE_VIEWED`
- `MATERIAL_VIEWED`
- `MATERIAL_DOWNLOADED`
- `ASSIGNMENT_VIEWED`
- `ANNOUNCEMENT_VIEWED`
- `SUBMISSION_CREATED`
- `SUBMISSION_RESUBMITTED`

Indexes:

- `(course_id, occurred_at DESC)`.
- `(course_id, user_id, occurred_at DESC)`.
- `(user_id, occurred_at DESC)`.

Events are append-only. Do not record every page refresh if it creates noisy data; rate-limit repeated view events per user/object within a short window. Never market this data as attendance.

### 5.15 `audit_auditevent`

Append-only record of security-sensitive or academically significant changes.

| Column | Type | Rules |
| --- | --- | --- |
| `id` | UUID | Primary key |
| `actor_id` | nullable FK User | Null only for system action |
| `action` | varchar | Controlled action name |
| `object_type` | varchar | Required |
| `object_id` | UUID | Required |
| `course_id` | nullable FK Course | Used for scoped queries |
| `metadata` | JSON object | IDs and changed field names; no passwords/file contents |
| `occurred_at` | timestamptz | Server-generated |

Audit at least these actions:

- course publish/archive and enrolment-mode change;
- material publish/archive and new version;
- announcement publish/edit/archive;
- assignment publish, deadline/policy change, close/archive;
- submission and resubmission acceptance;
- grade revision and release/withdrawal;
- staff role changes.

## 6. Cross-table invariants

PostgreSQL `CHECK` constraints cannot safely enforce rules that require another table. Enforce these in named domain services inside one transaction and test them:

- course owner has instructor role;
- enrolment user has student role;
- section belongs to the same course as its material or assignment;
- announcement author owns the course;
- material uploader owns the course;
- assignment creator owns the course;
- student has active enrolment before submission;
- submission version obeys extension, size, deadline, late, and resubmission rules;
- grade version belongs to the selected submission;
- grader owns the assignment's course;
- score does not exceed assignment maximum.

Do not duplicate these checks differently in several views. Centralize them in service functions and call the same functions from HTML views, admin actions, and future interfaces.

## 7. File storage and upload safety

### 7.1 Storage rules

- Development uses `MEDIA_ROOT` on the WSL filesystem, mounted or located inside the Linux filesystem for performance.
- Production may replace the Django storage backend with S3-compatible object storage without changing domain models.
- Use generated keys, never user-controlled filesystem paths.
- Suggested keys:
  - `courses/<course_uuid>/materials/<material_uuid>/<version_uuid>`
  - `courses/<course_uuid>/assignments/<assignment_uuid>/submissions/<submission_uuid>/<version_uuid>`
- Preserve the sanitized original filename only as metadata.
- Calculate SHA-256 while receiving the upload.
- Validate configured extension, MIME type, and maximum size server-side.
- Serve student submissions as protected attachment downloads after authorization. Never expose the media directory directly through a public web server.
- Set `Content-Disposition: attachment` for untrusted formats.
- Do not render uploaded HTML/SVG inline.
- Do not unpack ZIP files automatically.
- A failed database transaction must remove any newly written orphan file.

### 7.2 Version semantics

The assignment text sometimes says a resubmission "replaces" the previous file, but it also requires version timestamps and a clear record. Implement this consistently:

- The new version replaces the old one only in the current-view UI.
- The database and storage retain all versions.
- Students and instructors see version number and submission/upload time.
- No normal UI action hard-deletes an academic file version.

## 8. Required workflows

### 8.1 Registration and login

1. User selects student or instructor role, supplies username, email, display name, and password.
2. Form normalizes username/email and validates uniqueness.
3. Django hashes the password.
4. User logs in using username or email plus password.
5. Successful login redirects to the role-appropriate dashboard.
6. Invalid credentials return a generic error without revealing whether an account exists.

Acceptance criteria:

- Duplicate normalized username/email is rejected.
- Password validation runs during registration and password change.
- Anonymous users cannot access dashboards or course pages.
- Inactive users cannot log in.

### 8.2 Course creation and publication

1. Instructor creates a draft course.
2. Instructor adds syllabus and ordered sections.
3. Course can be published only when code, title, description, and at least one section are valid.
4. Instructor opens or closes enrolment separately from publication.
5. Published open courses appear in the student catalogue.

### 8.3 Student enrolment

1. Student browses published courses with open enrolment.
2. Student posts an enrol action.
3. Service locks/checks course, verifies role and state, then creates or reactivates one enrolment.
4. Repeated requests are idempotent and never create duplicate rows.
5. Student is redirected to the course home page with a success message.

### 8.4 Material upload and download

1. Instructor creates a logical material record in a course/section.
2. Instructor uploads version 1.
3. Later uploads create version 2, 3, and so on.
4. Publishing the material makes its latest version visible to enrolled students.
5. Authorized downloads stream through a protected view and record a download activity event.

### 8.5 Announcement feed

1. Instructor writes a draft or publishes immediately.
2. Feed displays pinned announcements first, then newest published items.
3. Student opening an announcement idempotently creates `AnnouncementRead`.
4. Dashboard unread count is a query, not a stored counter.
5. Ordinary page refresh is the initial update mechanism.

### 8.6 Assignment publication

1. Instructor creates a draft with instructions, deadline, max score, allowed extensions, maximum upload size, late policy, and resubmission policy.
2. Service validates the deadline and configuration.
3. Publishing makes it visible to active enrolled students.
4. Student dashboard orders upcoming assignments by deadline.
5. Closing blocks new first submissions and resubmissions.

### 8.7 Submission and resubmission

1. Student opens a published assignment in an enrolled course.
2. Server validates enrolment, assignment state, file type, and size.
3. Server captures current UTC time.
4. If no submission exists, create the submission container and version 1.
5. If a submission exists, enforce resubmission policy/deadline and create the next immutable version.
6. Compute `was_late` at acceptance time.
7. Show confirmation with version number, server timestamp, and current status.
8. Record activity and audit events.

Boundary rules must have tests for exactly before, exactly at, and after `due_at`. The rule is: resubmission requires `now < due_at`; first submission after `due_at` requires `allow_late_submissions`.

### 8.8 Grading

1. Instructor opens assignment submission list.
2. List clearly separates missing, submitted, late, and graded students.
3. Instructor reviews any retained submission version.
4. Saving creates a new grade revision.
5. Student cannot see a draft grade with null `released_at`.
6. Release action sets visibility and creates an audit event.
7. Student dashboard shows only the latest released revision.

### 8.9 Participation monitoring

Instructor dashboard for a selected course must show:

- total active enrolments;
- each student's most recent activity time;
- assignments submitted, missing, late, and graded;
- released score totals/averages where applicable;
- students with no platform activity in a configurable number of days.

Use efficient annotated ORM queries and pagination. Avoid one query per student. This dashboard reports platform engagement, not physical attendance.

## 9. URL and page map

Use stable UUID-based URLs and named URL patterns.

```text
GET/POST /accounts/register/
GET/POST /accounts/login/
POST     /accounts/logout/
GET      /dashboard/

GET      /courses/
GET      /courses/new/
POST     /courses/new/
GET      /courses/<course_id>/
GET/POST /courses/<course_id>/edit/
POST     /courses/<course_id>/publish/
POST     /courses/<course_id>/enrol/
GET      /courses/<course_id>/participants/

GET      /courses/<course_id>/announcements/
GET/POST /courses/<course_id>/announcements/new/
GET      /courses/<course_id>/announcements/<announcement_id>/

GET      /courses/<course_id>/materials/
GET/POST /courses/<course_id>/materials/new/
GET/POST /courses/<course_id>/materials/<material_id>/versions/new/
GET      /courses/<course_id>/materials/<material_id>/versions/<version_id>/download/

GET      /courses/<course_id>/assignments/
GET/POST /courses/<course_id>/assignments/new/
GET      /courses/<course_id>/assignments/<assignment_id>/
GET/POST /courses/<course_id>/assignments/<assignment_id>/submit/
GET      /courses/<course_id>/assignments/<assignment_id>/submissions/
GET      /courses/<course_id>/assignments/<assignment_id>/submissions/<submission_id>/
GET/POST /courses/<course_id>/assignments/<assignment_id>/submissions/<submission_id>/grade/
POST     /courses/<course_id>/assignments/<assignment_id>/submissions/<submission_id>/release-grade/

GET      /courses/<course_id>/analytics/
```

All mutations use POST and CSRF protection. Use POST/redirect/GET after successful forms. Avoid mutation in GET handlers.

## 10. User interface requirements

- Responsive from 360 px mobile width through desktop.
- One shared base template with consistent header, navigation, messages, and footer.
- Role-specific dashboard without role-specific duplicate layout systems.
- Every form has visible labels, field-level errors, a clear submit action, and a cancel/back path.
- Use semantic HTML and keyboard-operable controls.
- Provide a visible focus state and sufficient color contrast.
- Do not communicate status by color alone.
- Use explicit empty states: no courses, no materials, no announcements, no assignments, and no submissions.
- Show all deadlines with timezone label and a relative hint such as "Due in 2 days".
- Show server-recorded timestamps for submissions and versions.
- Confirmation dialogs are required before archive, deadline changes after submissions, and grade release/withdrawal.
- Paginate course rosters, activity tables, and submission lists.
- Never expose database IDs, storage paths, hashes, or internal error traces to ordinary users.

## 11. Security baseline

- Keep `SECRET_KEY`, database credentials, allowed hosts, secure-cookie flags, and storage credentials in environment variables.
- Commit `.env.example`, never `.env`.
- Use Django CSRF middleware for every form.
- Use Django password validation and secure password hashing defaults.
- Use ORM parameters; never construct SQL with user input.
- Check object-level authorization in every protected view.
- Add login throttling only through a well-maintained package if brute-force protection becomes a deployment requirement; do not invent a fragile custom rate limiter.
- Validate uploaded content as described above.
- In production enable HTTPS redirect, secure session/CSRF cookies, HSTS after HTTPS is confirmed, and restrictive allowed hosts.
- Keep debug disabled outside local development.
- Return generic 404 responses where revealing resource existence would leak another user's data.
- Do not place personal information in logs or audit metadata unless required.
- Run Django's deployment checks before release.

## 12. Query and performance expectations

The expected academic-demo scale is modest: dozens of courses, hundreds of students, and thousands of uploads/events. Optimize correctness and clarity first.

- Use `select_related()` for single-valued foreign keys.
- Use `prefetch_related()` for collections shown on the same page.
- Paginate potentially growing lists.
- Use the indexes specified in the schema.
- Add an index only for an observed or clearly required query pattern.
- Use aggregate queries for dashboards; never loop over students and issue a query for each.
- Stream downloads instead of reading the whole file into memory.
- Do not add caching until a measured page is slow.

## 13. Migrations and data discipline

1. Model changes require Django migrations in the same change.
2. Review generated migrations; do not blindly accept them.
3. Never edit a migration that teammates may already have applied. Add a new migration.
4. Use explicit data migrations for required backfills.
5. Test migrations against PostgreSQL, not only model tests.
6. Use constraints from the first migration wherever possible.
7. Seed data is created by an idempotent management command, not a data migration.
8. The seed command creates at least:
   - one instructor;
   - two students;
   - one published/open course with sections;
   - active enrolments;
   - two material versions;
   - two announcements;
   - one upcoming and one past assignment;
   - on-time, late, missing, and graded scenarios.
9. Never commit real student data or uploaded coursework.

## 14. Testing contract

Run tests against PostgreSQL. Minimum test categories:

### 14.1 Model/constraint tests

- normalized course code uniqueness;
- one enrolment per course/student;
- ordered section uniqueness;
- material and submission version uniqueness;
- one submission container per assignment/student;
- grade revision uniqueness;
- non-negative/positive numeric checks.

### 14.2 Permission tests

- anonymous denial;
- unenrolled student denial;
- student cannot access another student's submission;
- instructor cannot modify another instructor's course;
- student cannot call instructor endpoints;
- instructor cannot submit as a student;
- protected downloads enforce the same rules as pages.

### 14.3 Workflow tests

- registration/login with username and email;
- course publish and enrolment;
- idempotent enrolment;
- material upload and version ordering;
- announcement publish/read behavior;
- first submission before deadline;
- first submission after deadline with late disabled/enabled;
- resubmission before deadline;
- rejection at and after deadline;
- concurrent version-number protection;
- grade draft, revision, release, and student visibility;
- dashboard state for missing/submitted/late/graded.

### 14.4 File tests

- extension/size rejection;
- filename sanitization;
- authorization before download;
- hash and size metadata accuracy;
- orphan cleanup after failed transaction;
- historical versions remain accessible.

### 14.5 Required checks before merging

```bash
uv lock --check
uv run ruff check .
uv run ruff format --check .
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py check
uv run python manage.py test
```

Before deployment also run:

```bash
uv run python manage.py check --deploy
```

## 15. Local WSL development

Keep the repository inside the WSL Linux filesystem when possible, for example `~/projects/course-collaboration`, rather than under `/mnt/c`, to avoid slow file watching and permission surprises.

Expected initial workflow:

```bash
uv sync
docker compose up -d db
uv run python manage.py migrate
uv run python manage.py seed_demo
uv run python manage.py runserver
```

The application should be available at `http://127.0.0.1:8000/`.

Required environment variables belong in `.env`:

```text
DJANGO_SECRET_KEY=
DJANGO_DEBUG=true
DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost
DATABASE_URL=postgresql://course_app:course_app@127.0.0.1:5432/course_app
DJANGO_TIME_ZONE=Asia/Kuala_Lumpur
MEDIA_ROOT=
```

`.env.example` contains safe placeholders only.

Docker Compose initially contains one `db` service with a health check and named volume. Do not containerize the Django development server until doing so solves a real team setup problem.

## 16. Delivery sequence and requirement mapping

### Phase 1 - Foundation

- Repository structure, `uv`, settings, PostgreSQL Compose service.
- Custom user model and authentication.
- All core database models, initial migrations, constraints, and admin registration.
- Seed command and base templates.

### Phase 2 - Core MVP (high priority)

- FR-STU-01 registration/login.
- FR-INS-01 course setup and sections.
- FR-STU-02 catalogue and enrolment.
- FR-INS-02 plus FR-STU-03 material upload/version/download.
- FR-INS-04 plus FR-STU-04 assignment creation and first submission.

### Phase 3 - Communication and assessment (medium priority)

- FR-INS-03 plus FR-STU-06 announcement feed/read state.
- FR-STU-05 resubmission history.
- FR-INS-05 grading, feedback, revision, and release.

### Phase 4 - Monitoring and hardening (low priority plus quality)

- FR-INS-06 analytics and participation dashboard.
- Permission audit, upload hardening, accessibility review, integration tests.
- Production settings, backup/restore rehearsal, deployment verification.

The assignment milestones are July 19, 2026 for the core MVP, July 26 for the requirement pivot, August 2 for feature freeze, and August 9 for final delivery. Treat these as planning targets, not as permission to skip correctness or security.

## 17. Team ownership without code silos

The report assigns primary feature ownership as follows:

- Deshigan: authentication, course setup, and enrolment.
- Tamyuzuddin: database/architecture, materials/versioning, and announcements.
- Darneshtas: assignments, submissions/resubmissions, grading, and analytics.

Ownership means first responsibility, not exclusive access. Every database migration and cross-app service change requires review from at least one teammate whose owned area is affected.

Avoid parallel migrations that edit the same tables. Agree on migration order during the daily standup and rebase before generating a new migration.

## 18. Requirement-change procedure

The project expects a Week 8 requirement change. When it arrives:

1. Record the exact new or changed acceptance criteria.
2. Map it to existing FR/UC identifiers or assign a new local identifier.
3. Identify affected tables, services, views, templates, permissions, and tests.
4. Prefer extending the modular monolith over replacing architecture.
5. Create forward-only migrations.
6. Reprioritize low/medium backlog items if schedule capacity is insufficient.
7. Update this file before implementing behavior that changes product rules.

Do not pre-build speculative extension points beyond the clean app/service boundaries already described.

## 19. Coding rules for agents

- Read nearby models, services, tests, and migrations before editing.
- Make the smallest coherent change that fully satisfies a requirement.
- Use descriptive domain names from this file.
- Keep views thin: parse request, authorize, validate form, call service, render/redirect.
- Keep models responsible for local validation and representation; keep multi-row workflows in services.
- Wrap multi-row writes and version allocation in `transaction.atomic()`.
- Do not use model signals for core workflows.
- Do not catch broad exceptions unless re-raising after cleanup or translating at a clear boundary.
- Do not silently ignore failed file or database operations.
- Do not add dependencies without documenting why standard Django/Python is insufficient.
- Do not add a JavaScript framework, API layer, async queue, WebSocket server, or cache without an approved requirement and a short architecture decision record.
- Update tests and migrations with implementation changes.
- Update this file when a confirmed requirement changes system behavior or data rules.
- Preserve unrelated user changes in a dirty worktree.

## 20. Definition of done

A feature is done only when:

- its acceptance criteria are implemented;
- server-side authorization is present;
- validation and failure messages are usable;
- database constraints/migrations are included where applicable;
- activity/audit events are added where specified;
- tests cover success, permission denial, and important edge cases;
- pages work on mobile and desktop widths;
- there are no unhandled tracebacks in expected user errors;
- lint, migration check, Django check, and tests pass;
- a teammate can run it from the documented WSL setup.

## 21. Feature commits and GitHub delivery

After each independently usable feature is complete, verified, and meets the definition of done, create one focused Git commit for it. Examples include authentication, course creation/enrolment, materials/versioning, announcements, assignment submission, grading, and analytics.

Configured GitHub repository: https://github.com/DarneshtasMokanatas/course-collab-platform.git. Push each verified feature commit to the origin remote on the active feature branch when authentication is available.

Follow this workflow:

1. Review the working tree and preserve unrelated user changes.
2. Run the required checks from Section 14.
3. Stage only files belonging to the finished feature, including its migrations and tests.
4. Create a concise conventional commit message in imperative form, for example `feat(assignments): add timestamped submission versions`.
5. Push the commit to the configured GitHub remote and active feature branch when the remote points to the user's repository and authentication is available.
6. Report the commit hash, branch, and push result after each feature.

Do not commit failing code, secrets, `.env`, local media uploads, generated databases, temporary files, or unrelated changes. Do not force-push, rewrite shared history, change remotes, or create a pull request unless the user explicitly asks. If GitHub credentials, remote configuration, or push access is unavailable, still create the verified local commit and report exactly what is needed to push it.

## 22. Architecture references

The selected approach is based on official documentation:

- Django 5.2 is an LTS release: https://docs.djangoproject.com/en/5.2/releases/5.2/
- Django authentication/custom user guidance: https://docs.djangoproject.com/en/5.2/topics/auth/customizing/
- Django file uploads: https://docs.djangoproject.com/en/5.2/topics/http/file-uploads/
- PostgreSQL constraints and data definition: https://www.postgresql.org/docs/current/ddl.html
- uv project locking and syncing: https://docs.astral.sh/uv/concepts/projects/sync/
- Docker Compose application lifecycle and volumes: https://docs.docker.com/compose/gettingstarted/
