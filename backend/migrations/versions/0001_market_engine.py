"""Increment 1 schema: market data and engine output (Detailed Design 2.1 guard, 2.4, 2.5).

Prices are bigint in each instrument's smallest unit (AD-12, DD-5). Append-only rules are
enforced by triggers, because REVOKE does nothing against the table owner (FR-SMC-12).
setups and setup_revisions arrive in 0002 with Increment 2 (DD-8).

Revision ID: 0001
Revises:
Create Date: 2026-11-05
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

TIMEFRAME_CHECK = "CHECK (timeframe IN ('5m','15m','1h','4h','1d'))"

UPGRADE = [
    "CREATE EXTENSION IF NOT EXISTS pgcrypto",
    "CREATE EXTENSION IF NOT EXISTS citext",
    # Guard used by every append-only table.
    """CREATE FUNCTION forbid_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION '% on % is not allowed (append-only)', TG_OP, TG_TABLE_NAME;
END $$""",
    # ---------------------------------------------------------------- 2.4 market data
    """CREATE TABLE trading_calendars (
  code              text PRIMARY KEY,
  tz                text NOT NULL DEFAULT 'America/New_York',
  week_open_dow     smallint NOT NULL CHECK (week_open_dow BETWEEN 0 AND 6),
  week_open_time    time NOT NULL,
  week_close_dow    smallint NOT NULL CHECK (week_close_dow BETWEEN 0 AND 6),
  week_close_time   time NOT NULL,
  daily_break_start time,
  daily_break_end   time,
  closures          jsonb NOT NULL DEFAULT '[]',
  CHECK ((daily_break_start IS NULL) = (daily_break_end IS NULL))
)""",
    """CREATE TABLE instruments (
  code          text PRIMARY KEY,
  asset_class   text NOT NULL CHECK (asset_class IN ('forex','metal','energy')),
  display_name  text NOT NULL,
  price_scale   smallint NOT NULL CHECK (price_scale BETWEEN 0 AND 8),
  pip_scale     smallint NOT NULL,
  normal_spread integer NOT NULL CHECK (normal_spread >= 0),
  calendar_code text NOT NULL REFERENCES trading_calendars(code),
  sort_order    smallint NOT NULL DEFAULT 0,
  active        boolean NOT NULL DEFAULT true,
  CHECK (pip_scale <= price_scale)
)""",
    f"""CREATE TABLE candles (
  instrument  text NOT NULL REFERENCES instruments(code),
  timeframe   text NOT NULL {TIMEFRAME_CHECK},
  open_time   timestamptz NOT NULL,
  o bigint NOT NULL, h bigint NOT NULL, l bigint NOT NULL, c bigint NOT NULL,
  bid_o bigint NOT NULL, bid_h bigint NOT NULL, bid_l bigint NOT NULL, bid_c bigint NOT NULL,
  ask_o bigint NOT NULL, ask_h bigint NOT NULL, ask_l bigint NOT NULL, ask_c bigint NOT NULL,
  tick_volume integer NOT NULL DEFAULT 0,
  source      text NOT NULL DEFAULT 'oanda',
  PRIMARY KEY (instrument, timeframe, open_time),
  CHECK (h >= GREATEST(o, c, l) AND l <= LEAST(o, c, h)),
  CHECK (ask_c >= bid_c AND ask_o >= bid_o)
)""",
    f"""CREATE TABLE series_status (
  instrument       text NOT NULL REFERENCES instruments(code),
  timeframe        text NOT NULL {TIMEFRAME_CHECK},
  last_candle_time timestamptz,
  status           text NOT NULL DEFAULT 'ok' CHECK (status IN ('ok','delayed','backfilling')),
  delayed_since    timestamptz,
  last_checked_at  timestamptz,
  PRIMARY KEY (instrument, timeframe)
)""",
    f"""CREATE TABLE data_gaps (
  id          bigserial PRIMARY KEY,
  instrument  text NOT NULL REFERENCES instruments(code),
  timeframe   text NOT NULL {TIMEFRAME_CHECK},
  gap_from    timestamptz NOT NULL,
  gap_to      timestamptz NOT NULL,
  detected_at timestamptz NOT NULL DEFAULT now(),
  filled_at   timestamptz,
  CHECK (gap_to > gap_from)
)""",
    "CREATE INDEX data_gaps_series ON data_gaps (instrument, timeframe, detected_at DESC)",
    # ---------------------------------------------------------------- 2.5 engine output
    """CREATE TABLE rule_versions (
  version       text PRIMARY KEY,
  settings      jsonb NOT NULL,
  settings_hash char(64) NOT NULL,
  weights       jsonb NOT NULL,
  note          text,
  created_by    uuid,
  created_at    timestamptz NOT NULL DEFAULT now(),
  is_active     boolean NOT NULL DEFAULT false
)""",
    "CREATE UNIQUE INDEX rule_versions_one_active ON rule_versions ((true)) WHERE is_active",
    """CREATE FUNCTION rule_versions_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'DELETE on rule_versions is not allowed';
  END IF;
  IF (NEW.version, NEW.settings, NEW.settings_hash, NEW.weights, NEW.note, NEW.created_by, NEW.created_at)
     IS DISTINCT FROM
     (OLD.version, OLD.settings, OLD.settings_hash, OLD.weights, OLD.note, OLD.created_by, OLD.created_at) THEN
    RAISE EXCEPTION 'rule version % is immutable except is_active', OLD.version;
  END IF;
  RETURN NEW;
