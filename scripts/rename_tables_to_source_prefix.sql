-- Rename existing non-prefixed OHLCV tables to source-prefixed names (polygon_...)
-- and update ticker_registry accordingly. Safe to run multiple times.

DO $$
DECLARE
    rec RECORD;
    old_name TEXT;
    new_name TEXT;
BEGIN
    FOR rec IN
        SELECT symbol, table_name, data_type, timeframe
        FROM ticker_registry
        WHERE data_type = 'ohlcv'
    LOOP
        old_name := rec.table_name;
        -- Only rename tables that are not already source-prefixed
        IF position('_' in old_name) > 0 AND left(old_name, 8) != 'polygon_' THEN
            new_name := 'polygon_' || rec.table_name;
            -- Check if old table exists and new does not
            IF to_regclass(old_name) IS NOT NULL AND to_regclass(new_name) IS NULL THEN
                EXECUTE format('ALTER TABLE %I RENAME TO %I', old_name, new_name);
                -- Update registry
                UPDATE ticker_registry
                SET table_name = new_name,
                    last_updated = NOW()
                WHERE symbol = rec.symbol
                  AND data_type = rec.data_type
                  AND timeframe = rec.timeframe;
            END IF;
        END IF;
    END LOOP;
END$$ LANGUAGE plpgsql;
