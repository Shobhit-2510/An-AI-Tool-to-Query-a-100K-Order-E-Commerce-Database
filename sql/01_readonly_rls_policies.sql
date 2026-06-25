-- Project A enabled Row-Level Security (RLS) on every table. RLS blocks all rows
-- for any role that isn't the table owner unless a policy explicitly allows it,
-- so our t2sql_readonly role sees 0 rows until we add read policies.
--
-- Run this ONCE in the Supabase SQL editor (it runs as the table owner). It keeps
-- RLS enabled (Supabase's anon/public API stays locked) but grants our read-only
-- role SELECT access to the dataset tables.

DO $$
DECLARE
    t text;
BEGIN
    FOR t IN SELECT unnest(ARRAY[
        'customers', 'sellers', 'products', 'product_category_name_translation',
        'orders', 'order_items', 'order_payments', 'order_reviews'
    ])
    LOOP
        EXECUTE format('DROP POLICY IF EXISTS t2sql_ro_read ON public.%I;', t);
        EXECUTE format(
            'CREATE POLICY t2sql_ro_read ON public.%I FOR SELECT TO t2sql_readonly USING (true);',
            t
        );
    END LOOP;
END $$;

-- Verify the policies exist:
-- SELECT tablename, policyname, roles FROM pg_policies WHERE policyname = 't2sql_ro_read';