END $$""",
    "CREATE TRIGGER rule_versions_guard BEFORE UPDATE OR DELETE ON rule_versions"
    " FOR EACH ROW EXECUTE FUNCTION rule_versions_guard()",
    """CREATE TABLE presets (
  rule_version  text NOT NULL REFERENCES rule_versions(version),
  code          text NOT NULL CHECK (code IN ('default','scalping','intraday','swing')),
  name          text NOT NULL,
  settings      jsonb NOT NULL,
  settings_hash char(64) NOT NULL,
  sort_order    smallint NOT NULL,
  PRIMARY KEY (rule_version, code)
)""",
    # Presets belong to a published rule version: as immutable as the version itself.
    "CREATE TRIGGER presets_guard BEFORE UPDATE OR DELETE ON presets"
    " FOR EACH ROW EXECUTE FUNCTION forbid_change()",
    f"""CREATE TABLE series_state (
  instrument     text NOT NULL REFERENCES instruments(code),
  timeframe      text NOT NULL {TIMEFRAME_CHECK},
  settings_hash  char(64) NOT NULL,
  rule_version   text NOT NULL REFERENCES rule_versions(version),
  engine_schema  smallint NOT NULL DEFAULT 1,
  state          jsonb NOT NULL,
  trend_internal text NOT NULL DEFAULT 'neutral' CHECK (trend_internal IN ('bull','bear','neutral')),
  trend_external text NOT NULL DEFAULT 'neutral' CHECK (trend_external IN ('bull','bear','neutral')),
  as_of          timestamptz NOT NULL,
  updated_at     timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (instrument, timeframe, settings_hash)
)""",
    f"""CREATE TABLE market_events (
  id            char(32) PRIMARY KEY,
  instrument    text NOT NULL REFERENCES instruments(code),
  timeframe     text NOT NULL {TIMEFRAME_CHECK},
  settings_hash char(64) NOT NULL,
  rule_version  text NOT NULL REFERENCES rule_versions(version),
  type          text NOT NULL CHECK (type IN ('swing_high','swing_low','bos','choch','sweep','breakout','displacement')),
  structure     text CHECK (structure IN ('internal','external')),
  direction     text CHECK (direction IN ('bull','bear')),
  level         bigint,
  details       jsonb NOT NULL DEFAULT '{{}}',
  origin_time   timestamptz NOT NULL,
  confirm_time  timestamptz NOT NULL,
  refs          jsonb NOT NULL DEFAULT '{{}}',
  CHECK (confirm_time >= origin_time),
  CHECK ((type IN ('swing_high','swing_low') AND structure IS NOT NULL AND direction IS NULL     AND level IS NOT NULL)
      OR (type IN ('bos','choch')            AND structure IS NOT NULL AND direction IS NOT NULL AND level IS NOT NULL)
      OR (type IN ('sweep','breakout')       AND structure IS NULL     AND direction IS NOT NULL AND level IS NOT NULL)
      OR (type = 'displacement'              AND structure IS NULL     AND direction IS NOT NULL AND level IS NULL))
)""",
    "CREATE INDEX market_events_series ON market_events (instrument, timeframe, settings_hash, confirm_time)",
    "CREATE INDEX market_events_breaks ON market_events (instrument, timeframe, settings_hash, confirm_time)"
    " WHERE type IN ('bos','choch')",
    "CREATE TRIGGER market_events_append_only BEFORE UPDATE OR DELETE ON market_events"
    " FOR EACH ROW EXECUTE FUNCTION forbid_change()",
    f"""CREATE TABLE liquidity_levels (
  id            char(32) PRIMARY KEY,
  instrument    text NOT NULL REFERENCES instruments(code),
  timeframe     text NOT NULL {TIMEFRAME_CHECK},
  settings_hash char(64) NOT NULL,
  rule_version  text NOT NULL REFERENCES rule_versions(version),
  kinds         text[] NOT NULL CHECK (cardinality(kinds) >= 1 AND kinds <@ ARRAY['swing_high','swing_low','eqh','eql',
                'pdh','pdl','pwh','pwl','asian_high','asian_low','london_high','london_low','ny_high','ny_low']),
  side          text NOT NULL CHECK (side IN ('buy','sell')),
  price         bigint NOT NULL,
  structure     text CHECK (structure IN ('internal','external')),
  origin_time   timestamptz NOT NULL,
  confirm_time  timestamptz NOT NULL,
  end_time      timestamptz,
  end_reason    text CHECK (end_reason IN ('swept','breakout','superseded','merged','expired')),
  ended_by      char(32),
  CHECK ((end_time IS NULL) = (end_reason IS NULL))
)""",
    """CREATE FUNCTION liquidity_levels_guard() RETURNS trigger LANGUAGE plpgsql AS $$
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
END $$""",
    "CREATE TRIGGER liquidity_levels_guard BEFORE UPDATE OR DELETE ON liquidity_levels"
    " FOR EACH ROW EXECUTE FUNCTION liquidity_levels_guard()",
    "CREATE INDEX liquidity_active ON liquidity_levels (instrument, timeframe, settings_hash) WHERE end_time IS NULL",
    f"""CREATE TABLE zones (
  id                     char(32) PRIMARY KEY,
  kind                   text NOT NULL CHECK (kind IN ('ob','fvg')),
  instrument             text NOT NULL REFERENCES instruments(code),
  timeframe              text NOT NULL {TIMEFRAME_CHECK},
  settings_hash          char(64) NOT NULL,
  rule_version           text NOT NULL REFERENCES rule_versions(version),
  direction              text NOT NULL CHECK (direction IN ('bull','bear')),
  low                    bigint NOT NULL,
  high                   bigint NOT NULL,
  origin_time            timestamptz NOT NULL,
  confirm_time           timestamptz NOT NULL,
  state                  text NOT NULL CHECK (state IN ('confirmed','touched','mitigated_50','filled','invalidated','expired')),
  state_time             timestamptz NOT NULL,
  retests                smallint NOT NULL DEFAULT 0,
  pre_confirmation_touch boolean NOT NULL DEFAULT false,
  source_event_id        char(32) REFERENCES market_events(id),
  CHECK (high >= low),
  CHECK (kind <> 'fvg' OR high > low),
  CHECK (kind = 'ob' OR NOT pre_confirmation_touch)
)""",
    "CREATE INDEX zones_active ON zones (instrument, timeframe, settings_hash)"
    " WHERE state IN ('confirmed','touched','mitigated_50','filled')",
    "CREATE INDEX zones_range ON zones (instrument, timeframe, settings_hash, confirm_time)",
    """CREATE FUNCTION zones_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'DELETE on zones is not allowed';
  END IF;
  IF (NEW.id, NEW.kind, NEW.instrument, NEW.timeframe, NEW.settings_hash, NEW.rule_version, NEW.direction,
      NEW.low, NEW.high, NEW.origin_time, NEW.confirm_time, NEW.source_event_id)
     IS DISTINCT FROM
     (OLD.id, OLD.kind, OLD.instrument, OLD.timeframe, OLD.settings_hash, OLD.rule_version, OLD.direction,
      OLD.low, OLD.high, OLD.origin_time, OLD.confirm_time, OLD.source_event_id) THEN
    RAISE EXCEPTION 'zone % identity and boundaries are immutable', OLD.id;
  END IF;
  RETURN NEW;
