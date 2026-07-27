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
    # Automatically purge default/seed data
    cursor.execute("""
        DELETE FROM ads 
        WHERE competitor IN ('Slack', 'Asana', 'Monday.com', 'Example', 'default') 
           OR competitor LIKE '%sample%'
    """)
    conn.commit()
    conn.close()

def analyze_ad_with_gemini(competitor, ad_copy, ad_format):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return {
            "theme": "General Brand Awareness",
            "funnel_stage": "Top of Funnel",
            "summary": ad_copy[:150] if ad_copy.strip() else f"Visual {ad_format} creative.",
            "gap_analysis": "GEMINI_API_KEY missing in execution environment."
        }

    client = genai.Client(api_key=api_key)
    prompt = f"""
    You are a B2B competitive intelligence strategist analyzing an ad campaign.
    Competitor Domain: {competitor}
    Ad Format: {ad_format}
    Extracted Text / Context: {ad_copy if ad_copy.strip() else 'Visual creative with minimal on-screen text.'}

    Return strictly valid JSON with these keys:
    1. "theme": Primary messaging angle (e.g., Security & Compliance, Case Study, Product Feature, Direct Comparison, Cost/ROI).
    2. "funnel_stage": "Top of Funnel", "Middle of Funnel", or "Bottom of Funnel".
    3. "summary": Executive summary of the core value proposition (1-2 sentences).
    4. "gap_analysis": Strategic intent or customer pain point targeted here.
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
            "theme": "Product/Brand Showcase",
            "funnel_stage": "Top of Funnel",
            "summary": ad_copy[:150] if ad_copy.strip() else "Visual ad creative.",
            "gap_analysis": "Unable to parse AI response."
        }

async def detect_ad_format(card):
    video_elem = await card.query_selector("video, iframe[src*='youtube']")
    if video_elem:
        return "Video Ad"
    
    img_elem = await card.query_selector("img")
    if img_elem:
        return "Image / Visual Ad"
    
    return "Text / Search Ad"

async def extract_google_creative_id(card, index, clean_domain):
    """Extracts Google's native CR... ID from the element, or falls back to an indexed hash."""
    try:
        # Check for Google's native creative link/attribute
        link_elem = await card.query_selector('a[href*="/creative/"]')
        if link_elem:
            href = await link_elem.get_attribute("href")
            if "/creative/" in href:
                cr_id = href.split("/creative/")[1].split("?")[0]
                return f"{clean_domain}_{cr_id}"
    except Exception:
        pass

    # Fallback: Hash outer HTML + Index to guarantee uniqueness per placement
    html = await card.inner_html()
    content_hash = hashlib.md5(f"{clean_domain}_{index}_{html[:200]}".encode('utf-8')).hexdigest()
    return f"{clean_domain}_card_{index}_{content_hash[:6]}"

async def dismiss_popups(page):
    try:
        buttons = await page.query_selector_all("button")
        for btn in buttons:
            txt = (await btn.inner_text()).lower()
            if any(term in txt for term in ["accept", "agree", "i agree"]):
                await btn.click()
                await page.wait_for_timeout(1000)
                break
    except Exception:
        pass

async def navigate_to_advertiser_profile(page):
    try:
        advertiser_link = page.locator('a[href*="/advertiser/AR"]').first
        if await advertiser_link.count() > 0:
            print("  [↗] Navigating to full Advertiser Profile page...")
            await advertiser_link.click()
            await page.wait_for_load_state("networkidle")
            await page.wait_for_timeout(3000)
    except Exception as e:
        print(f"  [i] Directly on advertiser page: {e}")

async def deep_scroll_page(page, max_idle_scrolls=5):
    previous_count = 0
    idle_count = 0
    scroll_iteration = 0

    while idle_count < max_idle_scrolls:
        scroll_iteration += 1
        
        for _ in range(5):
            await page.keyboard.press("PageDown")
            await page.wait_for_timeout(200)

        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(2500)

        cards = await page.query_selector_all("creative-preview")
        current_count = len(cards)
        print(f"  Scroll #{scroll_iteration} — Total placements loaded in DOM: {current_count}")

        if current_count == previous_count:
            idle_count += 1
        else:
            idle_count = 0
            previous_count = current_count

        if scroll_iteration >= 35:
            break

async def scrape_google_ads(competitor_domain, db_path="competitor_ads.db"):
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    clean_domain = competitor_domain.replace("https://", "").replace("http://", "").replace("www.", "").strip("/")
    
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

        print(f"\n--- Scraping ALL ads for: {clean_domain} ---")
        try:
            await page.goto(url, wait_until="networkidle", timeout=45000)
            await page.wait_for_timeout(3000)

            await dismiss_popups(page)
            await navigate_to_advertiser_profile(page)
            await deep_scroll_page(page)

            ad_cards = await page.query_selector_all("creative-preview")
            print(f"\n✅ Total Raw Ad Placements Captured: {len(ad_cards)}")

            saved_count = 0
            for index, card in enumerate(ad_cards):
                # Scroll individual card into view to trigger lazy loading
                await card.scroll_into_view_if_needed()
                
                ad_id = await extract_google_creative_id(card, index, clean_domain)
                text_content = await card.inner_text()
                ad_format = await detect_ad_format(card)

                if not text_content.strip():
                    text_content = f"{ad_format} ({clean_domain})"

                img_elem = await card.query_selector("img")
                img_url = await img_elem.get_attribute("src") if img_elem else ""

                # Check if this exact Google Creative ID already exists
                cursor.execute("SELECT id FROM ads WHERE id = ?", (ad_id,))
                if cursor.fetchone():
                    continue

                ai_data = analyze_ad_with_gemini(clean_domain, text_content, ad_format)

                cursor.execute("""
                    INSERT OR REPLACE INTO ads 
                    (id, competitor, headline, body, format, image_url, theme, funnel_stage, summary, gap_analysis, date_scraped)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    ad_id,
                    clean_domain,
                    text_content.split('\n')[0][:100],
                    text_content,
                    ad_format,
                    img_url,
                    ai_data.get("theme", "General"),
                    ai_data.get("funnel_stage", "Top of Funnel"),
                    ai_data.get("summary", ""),
                    ai_data.get("gap_analysis", ""),
                    datetime.now().strftime("%Y-%m-%d")
                ))
                saved_count += 1
                print(f"  [+] Logged Ad Placement [{index+1}/{len(ad_cards)}] | ID: {ad_id}")

            conn.commit()
            print(f"\n🎉 Scraping Complete! Saved {saved_count} new ads out of {len(ad_cards)} total placements.")
        except Exception as e:
            print(f"Error scraping {clean_domain}: {e}")
        finally:
            conn.close()
            await browser.close()

if __name__ == "__main__":
    init_db()

    if len(sys.argv) > 1 and sys.argv[1].strip():
        target = sys.argv[1].strip()
        asyncio.run(scrape_google_ads(target))
    else:
        conn = sqlite3.connect("competitor_ads.db")
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT competitor FROM ads")
        rows = cursor.fetchall()
        domains = [r[0] for r in rows if r[0]]
        conn.close()

        for domain in domains:
            asyncio.run(scrape_google_ads(domain))
