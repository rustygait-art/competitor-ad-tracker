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
            "gap_analysis": "GEMINI_API_KEY environment variable missing."
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
    4. "gap_analysis": Strategic angle or customer pain point targeted here.
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
    try:
        buttons = await page.query_selector_all("button")
        for btn in buttons:
            txt = (await btn.inner_text()).lower()
            if "accept" in txt or "agree" in txt or "i agree" in txt:
                await btn.click()
                await page.wait_for_timeout(1000)
                break
    except Exception:
        pass

async def navigate_to_advertiser_profile(page, clean_domain):
    """If we land on a search summary page, click through to the full Advertiser Profile."""
    try:
        # Look for the profile card/link pointing to the full advertiser catalog
        advertiser_link = page.locator('a[href*="/advertiser/AR"]').first
        if await advertiser_link.count() > 0:
            print("  [↗] Click-through found! Redirecting to full Advertiser Profile page...")
            await advertiser_link.click()
            await page.wait_for_load_state("networkidle")
            await page.wait_for_timeout(3000)
    except Exception as e:
        print(f"  [i] Directly on target page or no redirect link: {e}")

async def deep_scroll_page(page, max_idle_scrolls=5):
    """Scrolls dynamically until Google stops appending new creative cards."""
    previous_count = 0
    idle_count = 0
    scroll_iteration = 0

    while idle_count < max_idle_scrolls:
        scroll_iteration += 1
        
        # Press PageDown to trigger dynamic JSObservers
        for _ in range(6):
            await page.keyboard.press("PageDown")
            await page.wait_for_timeout(250)

        # Scroll to absolute bottom
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(2500)  # Wait for Google's async SearchCreatives RPC call

        cards = await page.query_selector_all("creative-preview")
        current_count = len(cards)
        print(f"  Scroll #{scroll_iteration} — Total ads loaded: {current_count}")

        if current_count == previous_count:
            idle_count += 1
        else:
            idle_count = 0
            previous_count = current_count

        if scroll_iteration >= 40:  # Safety ceiling
            print("  Reached maximum scroll ceiling.")
            break

async def scrape_google_ads(competitor_domain, db_path="competitor_ads.db"):
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    clean_domain = competitor_domain.replace("https://", "").replace("http://", "").replace("www.", "").strip("/")
    
    # Check if a direct Advertiser ID (AR...) was passed or a standard domain name
    if clean_domain.startswith("AR"):
        url = f"https://adstransparency.google.com/advertiser/{clean_domain}?region=anywhere"
    else:
        url = f"https://adstransparency.google.com/?region=anywhere&domain={clean_domain}"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1440, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        print(f"\n--- Deep Scraping ALL ads for: {clean_domain} ---")
        try:
            await page.goto(url, wait_until="networkidle", timeout=45000)
            await page.wait_for_timeout(3000)

            await dismiss_popups(page)
            
            # Step 1: Click through from Search Summary to Full Profile if necessary
            await navigate_to_advertiser_profile(page, clean_domain)

            # Step 2: Infinite scroll down the entire creative catalog
            await deep_scroll_page(page)

            # Step 3: Parse and analyze every card found
            ad_cards = await page.query_selector_all("creative-preview")
            print(f"\n✅ Total Creative Elements Captured: {len(ad_cards)}")

            for index, card in enumerate(ad_cards):
                text_content = await card.inner_text()
                if not text_content.strip():
                    text_content = f"Visual Ad Creative ({clean_domain})"

                img_elem = await card.query_selector("img")
                img_url = await img_elem.get_attribute("src") if img_elem else ""

                unique_str = f"{clean_domain}_{text_content[:150]}_{img_url}"
                content_hash = hashlib.md5(unique_str.encode('utf-8')).hexdigest()
                ad_id = f"{clean_domain}_{content_hash[:10]}"

                cursor.execute("SELECT id FROM ads WHERE id = ?", (ad_id,))
                if cursor.fetchone():
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

if __name__ == "__main__":
    init_db()

    if len(sys.argv) > 1 and sys.argv[1].strip():
        target_domain = sys.argv[1].strip()
        print(f"🎯 Targeted scrape for domain: {target_domain}")
        asyncio.run(scrape_google_ads(target_domain))
    else:
        conn = sqlite3.connect("competitor_ads.db")
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT DISTINCT competitor FROM ads")
            rows = cursor.fetchall()
            existing_domains = [r[0] for r in rows if r[0]]
        except Exception:
            existing_domains = []
        finally:
            conn.close()

        if existing_domains:
            print(f"🔄 Re-scraping tracked domain(s): {existing_domains}")
            for domain in existing_domains:
                asyncio.run(scrape_google_ads(domain))
        else:
            print("ℹ️ Database is empty and no domain was specified.")
            sys.exit(0)
