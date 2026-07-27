import asyncio
from playwright.async_api import async_playwright

async def scrape_google_ads(domain_or_id: str):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        # Use a realistic viewport to trigger grid rendering
        context = await browser.new_context(viewport={"width": 1280, "height": 900})
        page = await context.new_page()

        # Build initial target URL
        if domain_or_id.startswith("AR"):
            url = f"https://adstransparency.google.com/advertiser/{domain_or_id}?region=anywhere"
        else:
            url = f"https://adstransparency.google.com/?region=anywhere&domain={domain_or_id}"

        print(f"Navigating to {url}...")
        await page.goto(url, wait_until="networkidle")

        # Step 1: If we landed on search results, click into the primary advertiser profile
        advertiser_link = page.locator('a[href*="/advertiser/AR"]').first
        if await advertiser_link.count() > 0 and "/advertiser/AR" not in page.url:
            print("Redirecting to primary Advertiser profile page...")
            await advertiser_link.click()
            await page.wait_for_load_state("networkidle")

        # Step 2: Infinite scroll loop with dynamic wait
        prev_count = 0
        no_change_iterations = 0
        max_no_change = 4  # Stop after 4 consecutive scrolls with 0 new ads

        print("Starting infinite scroll to fetch all creatives...")
        
        while no_change_iterations < max_no_change:
            # Get current creative card count
            creatives = page.locator("creative-preview")
            current_count = await creatives.count()

            print(f"Loaded {current_count} ads so far...")

            # Scroll to bottom of page
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            
            # Critical: Give Google time to fire async RPC requests and append new DOM elements
            await page.wait_for_timeout(2000)

            # Check if new elements were added
            if current_count == prev_count:
                no_change_iterations += 1
            else:
                no_change_iterations = 0
                prev_count = current_count

        print(f"Scrape complete. Total creatives found: {prev_count}")
        
        # Step 3: Extract ad details
        ads_data = []
        cards = await page.locator("creative-preview").all()
        for i, card in enumerate(cards):
            # Extract image/video/text source from individual cards
            html_content = await card.inner_html()
            ads_data.append({"index": i + 1, "html": html_content})

        await browser.close()
        return ads_data

# Run the scraper
# You can pass 'secondfront.com' or their direct Advertiser ID (e.g., 'AR...')
asyncio.run(scrape_google_ads("secondfront.com"))
