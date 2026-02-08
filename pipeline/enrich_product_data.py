"""
Enrich product data by scraping Ingredients and How-to-take tabs from
Wellbeing Nutrition product pages using Playwright (headless Chromium).

The site renders tab content with JavaScript, so a real browser is required.

Run with:
    python -m pipeline.enrich_product_data              # enrich all products
    python -m pipeline.enrich_product_data --limit 5    # test with 5 products
    python -m pipeline.enrich_product_data --dry-run    # print tabs found, don't write
"""

import argparse
import asyncio
import json
import re
from pathlib import Path

from playwright.async_api import async_playwright, Page, TimeoutError as PwTimeout

INPUT_JSON = Path(__file__).resolve().parent / "data" / "scraped_products_v2.json"
OUTPUT_JSON = Path(__file__).resolve().parent / "data" / "scraped_products_v3.json"

# Tab labels we want → attribute key in the output JSON.
TAB_LABELS = {
    "ingredients": "ingredients_text",
    "how to take": "how_to_take",
    "how to use": "how_to_take",  # alternate wording on some pages
}

# Be respectful: pause between page loads.
PAGE_DELAY_SECONDS = 2


def _clean(text: str) -> str:
    """Collapse whitespace, keep line breaks readable."""
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


async def extract_tabs(page: Page, url: str) -> dict[str, str]:
    """
    Navigate to *url*, read tab content from the Wellbeing Nutrition product
    page and return a mapping of attribute-key → extracted text.

    The site structure:
      - Tab links: ``li.tab_heading a`` with ``href="#tab_1"``, ``"#tab2"``, etc.
      - Tab panels: ``div.tab-content`` with matching ``id``.
    """
    result: dict[str, str] = {}

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        await page.wait_for_timeout(3000)
    except (PwTimeout, Exception) as exc:
        print(f"    ⚠  Could not load page: {exc}")
        return result

    # --- Strategy 1: li.tab_heading links + div.tab-content panels -------------
    tab_data = await page.evaluate("""() => {
        const links = document.querySelectorAll('li.tab_heading a');
        const tabs = {};
        for (const a of links) {
            const label = a.textContent.trim().toLowerCase();
            const href = a.getAttribute('href') || '';
            const panelId = href.replace('#', '');
            const panel = panelId ? document.getElementById(panelId) : null;
            if (panel) {
                tabs[label] = panel.textContent.trim();
            }
        }
        return tabs;
    }""")

    for tab_label, attr_key in TAB_LABELS.items():
        if attr_key in result:
            continue
        text = tab_data.get(tab_label, "")
        if text:
            result[attr_key] = _clean(text)

    # --- Strategy 2 (fallback): look for collapsible sections ------------------
    if not result:
        collapsible_data = await page.evaluate("""() => {
            const triggers = document.querySelectorAll('.collapsible-trigger');
            const sections = {};
            for (const btn of triggers) {
                const label = btn.textContent.trim().toLowerCase();
                const content = btn.nextElementSibling;
                if (content) {
                    sections[label] = content.textContent.trim();
                }
            }
            return sections;
        }""")

        for tab_label, attr_key in TAB_LABELS.items():
            if attr_key in result:
                continue
            text = collapsible_data.get(tab_label, "")
            if text:
                result[attr_key] = _clean(text)

    return result


async def enrich_products(
    limit: int | None = None,
    dry_run: bool = False,
) -> None:
    """Main enrichment loop."""
    with open(INPUT_JSON, encoding="utf-8") as f:
        products: list[dict] = json.load(f)

    total = len(products)
    to_process = products[:limit] if limit else products
    print(f"Loaded {total} products from {INPUT_JSON.name}")
    print(f"Will process {len(to_process)} products\n")

    enriched_count = 0
    skipped_count = 0

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()

        for i, product in enumerate(to_process, 1):
            url = product.get("product_url")
            name = product.get("name", "Unknown")

            if not url:
                print(f"  [{i}/{len(to_process)}] {name} — no URL, skipping")
                skipped_count += 1
                continue

            print(f"  [{i}/{len(to_process)}] {name}...", end=" ", flush=True)

            tab_data = await extract_tabs(page, url)

            if tab_data:
                if not dry_run:
                    attrs = product.setdefault("attributes", {})
                    attrs.update(tab_data)
                enriched_count += 1
                tabs_found = ", ".join(tab_data.keys())
                # Show a preview of ingredient text length.
                ing_len = len(tab_data.get("ingredients_text", ""))
                print(f"✓ ({tabs_found}) [ingredients: {ing_len} chars]")
            else:
                print("— no tabs found")
                skipped_count += 1

            await asyncio.sleep(PAGE_DELAY_SECONDS)

        await browser.close()

    print(f"\nEnriched: {enriched_count}  |  Skipped/no-tabs: {skipped_count}")

    if dry_run:
        print("(dry-run — no file written)")
        return

    # Write the full product list (including un-processed products when limit is set).
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(products, f, indent=2, ensure_ascii=False)

    print(f"Saved enriched data to {OUTPUT_JSON}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Enrich product data with ingredient tabs")
    parser.add_argument("--limit", type=int, default=None, help="Process only first N products")
    parser.add_argument("--dry-run", action="store_true", help="Print results without writing file")
    args = parser.parse_args()

    asyncio.run(enrich_products(limit=args.limit, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
