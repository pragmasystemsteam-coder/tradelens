"""Increment 2 schema: accounts, plans, subscriptions, setups, watchlists (DD 2.1-2.3, 2.5, 2.6).

Tables: users, sessions, email_tokens, plans, plan_prices, country_currency, subscriptions
(without the founder-claim FK, which arrives with founder_claims in Increment 3), founder_slots,
setups, setup_revisions, watchlists, watchlist_items. Adds the FK rule_versions.created_by ->
users.

Also relaxes ``liquidity_levels_guard``: an active level's ``kinds`` may change (a second kind
joins the level at the same side and price, or a superseded period kind leaves it; DD 3.4 "at
most one active level per (side, price)"). The level ID uses the first kind at creation (DD 3.8),
so identity is unaffected. Kinds of an ended level and every other identity column stay
immutable; the 0001 CHECK still refuses empty kinds.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-10
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

SETUP_IDENTITY = (
    "id, instrument, asset_class, timeframe, profile, settings_hash, rule_version, scoring_version,"
    " direction, break_event_id, break_type, patterns, sessions, spread, ob_zone_id, fvg_zone_id,"
    " invalidation, opposing_level, counter_trend, origin_time, confirm_time"
)
LEVEL_IDENTITY = (
    "id, instrument, timeframe, settings_hash, rule_version, side, price, structure, origin_time,"
    " confirm_time"
)


def _cols(columns: str, prefix: str) -> str:
    return ", ".join(f"{prefix}.{c.strip()}" for c in columns.split(","))


UPGRADE = [
    # ---------------------------------------------------------------- 2.1 accounts
    """CREATE TABLE users (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email             citext NOT NULL,
  password_hash     text   NOT NULL,
  name              text   NOT NULL DEFAULT '',
  timezone          text   NOT NULL DEFAULT 'UTC',
  trading_style     text   NOT NULL DEFAULT 'intraday' CHECK (trading_style IN ('scalping','intraday','swing')),
  role              text   NOT NULL DEFAULT 'customer' CHECK (role IN ('customer','support','admin')),
  billing_country   char(2),
  totp_secret_enc   text,
  email_verified_at timestamptz,
  created_at        timestamptz NOT NULL DEFAULT now(),
  deleted_at        timestamptz
)""",
    "CREATE UNIQUE INDEX users_email_live ON users (email) WHERE deleted_at IS NULL",
    """CREATE TABLE sessions (
  id           text PRIMARY KEY,
  user_id      uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  kind         text NOT NULL CHECK (kind IN ('app','admin')),
  created_at   timestamptz NOT NULL DEFAULT now(),
  last_seen_at timestamptz NOT NULL DEFAULT now(),
  expires_at   timestamptz NOT NULL,
  revoked_at   timestamptz,
  user_agent   text
)""",
    "CREATE INDEX sessions_live ON sessions (user_id, created_at) WHERE revoked_at IS NULL",
    """CREATE TABLE email_tokens (
  token_hash text PRIMARY KEY,
  user_id    uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  purpose    text NOT NULL CHECK (purpose IN ('verify','reset')),
  expires_at timestamptz NOT NULL,
  used_at    timestamptz
)""",
    "ALTER TABLE rule_versions ADD CONSTRAINT rule_versions_created_by_fkey"
    " FOREIGN KEY (created_by) REFERENCES users(id)",
    # ---------------------------------------------------------------- 2.2 plans
    """CREATE TABLE plans (
  code        text PRIMARY KEY,
  name        text NOT NULL,
  is_paid     boolean NOT NULL,
  is_default  boolean NOT NULL DEFAULT false,
  tier_rank   smallint NOT NULL DEFAULT 0,
  renews_into text REFERENCES plans(code),
  trial_days  smallint NOT NULL DEFAULT 0 CHECK (trial_days >= 0),
  limits      jsonb NOT NULL CHECK (jsonb_typeof(limits) = 'object'),
  sort_order  smallint NOT NULL DEFAULT 0,
  is_public   boolean NOT NULL DEFAULT true,
  active      boolean NOT NULL DEFAULT true,
  CHECK (NOT is_default OR NOT is_paid)
)""",
    "CREATE UNIQUE INDEX plans_one_default ON plans ((true)) WHERE is_default",
    "CREATE UNIQUE INDEX plans_one_trial ON plans ((true)) WHERE trial_days > 0",
    """CREATE TABLE plan_prices (
  plan_code        text NOT NULL REFERENCES plans(code),
  currency         char(3) NOT NULL,
  amount_minor     integer NOT NULL CHECK (amount_minor > 0),
  interval         text NOT NULL CHECK (interval IN ('month','year')),
  razorpay_plan_id text UNIQUE,
  active           boolean NOT NULL DEFAULT true,
  PRIMARY KEY (plan_code, currency)
)""",
    """CREATE TABLE country_currency (
  country  text PRIMARY KEY,
  currency char(3) NOT NULL
)""",
    """CREATE TABLE founder_slots (
  plan_code text PRIMARY KEY REFERENCES plans(code),
  cap       integer NOT NULL CHECK (cap >= 0),
  used      integer NOT NULL DEFAULT 0 CHECK (used >= 0 AND used <= cap)
)""",
    # ---------------------------------------------------------------- 2.3 subscriptions
    """CREATE TABLE subscriptions (
  id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id                  uuid NOT NULL REFERENCES users(id),
  plan_code                text NOT NULL REFERENCES plans(code),
  source                   text NOT NULL CHECK (source IN ('razorpay','trial','manual')),
  currency                 char(3),
  status                   text NOT NULL CHECK (status IN
                           ('created','trialing','active','grace','cancelled','expired','halted','refunded')),
  trial_ends_at            timestamptz,
  current_period_end       timestamptz,
  grace_until              timestamptz,
  cancel_at_period_end     boolean NOT NULL DEFAULT false,
  pending_plan_code        text REFERENCES plans(code),
  pending_effective_at     timestamptz,
  ended_at                 timestamptz,
  razorpay_subscription_id text UNIQUE,
  created_at               timestamptz NOT NULL DEFAULT now(),
  updated_at               timestamptz NOT NULL DEFAULT now(),
  CHECK ((pending_plan_code IS NULL) = (pending_effective_at IS NULL)),
  CHECK (status <> 'trialing' OR (trial_ends_at IS NOT NULL AND razorpay_subscription_id IS NULL))
)""",
    "CREATE UNIQUE INDEX subscriptions_one_live ON subscriptions (user_id)"
    " WHERE status IN ('trialing','active','grace')",
    "CREATE UNIQUE INDEX subscriptions_one_created ON subscriptions (user_id) WHERE status = 'created'",
    "CREATE INDEX subscriptions_due ON subscriptions (pending_effective_at) WHERE pending_plan_code IS NOT NULL",
    "CREATE INDEX subscriptions_trial_end ON subscriptions (trial_ends_at) WHERE status = 'trialing'",
    # ---------------------------------------------------------------- 2.5 setups
    """CREATE TABLE setups (
  id              char(32) PRIMARY KEY,
  instrument      text NOT NULL REFERENCES instruments(code),
  asset_class     text NOT NULL CHECK (asset_class IN ('forex','metal','energy')),
  timeframe       text NOT NULL CHECK (timeframe IN ('15m','1h','4h')),
  profile         text NOT NULL CHECK (profile IN ('scalping','intraday','swing')),
  settings_hash   char(64) NOT NULL,
  rule_version    text NOT NULL REFERENCES rule_versions(version),
  scoring_version text NOT NULL,
  direction       text NOT NULL CHECK (direction IN ('bull','bear')),
  break_event_id  char(32) NOT NULL REFERENCES market_events(id),
  break_type      text NOT NULL CHECK (break_type IN ('bos','choch')),
  patterns        text[] NOT NULL CHECK (patterns <@ ARRAY['bos','choch','displacement','sweep','fvg','ob']),
  sessions        text[] NOT NULL DEFAULT '{}' CHECK (sessions <@ ARRAY['asian','london','new_york']),
  spread          bigint NOT NULL CHECK (spread >= 0),
  q               smallint NOT NULL CHECK (q BETWEEN 0 AND 100),
  c               smallint NOT NULL CHECK (c BETWEEN 0 AND 100),
  combined        smallint NOT NULL CHECK (combined BETWEEN 0 AND 100),
  counter_trend   boolean NOT NULL,
  factors         jsonb NOT NULL,
  explanation     text NOT NULL,
  ob_zone_id      char(32) REFERENCES zones(id),
  fvg_zone_id     char(32) REFERENCES zones(id),
  primary_zone_id char(32) GENERATED ALWAYS AS (COALESCE(ob_zone_id, fvg_zone_id)) STORED,
  invalidation    bigint NOT NULL,
  opposing_level  bigint,
  status          text NOT NULL CHECK (status IN ('confirmed','invalidated','expired')),
  status_time     timestamptz NOT NULL,
  revision        smallint NOT NULL DEFAULT 1,
  ltf_confirmed_at timestamptz,
  origin_time     timestamptz NOT NULL,
  confirm_time    timestamptz NOT NULL,
  CHECK (ob_zone_id IS NOT NULL OR fvg_zone_id IS NOT NULL),
  CHECK ((profile='scalping' AND timeframe='15m') OR (profile='intraday' AND timeframe='1h')
      OR (profile='swing' AND timeframe='4h'))
)""",
    "CREATE INDEX setups_rank ON setups (settings_hash, timeframe, direction, combined DESC, confirm_time DESC, id)"
    " WHERE status = 'confirmed'",
    "CREATE INDEX setups_rank_all ON setups (settings_hash, combined DESC, confirm_time DESC, id)"
    " WHERE status = 'confirmed'",
    "CREATE INDEX setups_instr ON setups (settings_hash, instrument, timeframe, confirm_time DESC)"
    " WHERE status = 'confirmed'",
    "CREATE INDEX setups_asset ON setups (settings_hash, asset_class, combined DESC) WHERE status = 'confirmed'",
    "CREATE INDEX setups_patterns ON setups USING gin (patterns) WHERE status = 'confirmed'",
    "CREATE INDEX setups_sessions ON setups USING gin (sessions) WHERE status = 'confirmed'",
    f"""CREATE FUNCTION setups_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'DELETE on setups is not allowed';
  END IF;
  IF ({_cols(SETUP_IDENTITY, "NEW")}) IS DISTINCT FROM ({_cols(SETUP_IDENTITY, "OLD")}) THEN
    RAISE EXCEPTION 'setup % identity is immutable (scores and status change via setup_revisions)', OLD.id;
  END IF;
  RETURN NEW;
