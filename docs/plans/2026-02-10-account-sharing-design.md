# Account Management & Project Sharing Design (v2)

## Overview

Replace Boswell's single-team access model with user accounts and per-project sharing.
Projects are private by default and shared explicitly with roles (`view`, `operate`, `collaborate`, `owner`).

This revision resolves security and migration gaps from v1, including:

- Invite-only registration for now (no open direct signup yet)
- Email identity checks before access is granted
- Single source of truth for project authorization
- Deterministic migration from team-level access
- Hard guarantee that non-deleted projects always have at least one owner

---

## 1. Key Decisions

| Decision | Choice |
|----------|--------|
| Sharing model | Per-project ACL (Google Docs style) |
| Permission levels | View, Operate, Collaborate, Owner |
| Auth | Email + password sessions |
| Registration policy (Phase 1) | **Invite-only** |
| Registration policy (Phase 2, optional) | Direct signup allowed only after email verification + password reset are fully live |
| User discovery | Email-based invite and share flow |
| Teams | Removed entirely |
| Dashboard | "My Projects" + "Shared with me" |
| Ownership transfer | Supported by granting `owner` role |
| Templates | Personal per-user (not shared) |
| ADMIN_EMAILS allowlist | Removed |
| Last-owner invariant | Required for all non-deleted projects |

---

## 2. Non-Negotiable Invariants

1. **Project access source of truth is `project_shares` only**.  
   `projects.created_by` is audit metadata, not an authorization check.
2. **At least one owner must exist for every non-deleted project**.
3. **Invite claims are single-use and atomic**.
4. **Invite email must match the authenticated account email**.
5. **No direct signup in Phase 1**.
6. **No authorization paths may rely on legacy `team_id` after cutover**.

---

## 3. Data Model

## `users` table changes

- Add `password_hash` (`TEXT`, nullable during migration, non-null after migration completion)
- Add `email_verified_at` (`TIMESTAMPTZ`, nullable)
- Keep `email` unique (normalized lowercase at write time)
- Remove `team_id` foreign key

### Notes

- `email_verified_at` is required for future direct-signup flows.
- During Phase 1 invite-only mode, invite claim can set verification state when identity checks pass.

## New `project_shares` table (authorization source of truth)

| Column | Type | Purpose |
|--------|------|---------|
| `id` | UUID PK | Row identity |
| `project_id` | UUID FK -> `interviews.id` | Shared project |
| `user_id` | UUID FK -> `users.id` | User with access |
| `role` | Enum(`view`,`operate`,`collaborate`,`owner`) | Permission level |
| `granted_by` | UUID FK -> `users.id` (nullable on delete set null) | Actor who granted |
| `created_at` | TIMESTAMPTZ | Created time |
| `updated_at` | TIMESTAMPTZ | Last role change |

### Required constraints and indexes

- Unique: `(project_id, user_id)`
- Index: `(user_id, project_id)` for "shared with me"
- Index: `(project_id, role)` for authorization checks
- Index: `(project_id)` for collaborator listing
- FK delete behavior:
  - `project_id` -> `ON DELETE CASCADE`
  - `user_id` -> `ON DELETE CASCADE`
  - `granted_by` -> `ON DELETE SET NULL`

## New `account_invites` table

| Column | Type | Purpose |
|--------|------|---------|
| `id` | UUID PK | Row identity |
| `token_hash` | `CHAR(64)` unique | SHA-256 of raw token (do not store raw token) |
| `token_prefix` | `VARCHAR(12)` | Debug/audit visibility |
| `email` | `VARCHAR(255)` | Target email (normalized lowercase) |
| `invited_by` | UUID FK -> `users.id` | Inviter |
| `project_id` | UUID FK -> `interviews.id` nullable | Project to share |
| `role` | Enum nullable | Role to grant for project invite |
| `claimed_by_user_id` | UUID FK -> `users.id` nullable | User that consumed invite |
| `claimed_at` | TIMESTAMPTZ nullable | Consumption timestamp |
| `expires_at` | TIMESTAMPTZ | Expiry |
| `revoked_at` | TIMESTAMPTZ nullable | Revocation timestamp |
| `created_at` | TIMESTAMPTZ | Created timestamp |

### Required constraints and indexes

- Unique: `token_hash`
- Check: if `project_id` is not null then `role` is not null
- Index: `(email, claimed_at, revoked_at, expires_at)`
- Index: `(project_id, claimed_at, revoked_at)`

## `interview_templates` changes

- Remove `team_id`
- Add/keep `created_by` (user ownership)
- Templates remain personal and unshared

## Removed `teams` table

- Drop `teams`
- Drop all `team_id` columns and FKs from:
  - `users`
  - `interviews` (project table)
  - `interview_templates`

---

## 4. Authentication and Identity

## Phase 1 (current target): Invite-only registration

- Supported routes:
  - `GET/POST /auth/login` (email + password)
  - `GET/POST /auth/invite/{token}` (claim invite + create account if needed)
  - `POST /auth/logout`
- **Direct signup route is disabled** in this phase.

### Invite claim rules

1. Normalize token and email inputs.
2. Validate invite exists, is not expired, not revoked, not already claimed.
3. User must authenticate (existing account) or create account with the same invite email.
4. Account email must exactly match invite email (normalized).
5. Invite claim and share grant must happen in one transaction.
6. Set `claimed_at` and `claimed_by_user_id` atomically.
7. Upsert `project_shares(project_id, user_id)` with invited role.

