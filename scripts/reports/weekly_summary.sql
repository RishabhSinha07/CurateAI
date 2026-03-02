-- CurateAI Weekly Summary Report
-- Run via: docker compose exec db psql -U postgres -d curateai -f /app/scripts/reports/weekly_summary.sql
-- Or: psql $DATABASE_URL -f scripts/reports/weekly_summary.sql

-- ============================================
-- 1. Sessions per Tenant (last 7 days)
-- ============================================
SELECT
    t.name AS tenant,
    t.slug,
    COUNT(cs.id) AS sessions,
    COUNT(DISTINCT DATE(cs.created_at)) AS active_days
FROM chat_sessions cs
JOIN tenants t ON cs.tenant_id = t.id
WHERE cs.created_at >= NOW() - INTERVAL '7 days'
GROUP BY t.name, t.slug
ORDER BY sessions DESC;


-- ============================================
-- 2. Top Clicked Products (last 7 days)
-- ============================================
SELECT
    p.name AS product,
    p.brand,
    COUNT(*) AS clicks,
    COUNT(DISTINCT pe.session_id) AS unique_sessions
FROM product_events pe
JOIN products p ON pe.product_id = p.id
WHERE pe.event_type = 'click'
  AND pe.created_at >= NOW() - INTERVAL '7 days'
GROUP BY p.name, p.brand
ORDER BY clicks DESC
LIMIT 20;


-- ============================================
-- 3. Conversion Funnel (last 7 days)
-- ============================================
SELECT
    event_type,
    COUNT(*) AS count,
    COUNT(DISTINCT session_id) AS unique_sessions
FROM product_events
WHERE created_at >= NOW() - INTERVAL '7 days'
GROUP BY event_type
ORDER BY
    CASE event_type
        WHEN 'click' THEN 1
        WHEN 'add_to_cart' THEN 2
        WHEN 'purchase' THEN 3
    END;


-- ============================================
-- 4. Average Search Quality (last 7 days)
-- ============================================
SELECT
    COUNT(*) AS total_searches,
    ROUND(AVG((cs.extracted_context->'_search_metadata'->>'result_count')::int), 1) AS avg_results,
    ROUND(AVG((cs.extracted_context->'_search_metadata'->>'top_similarity')::float), 3) AS avg_top_similarity,
    COUNT(*) FILTER (
        WHERE (cs.extracted_context->'_search_metadata'->>'low_confidence_search')::boolean = true
    ) AS low_confidence_searches
FROM chat_sessions cs
WHERE cs.extracted_context->'_search_metadata' IS NOT NULL
  AND cs.updated_at >= NOW() - INTERVAL '7 days';


-- ============================================
-- 5. Domain Popularity (last 7 days)
-- ============================================
SELECT
    cs.current_domain_slug AS domain,
    COUNT(*) AS sessions,
    COUNT(*) FILTER (WHERE cs.status = 'completed') AS completed,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE cs.status = 'completed') / NULLIF(COUNT(*), 0),
        1
    ) AS completion_pct
FROM chat_sessions cs
WHERE cs.created_at >= NOW() - INTERVAL '7 days'
  AND cs.current_domain_slug IS NOT NULL
GROUP BY cs.current_domain_slug
ORDER BY sessions DESC;
