"""Increment 3 schema: trial, founder claims, billing, profiles, outbox, alerts, admin (DD 2.2-2.7).

Tables: trial_claims, founder_claims (with the FK to subscriptions), payments, billing_events,
refund_requests, user_profiles, profile_versions, email_outbox, alert_rules, alert_deliveries,
notifications, admin_audit_log, app_errors, monitor_alert_state. The Detailed Design names this
file 0003; 0003 was taken by the setup engine document (task 2.3), so it is 0004.

profile_versions and admin_audit_log are append-only by trigger (a REVOKE does nothing against
the owner); the audit log also refuses TRUNCATE and has its grants revoked from the app role.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-18
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

OUTBOX_KINDS = (
    "verify", "reset", "alert", "refund_requested", "refund_approved", "refund_rejected",
    "refund_completed", "already_registered", "payment_failed", "subscription_ended",
    "trial_ending",
)  # fmt: skip
_KINDS_SQL = ",".join(f"'{k}'" for k in OUTBOX_KINDS)

UPGRADE = [
    # ---------------------------------------------------------------- 2.2 trial and founder offer
    """CREATE TABLE trial_claims (
  email_hash char(64) PRIMARY KEY,
  user_id    uuid REFERENCES users(id) ON DELETE SET NULL,
  claimed_at timestamptz NOT NULL DEFAULT now()
)""",
    """CREATE TABLE founder_claims (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  plan_code       text NOT NULL REFERENCES founder_slots(plan_code),
  user_id         uuid NOT NULL REFERENCES users(id),
  subscription_id uuid REFERENCES subscriptions(id),
  status          text NOT NULL CHECK (status IN ('reserved','confirmed','released')),
  reserved_until  timestamptz,
  created_at      timestamptz NOT NULL DEFAULT now(),
  confirmed_at    timestamptz,
  released_at     timestamptz
)""",
    "CREATE UNIQUE INDEX founder_claim_one_per_user ON founder_claims (plan_code, user_id)"
    " WHERE status IN ('reserved','confirmed')",
    # ---------------------------------------------------------------- 2.3 payments, events, refunds
    """CREATE TABLE payments (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id             uuid NOT NULL REFERENCES users(id),
  subscription_id     uuid REFERENCES subscriptions(id),
  plan_code           text REFERENCES plans(code),
  amount_minor        integer NOT NULL CHECK (amount_minor >= 0),
  refunded_minor      integer NOT NULL DEFAULT 0 CHECK (refunded_minor BETWEEN 0 AND amount_minor),
  currency            char(3) NOT NULL,
  razorpay_payment_id text NOT NULL UNIQUE,
  status              text NOT NULL CHECK (status IN ('captured','failed','refunded','partially_refunded')),
  is_first_payment    boolean NOT NULL,
  paid_at             timestamptz NOT NULL
)""",
    "CREATE INDEX payments_user ON payments (user_id, paid_at DESC)",
    """CREATE TABLE billing_events (
  razorpay_event_id text PRIMARY KEY,
  type              text NOT NULL,
  payload           jsonb NOT NULL,
  received_at       timestamptz NOT NULL DEFAULT now(),
  processed_at      timestamptz,
  error             text
)""",
    "CREATE INDEX billing_events_failed ON billing_events (received_at) WHERE error IS NOT NULL",
    """CREATE TABLE refund_requests (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id            uuid NOT NULL REFERENCES users(id),
  payment_id         uuid NOT NULL REFERENCES payments(id),
  amount_minor       integer NOT NULL CHECK (amount_minor > 0),
  reason             text NOT NULL,
  status             text NOT NULL DEFAULT 'requested'
                     CHECK (status IN ('requested','approved','rejected','completed','failed')),
  within_policy      boolean NOT NULL,
  requested_by       uuid NOT NULL REFERENCES users(id),
  decided_by         uuid REFERENCES users(id),
  decision_reason    text,
  access_outcome     text CHECK (access_outcome IN ('downgraded_now','kept_until_period_end')),
  razorpay_refund_id text UNIQUE,
  created_at         timestamptz NOT NULL DEFAULT now(),
  decided_at         timestamptz,
  completed_at       timestamptz,
  CHECK (status <> 'rejected' OR decision_reason IS NOT NULL)
)""",
    "CREATE UNIQUE INDEX refund_one_open ON refund_requests (payment_id)"
    " WHERE status IN ('requested','approved')",
    "CREATE INDEX refund_queue ON refund_requests (created_at) WHERE status = 'requested'",
    # ---------------------------------------------------------------- 2.6 profiles
    """CREATE TABLE user_profiles (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id    uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name       text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz
)""",
    "CREATE UNIQUE INDEX user_profiles_name ON user_profiles (user_id, name) WHERE deleted_at IS NULL",
    """CREATE TABLE profile_versions (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  profile_id    uuid NOT NULL REFERENCES user_profiles(id) ON DELETE CASCADE,
  version       integer NOT NULL,
  settings      jsonb NOT NULL,
  settings_hash char(64) NOT NULL,
  created_at    timestamptz NOT NULL DEFAULT now(),
  UNIQUE (profile_id, version)
)""",
    "CREATE TRIGGER profile_versions_immutable BEFORE UPDATE ON profile_versions"
    " FOR EACH ROW EXECUTE FUNCTION forbid_change()",
    # ---------------------------------------------------------------- 2.6 e-mail outbox
    f"""CREATE TABLE email_outbox (
  id              bigserial PRIMARY KEY,
  kind            text NOT NULL CHECK (kind IN ({_KINDS_SQL})),
  user_id         uuid REFERENCES users(id) ON DELETE SET NULL,
  to_email        citext NOT NULL,
  subject         text NOT NULL,
  payload         jsonb NOT NULL DEFAULT '{{}}',
  dedupe_key      text UNIQUE,
  status          text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','sending','sent','retry','failed')),
  attempts        smallint NOT NULL DEFAULT 0,
  max_attempts    smallint NOT NULL DEFAULT 5,
  next_attempt_at timestamptz NOT NULL DEFAULT now(),
  locked_at       timestamptz,
  last_error      text,
  created_at      timestamptz NOT NULL DEFAULT now(),
  sent_at         timestamptz,
  failed_at       timestamptz
)""",
    "CREATE INDEX email_outbox_due ON email_outbox (next_attempt_at)"
    " WHERE status IN ('queued','retry')",
    "CREATE INDEX email_outbox_sending ON email_outbox (locked_at) WHERE status = 'sending'",
    "CREATE INDEX email_outbox_failed ON email_outbox (failed_at) WHERE status = 'failed'",
    # ---------------------------------------------------------------- 2.6 alerts and notifications
    """CREATE TABLE alert_rules (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id            uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  template           text NOT NULL CHECK (template IN ('setup_confirmed','enter_ob','enter_fvg',
                     'mitigation_50','setup_invalidated','score_threshold')),
  instruments        text[] NOT NULL CHECK (cardinality(instruments) BETWEEN 1 AND 11),
  timeframe          text NOT NULL CHECK (timeframe IN ('15m','1h','4h')),
  direction          text CHECK (direction IN ('bull','bear')),
  min_score          smallint NOT NULL DEFAULT 60 CHECK (min_score BETWEEN 0 AND 100),
  profile_version_id uuid REFERENCES profile_versions(id),
  cooldown_minutes   smallint NOT NULL DEFAULT 15 CHECK (cooldown_minutes BETWEEN 0 AND 1440),
  paused             boolean NOT NULL DEFAULT false,
  suspended_reason   text CHECK (suspended_reason IN ('plan_limit','plan_assets','plan_custom')),
  watermark_time     timestamptz NOT NULL DEFAULT now(),
  created_at         timestamptz NOT NULL DEFAULT now()
)""",
    "CREATE INDEX alert_rules_active ON alert_rules (timeframe, template)"
    " WHERE NOT paused AND suspended_reason IS NULL",
    """CREATE TABLE alert_deliveries (
  id              bigserial PRIMARY KEY,
  rule_id         uuid REFERENCES alert_rules(id) ON DELETE SET NULL,
  rule_snapshot   jsonb NOT NULL DEFAULT '{}',
  user_id         uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  instrument      text NOT NULL,
  timeframe       text NOT NULL,
  direction       text,
  setup_id        char(32) REFERENCES setups(id),
  event_kind      text NOT NULL CHECK (event_kind IN ('setup_confirmed','zone_touched',
                  'zone_mitigated_50','setup_invalidated','score_crossed')),
  event_ref       text NOT NULL,
  channel         text NOT NULL CHECK (channel IN ('in_app','email')),
  status          text NOT NULL CHECK (status IN ('queued','sent','failed','suppressed')),
  reason          text,
  summary         text NOT NULL,
  email_outbox_id bigint REFERENCES email_outbox(id),
  created_at      timestamptz NOT NULL DEFAULT now(),
  sent_at         timestamptz,
  UNIQUE (rule_id, event_ref, channel)
)""",
    "CREATE INDEX alert_deliveries_history ON alert_deliveries (user_id, created_at DESC)",
    "CREATE INDEX alert_deliveries_cooldown ON alert_deliveries (rule_id, instrument, created_at DESC)"
    " WHERE status <> 'suppressed'",
    """CREATE TABLE notifications (
  id         bigserial PRIMARY KEY,
  user_id    uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title      text NOT NULL,
  body       text NOT NULL,
  link       text,
  created_at timestamptz NOT NULL DEFAULT now(),
  read_at    timestamptz
)""",
    "CREATE INDEX notifications_list ON notifications (user_id, created_at DESC)",
    # ---------------------------------------------------------------- 2.7 admin and operations
    """CREATE TABLE admin_audit_log (
  id          bigserial PRIMARY KEY,
  actor_id    uuid NOT NULL REFERENCES users(id),
  customer_id uuid REFERENCES users(id),
  action      text NOT NULL,
  target_type text NOT NULL,
  target_id   text NOT NULL,
  reason      text,
  details     jsonb NOT NULL DEFAULT '{}',
  at          timestamptz NOT NULL DEFAULT now()
)""",
    "CREATE TRIGGER admin_audit_no_change BEFORE UPDATE OR DELETE ON admin_audit_log"
    " FOR EACH ROW EXECUTE FUNCTION forbid_change()",
    "CREATE TRIGGER admin_audit_no_truncate BEFORE TRUNCATE ON admin_audit_log"
    " FOR EACH STATEMENT EXECUTE FUNCTION forbid_change()",
    # The app role exists wherever deploy/postgres-init ran (stack and test container).
    """DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tradelens_app') THEN
    REVOKE UPDATE, DELETE, TRUNCATE ON admin_audit_log FROM tradelens_app;
  END IF;