## Phase 2 (optional, future): Direct signup

Direct signup is allowed only after:

1. Email verification is fully operational.
2. Password reset/forgot-password is fully operational.
3. Abuse controls exist (rate limits, lockouts, and verification enforcement).

## Password setup/reset migration safety

To avoid lockout during migration:

- Keep a temporary password setup/reset path for existing users until completion.
- Existing sessions can remain valid, but users without `password_hash` are forced through password setup before protected actions.
- Remove temporary fallback only when all active users can reliably recover accounts.

---

## 5. Permission Matrix

| Action | View | Operate | Collaborate | Owner |
|--------|------|---------|-------------|-------|
| See project, transcripts, analyses | yes | yes | yes | yes |
| Start/manage interviews | no | yes | yes | yes |
| Edit project config, questions, research | no | no | yes | yes |
| Add/remove guests | no | no | yes | yes |
| Manage sharing and roles | no | no | no | yes |
| Delete project | no | no | no | yes |
| Transfer ownership | no | no | no | yes |

---

## 6. Authorization Architecture

Introduce a central permission resolver and remove ad hoc checks.

## Required backend primitives

- `get_project_role(user_id, project_id) -> role | None`
- `require_project_role(min_role)` dependency/helper
- `can_manage_sharing(project_id, user_id)` (owner only)
- `assert_not_last_owner_before_downgrade_or_revoke(...)`

## Migration rule for existing routes

- Replace every `Project.team_id == user.team_id` check with project-role checks.
- Replace every `InterviewTemplate.team_id == user.team_id` check with template ownership checks.
- Require explicit project-role checks in all project-scoped endpoints.

### Scope note

Current code contains many team-scoped checks in admin routes; migration must be route-by-route and test-backed, not a global search/replace.

---

## 7. Sharing and Ownership Workflows

## Share project (owner only)

1. Owner enters target email and role.
2. If matching user exists:
   - Upsert `project_shares` directly.
3. If user does not exist:
   - Create `account_invites` row.
   - Generate raw token once, store only `token_hash`.
   - Show copyable invite URL (manual send is allowed).

## Manage collaborators

- Owners can list collaborators, change roles, revoke access.
- Pending invites are visible with copy and revoke actions.
- Role changes and revocations are audit-logged.

## Ownership transfer and co-owners

- Multiple owners are allowed.
- Downgrading/removing an owner is blocked if they are the last owner.
- Last-owner removal is allowed only when deleting the project in the same authorized operation.

---

## 8. Dashboard and UI

## Dashboard sections

- `My Projects` (where user has `owner`)
- `Shared with me` (where role is `view`/`operate`/`collaborate` or non-primary-owner entries)

## Project UI

- Sharing tab visible only to owners
- Collaborator list with role badges
- Pending invite list with status
- Action buttons gated by role

## Auth UI

- Login page (email/password)
- Invite claim page (existing or new user with locked invite email)
- Account settings page (name/password)

---

## 9. Migration Strategy (Phased)

## Phase A: Additive schema rollout

1. Add `users.password_hash` (nullable)
2. Add `users.email_verified_at`
3. Create `project_shares`
4. Create `account_invites`
5. Add needed indexes/constraints

## Phase B: Backfill authorization data

For each existing project:

1. Ensure `created_by` is set; if null, assign deterministic fallback owner (earliest active team user by created date, then lowest UUID tie-break).
2. Insert owner share for `created_by`.
3. For all **other** users currently in the same legacy team, insert `view` share.  
   (This is an explicit product decision.)
4. Verify owner count >= 1.

For templates:

1. Add/set `created_by`.
2. Backfill ownership deterministically from existing team membership.

## Phase C: Dual-read/dual-write transition

- Temporarily write both legacy and new auth fields if needed.
- Read permissions from `project_shares` in shadow mode and compare to legacy decisions.
- Log mismatches and block cutover until mismatch rate is acceptable.

## Phase D: Auth cutover

1. Enable password login.
2. Enable invite-only registration.
3. Keep temporary password setup/reset fallback for migration period.
4. Disable direct signup.

## Phase E: Authorization cutover

1. Remove `team_id` checks from all routes.
2. Enforce centralized role checks.
3. Run regression suite.

## Phase F: Cleanup

1. Drop `team_id` columns and FKs.
2. Drop `teams` table.
3. Remove temporary migration-only auth fallback when safe.

---

## 10. Operational and Security Requirements

- Rate limit login and invite-claim endpoints.
- Add brute-force protection (progressive delays or temporary lockouts).
- Record security audit events:
  - invite created/revoked/claimed
  - share granted/changed/revoked
  - owner transfer
  - project deletion
- Never log raw invite tokens.
- Use constant-time comparison for token hash checks.

---

## 11. Testing Requirements

## Unit tests

- Role resolution and permission boundaries
- Last-owner invariant enforcement
- Invite claim validation (expired/revoked/already claimed/email mismatch)

## Integration tests

- Invite-only registration end-to-end
- Existing-user invite claim
- New-user invite claim
- Share role change and revoke
- Project deletion as last owner
- Migration backfill correctness for legacy teams (`owner` + teammate `view`)

## Migration validation checks

- Every non-deleted project has >=1 owner row
- No orphaned project_shares
- No route allows project access without project_shares membership

---

## 12. Explicitly Deferred

- Public self-serve direct signup (until Phase 2 gates are met)
- Organization/team-level ACLs
- Shared templates across users

