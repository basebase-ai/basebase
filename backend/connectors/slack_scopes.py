"""
Canonical Slack OAuth scope definitions.

Single source of truth used by:
- Nango connect session (user_scopes override)
- ``GET /api/auth/slack/install`` (public "Add to Slack" redirect)
- Slack console OAuth & Permissions (manual — keep in sync)

When adding or removing a scope, update this file *and* the Slack console +
Nango dashboard so all three stay aligned.
"""

SLACK_BOT_SCOPES: str = ",".join([
    "app_mentions:read",
    "channels:history",
    "channels:join",
    "channels:read",
    "chat:write",
    "chat:write.public",
    "files:read",
    "files:write",
    "groups:history",
    "groups:read",
    "im:history",
    "im:read",
    "im:write",
    "mpim:history",
    "mpim:read",
    "mpim:write",
    "reactions:read",
    "reactions:write",
    "users:read",
    "users:read.email",
    "users.profile:read",
])

SLACK_USER_SCOPES: str = ",".join([
    "users:read",
    "users:read.email",
])