END $$""",
    "CREATE TRIGGER zones_guard BEFORE UPDATE OR DELETE ON zones FOR EACH ROW EXECUTE FUNCTION zones_guard()",
    """CREATE TABLE zone_transitions (
  zone_id     char(32) NOT NULL REFERENCES zones(id),
  state       text NOT NULL CHECK (state IN ('detected','confirmed','touched','mitigated_50','filled','invalidated','expired')),
  candle_time timestamptz NOT NULL,
  PRIMARY KEY (zone_id, state, candle_time)
)""",
    "CREATE TRIGGER zone_transitions_append_only BEFORE UPDATE OR DELETE ON zone_transitions"
    " FOR EACH ROW EXECUTE FUNCTION forbid_change()",
    # Row triggers do not fire on TRUNCATE; block it on every append-only table.
    *[
        f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table}"
        " FOR EACH STATEMENT EXECUTE FUNCTION forbid_change()"
        for table in ("market_events", "zone_transitions", "rule_versions", "presets")
    ],
]

DOWNGRADE = [
    "DROP TABLE IF EXISTS zone_transitions",
    "DROP TABLE IF EXISTS zones",
    "DROP TABLE IF EXISTS liquidity_levels",
    "DROP TABLE IF EXISTS market_events",
    "DROP TABLE IF EXISTS series_state",
    "DROP TABLE IF EXISTS presets",
    "DROP TABLE IF EXISTS rule_versions",
    "DROP TABLE IF EXISTS data_gaps",
    "DROP TABLE IF EXISTS series_status",
    "DROP TABLE IF EXISTS candles",
    "DROP TABLE IF EXISTS instruments",
    "DROP TABLE IF EXISTS trading_calendars",
    "DROP FUNCTION IF EXISTS liquidity_levels_guard()",
    "DROP FUNCTION IF EXISTS zones_guard()",
    "DROP FUNCTION IF EXISTS rule_versions_guard()",
    "DROP FUNCTION IF EXISTS forbid_change()",
]


def upgrade() -> None:
    """Create the Increment 1 tables, indexes, guard functions and triggers."""
    for statement in UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    """Drop everything this migration created (extensions stay; other increments may use them)."""
    for statement in DOWNGRADE:
        op.execute(statement)