END $$""",
    "CREATE TRIGGER setups_guard BEFORE UPDATE OR DELETE ON setups FOR EACH ROW EXECUTE FUNCTION setups_guard()",
    """CREATE TABLE setup_revisions (
  setup_id       char(32) NOT NULL REFERENCES setups(id),
  rev            smallint NOT NULL,
  q smallint NOT NULL, c smallint NOT NULL, combined smallint NOT NULL,
  status         text NOT NULL CHECK (status IN ('confirmed','invalidated','expired')),
  factors        jsonb NOT NULL,
  reason         text NOT NULL CHECK (reason IN ('created','ltf_confirmation','zone_invalidated','zone_expired')),
  effective_time timestamptz NOT NULL,
  created_at     timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (setup_id, rev)
)""",
    "CREATE TRIGGER setup_revisions_append_only BEFORE UPDATE OR DELETE ON setup_revisions"
    " FOR EACH ROW EXECUTE FUNCTION forbid_change()",
    *[
        f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table}"
        " FOR EACH STATEMENT EXECUTE FUNCTION forbid_change()"
        for table in ("setups", "setup_revisions")
    ],
    # ---------------------------------------------------------------- 2.6 watchlists
    """CREATE TABLE watchlists (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id    uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name       text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id, name)
)""",
    """CREATE TABLE watchlist_items (
  watchlist_id uuid NOT NULL REFERENCES watchlists(id) ON DELETE CASCADE,
  instrument   text NOT NULL REFERENCES instruments(code),
  added_at     timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (watchlist_id, instrument)
)""",
    # ---------------------------------------------------------------- liquidity kinds may grow
    f"""CREATE OR REPLACE FUNCTION liquidity_levels_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'DELETE on liquidity_levels is not allowed';
  END IF;
  IF ({_cols(LEVEL_IDENTITY, "NEW")}) IS DISTINCT FROM ({_cols(LEVEL_IDENTITY, "OLD")})
     OR (NEW.kinds IS DISTINCT FROM OLD.kinds AND OLD.end_time IS NOT NULL) THEN
    RAISE EXCEPTION 'liquidity level % identity is immutable (kinds change only while active)', OLD.id;
  END IF;
  RETURN NEW;
