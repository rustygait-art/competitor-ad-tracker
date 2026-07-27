import sys
import os
import sqlite3
import json
import asyncio
import hashlib
from datetime import datetime
from playwright.async_api import async_playwright
from google import genai
from google.genai import types

def init_db(db_path="competitor_ads.db"):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ads (
            id TEXT PRIMARY KEY,
            competitor TEXT,
            headline TEXT,
            body TEXT,
            format TEXT,
            image_url TEXT,
            theme TEXT,
            funnel_stage TEXT,
            summary TEXT,
            gap_analysis TEXT,
            date_scraped TEXT
        )
    """)
    conn.commit()
    conn.close()

def analyze_ad_with_gemini(competitor, ad_copy):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return {
            "theme": "General",
            "funnel_stage": "Top of Funnel",
            "summary": ad_copy[:120],
            "gap_analysis": "GEMINI_API_KEY missing."
        }

    client = genai.Client(api_key=api_key)
    prompt = f"""
    You are a high-level B2B marketing strategist analyzing competitor ads.
    Competitor Domain: {competitor}
    Ad Content: {ad_copy}

    Perform an ad classification and return strictly valid JSON matching this schema:
    1. "theme": Primary messaging angle (e.g., Social Proof/Case Study, Feature Highlight, Pricing/Offer, Direct Comparison, Pain Point/Compliance).
    2. "funnel_stage": Target funnel level ("Top of Funnel", "Middle of Funnel", or "Bottom of Funnel").
    3. "summary": A 1-2 sentence executive summary of the primary hook.
    4. "gap_analysis": Strategic angle or pain point targeted.
    """

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json")
        )
        return json.loads(response.text)
    except Exception as e:
        print(f"Gemini API Error: {e}")
        return {
            "theme": "General",
            "funnel_stage": "Top of Funnel",
            "summary": ad_copy[:120],
            "gap_analysis": "Error running AI analysis."
        }

async def dismiss_popups(page):
    """Dismisses any Google Cookie/Consent overlays blocking the viewport."""
    try:
        # Common selectors for Google consent buttons
        buttons = await page.query_selector_all("button")
        for btn in buttons:
            txt = (await btn.inner_text()).lower()
            if "accept" in txt or "agree" in txt or "i agree" in txt:
                await btn.click()
                print("  [+] Dismissed consent popup.")
                await page.wait_for_timeout(1000)
                break
    except Exception:
        pass

async def deep_scroll_page(page, max_scrolls=12):
    """Simulates physical page scrolling to fire Google's internal AJAX observers."""
    previous_count = 0
    
    for i in range(max_scrolls):
        # Press PageDown multiple times to trigger dynamic observers
        for _ in range(4):
            await page.keyboard.press("PageDown")
            await page.wait_for_timeout(300)
            
        # Give Google time to return dynamic ad requests
        await page.wait_for_timeout(2000)
        
        cards = await page.query_selector_all("creative-preview")
        current_count = len(cards)
        print(f"  Scrolled ({i+1}/{max_scrolls}) — Found {current_count} ads so far...")
        
        # Stop scrolling if no new ads loaded after consecutive attempts
        if current_count == previous_count and i > 2:
            print("  Reached end of ad stream.")
            break
        previous_count = current_count

async def scrape_google_ads(competitor_domain, db_path="competitor_ads.db"):
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    clean_domain = competitor_domain.replace("https://", "").replace("http://", "").replace("www.", "").strip("/")
    
    # URL format covering all regions and ad formats
    url = f"https://adstransparency.google.com/?region=anywhere&domain={clean_domain}"
    
    async with async_playwright() as p:
        # Launch Chromium with explicit screen size to ensure standard layout rendering
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1440, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        print(f"\n--- Deep Scraping ALL ads for: {clean_domain} ---")
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=40000)
            await page.wait_for_timeout(4000)

            # 1. Dismiss overlays
            await dismiss_popups(page)

            # 2. Perform interactive deep scroll
            await deep_scroll_page(page)

            # 3. Harvest creative elements
            ad_cards = await page.query_selector_all("creative-preview")
            print(f"Total Creative Elements Captured: {len(ad_cards)}")

            for index, card in enumerate(ad_cards):
                text_content = await card.inner_text()
                if not text_content.strip():
                    text_content = f"Visual Ad Creative ({clean_domain})"

                img_elem = await card.query_selector("img")
                img_url = await img_elem.get_attribute("src") if img_elem else ""

                # Create unique ID per creative
                unique_str = f"{clean_domain}_{text_content[:150]}_{img_url}"
                content_hash = hashlib.md5(unique_str.encode('utf-8')).hexdigest()
                ad_id = f"{clean_domain}_{content_hash[:10]}"

                cursor.execute("SELECT id FROM ads WHERE id = ?", (ad_id,))
                if cursor.fetchone():
                    print(f"  [-] Ad already exists in DB: {ad_id}")
                    continue

                ai_data = analyze_ad_with_gemini(clean_domain, text_content)

                cursor.execute("""
                    INSERT OR REPLACE INTO ads 
                    (id, competitor, headline, body, format, image_url, theme, funnel_stage, summary, gap_analysis, date_scraped)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    ad_id,
                    clean_domain,
                    text_content.split('\n')[0][:100],
                    text_content,
                    "Image/Text",
                    img_url,
                    ai_data.get("theme", "General"),
                    ai_data.get("funnel_stage", "Top of Funnel"),
                    ai_data.get("summary", ""),
                    ai_data.get("gap_analysis", ""),
                    datetime.now().strftime("%Y-%m-%d")
                ))
                print(f"  [+] Logged Ad [{index+1}/{len(ad_cards)}]: {ad_id}")

            conn.commit()
        except Exception as e:
            print(f"Error scraping {clean_domain}: {e}")
        finally:
            conn.close()
            await browser.close()

# (Keep all existing helper functions: init_db, analyze_ad_with_gemini, dismiss_popups, deep_scroll_page, scrape_google_ads)

if __name__ == "__main__":
    if len(sys.argv) > 1:
        domain_to_scrape = sys.argv[1]
        asyncio.run(scrape_google_ads(domain_to_scrape))
    else:
        print("❌ Error: No target domain provided.")
        print("Usage: python scraper.py <domain_name>")
        sys.exit(1)
