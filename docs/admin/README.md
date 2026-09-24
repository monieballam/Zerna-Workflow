# Admin Guide

This section documents the organization-scoped admin surfaces in Zerna.

## What Admins Can Do

- Review all submitted feedback for the current organization
- See which user submitted the feedback
- See whether the feedback is system-wide or attached to a specific run
- See the dataset and run snapshot captured at submission time
- Inspect the parameters used for that run when the feedback was submitted
- Create new users directly into the organization
- Attach existing users to the organization
- Promote members to `admin`
- Demote admins, except for the last remaining admin in the organization

## Feedback Model

Feedback is organization-scoped and stored with snapshots so review remains useful even if the underlying run or dataset changes later.

For run-specific feedback, the system captures:

- submitter email
- run id
- dataset id snapshot
- dataset name snapshot
- template id snapshot
- run parameters snapshot
- run status snapshot
- submission timestamp

For system-wide feedback, only the submitter and the feedback content are stored.

## User-Facing Entry Points

- `/feedback`
  Users can submit whole-system feedback or choose a specific run.
- `/runs/[id]`
  Run detail includes a `Send feedback` shortcut that opens the feedback form pre-scoped to that run.

## Admin Dashboard

- `/admin`
  Shows member management and feedback review for the current organization.

The current app session uses the user’s primary organization membership as the active org context.

## Bootstrap Admin

The API startup path supports a bootstrap admin flow:

- `BOOTSTRAP_ADMIN_EMAIL`
  Defaults to `admin@zerna.local`
- `BOOTSTRAP_ADMIN_ORG_NAME`
  Defaults to `Zerna`
- `BOOTSTRAP_ADMIN_PASSWORD`
  Optional. If set, startup can create the bootstrap admin account when it does not already exist.

Behavior:

1. If `BOOTSTRAP_ADMIN_EMAIL` already exists, startup promotes it to admin in the configured org when needed.
2. If the user exists but has no org membership, startup attaches it to the configured org as admin.
3. If the user does not exist and `BOOTSTRAP_ADMIN_PASSWORD` is set, startup creates the account and makes it admin.
4. If the user does not exist and no password is configured, startup logs and skips creation.

## Operational Notes

- Admin role is organization-scoped, not global.
- Feedback review is also organization-scoped.
- Run-scoped feedback preserves review context even if the run itself is later deleted or detached from its source dataset.
- The app prevents demoting the last admin in an organization.