END $$""",
]

RESTORE_LEVEL_GUARD = """CREATE OR REPLACE FUNCTION liquidity_levels_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'DELETE on liquidity_levels is not allowed';
  END IF;
  IF (NEW.id, NEW.instrument, NEW.timeframe, NEW.settings_hash, NEW.rule_version, NEW.kinds, NEW.side,
      NEW.price, NEW.structure, NEW.origin_time, NEW.confirm_time)
     IS DISTINCT FROM
     (OLD.id, OLD.instrument, OLD.timeframe, OLD.settings_hash, OLD.rule_version, OLD.kinds, OLD.side,
      OLD.price, OLD.structure, OLD.origin_time, OLD.confirm_time) THEN
    RAISE EXCEPTION 'liquidity level % identity is immutable (only the end fields change)', OLD.id;
  END IF;
  RETURN NEW;
END $$"""

DOWNGRADE = [
    RESTORE_LEVEL_GUARD,
    "DROP TABLE IF EXISTS watchlist_items",
    "DROP TABLE IF EXISTS watchlists",
    "DROP TABLE IF EXISTS setup_revisions",
    "DROP TABLE IF EXISTS setups",
    "DROP FUNCTION IF EXISTS setups_guard()",
    "DROP TABLE IF EXISTS subscriptions",
    "DROP TABLE IF EXISTS founder_slots",
    "DROP TABLE IF EXISTS country_currency",
    "DROP TABLE IF EXISTS plan_prices",
    "DROP TABLE IF EXISTS plans",
    "ALTER TABLE rule_versions DROP CONSTRAINT IF EXISTS rule_versions_created_by_fkey",
    "DROP TABLE IF EXISTS email_tokens",
    "DROP TABLE IF EXISTS sessions",
    "DROP TABLE IF EXISTS users",
]


def upgrade() -> None:
    """Create the Increment 2 tables, indexes, guards and triggers."""
    for statement in UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    """Drop everything this migration created and restore the 0001 level guard."""
    for statement in DOWNGRADE:
        op.execute(statement)