END $$""",
    """CREATE TABLE app_errors (
  id         bigserial PRIMARY KEY,
  service    text NOT NULL CHECK (service IN ('api','worker','web','admin-web')),
  level      text NOT NULL DEFAULT 'error' CHECK (level IN ('warning','error','critical')),
  request_id text,
  message    text NOT NULL,
  details    jsonb NOT NULL DEFAULT '{}',
  at         timestamptz NOT NULL DEFAULT now()
)""",
    """CREATE TABLE monitor_alert_state (
  problem_key     text PRIMARY KEY,
  kind            text NOT NULL CHECK (kind IN ('service','series','email','webhook')),
  state           text NOT NULL CHECK (state IN ('ok','down')),
  first_down_at   timestamptz,
  last_checked_at timestamptz NOT NULL DEFAULT now(),
  last_emailed_at timestamptz,
  resolved_at     timestamptz
)""",
]

DOWNGRADE = [
    "DROP TABLE IF EXISTS monitor_alert_state",
    "DROP TABLE IF EXISTS app_errors",
    "DROP TABLE IF EXISTS admin_audit_log",
    "DROP TABLE IF EXISTS notifications",
    "DROP TABLE IF EXISTS alert_deliveries",
    "DROP TABLE IF EXISTS alert_rules",
    "DROP TABLE IF EXISTS email_outbox",
    "DROP TABLE IF EXISTS profile_versions",
    "DROP TABLE IF EXISTS user_profiles",
    "DROP TABLE IF EXISTS refund_requests",
    "DROP TABLE IF EXISTS billing_events",
    "DROP TABLE IF EXISTS payments",
    "DROP TABLE IF EXISTS founder_claims",
    "DROP TABLE IF EXISTS trial_claims",
]


def upgrade() -> None:
    """Create the Increment 3 tables, indexes and guards."""
    for statement in UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    """Drop everything this migration created."""
    for statement in DOWNGRADE:
        op.execute(statement)
