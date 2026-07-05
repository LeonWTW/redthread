-- =============================================================================
-- RedThread — glossary seed (M1 task 1.7, plan docs/plans/001-mvp-plan.md)
-- Starter set of XHS beauty community terms. Idempotent: safe to re-run.
-- Injected into translation prompts; renders the report's Decoder section.
-- Apply: psql -U redthread -d redthread -f server/seeds/glossary.sql
-- =============================================================================

INSERT INTO glossary (term_zh, term_en, note, category) VALUES
    ('避雷', 'mine warning',
     'Warning to avoid a product; the poster flags it as a bad purchase so others do not step on the same "mine".',
     'general'),
    ('平替', 'affordable dupe',
     'Cheaper substitute claimed to perform like a high-end product; core value-hunting behavior.',
     'general'),
    ('成分党', 'ingredient-focused consumer',
     'Consumer segment that judges products by ingredient list and formulation science rather than branding.',
     'skincare'),
    ('种草', 'planted desire',
     'To be persuaded into wanting a product after seeing content; literally "planting grass" that grows into a purchase urge.',
     'general'),
    ('求真', 'authenticity check request',
     'Request for the community to verify whether a product, claim, or seller is genuine before buying.',
     'general'),
    ('拔草', 'desire uprooted',
     'The opposite of 种草: deciding against a purchase and removing it from the wishlist, often after seeing negative reviews.',
     'general'),
    ('踩雷', 'stepped on a mine',
     'Bought a product that turned out to be a dud; personal experience counterpart of a 避雷 warning.',
     'general'),
    ('空瓶', 'empty bottle',
     'Finished a product down to the last drop; posting empties is a strong endorsement of repurchase-worthy products.',
     'skincare'),
    ('回购', 'repurchase',
     'Buying the same product again; a stated repurchase (or "infinite repurchase" 无限回购) signals genuine loyalty.',
     'general'),
    ('早C晚A', 'morning C, evening A',
     'Popular skincare routine: vitamin C products in the morning, retinoid (vitamin A) products at night.',
     'skincare'),
    ('刷酸', 'acid exfoliation',
     'Chemical exfoliation routine using AHA/BHA/PHA acids; frequently discussed with barrier-damage warnings.',
     'skincare'),
    ('妈生皮', 'born-with-it skin',
     'Naturally flawless-looking "skin your mother gave you"; a makeup and skincare goal aesthetic of invisible perfection.',
     'makeup')
ON CONFLICT (term_zh) DO NOTHING;
