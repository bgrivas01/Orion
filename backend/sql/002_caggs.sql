-- Continuous aggregate for gauge trend sparklines.
-- MUST be applied one statement at a time, outside a transaction block:
-- TimescaleDB rejects CREATE MATERIALIZED VIEW ... WITH (timescaledb.continuous)
-- inside a transaction.
CREATE MATERIALIZED VIEW IF NOT EXISTS gauge_hourly
WITH (timescaledb.continuous) AS
SELECT site_id,
       time_bucket('1 hour', time) AS bucket,
       avg(gauge_height_ft)        AS avg_ft,
       max(gauge_height_ft)        AS max_ft
FROM gauge_readings
GROUP BY site_id, bucket
WITH NO DATA;
SELECT add_continuous_aggregate_policy('gauge_hourly', start_offset => INTERVAL '3 days', end_offset => INTERVAL '30 minutes', schedule_interval => INTERVAL '15 minutes', if_not_exists => TRUE);
