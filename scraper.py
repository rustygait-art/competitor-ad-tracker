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
    """Initializes SQLite database and creates table if missing."""
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
    """Uses Gemini 2.5 Flash to categorize and perform gap analysis on ad copy."""
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
    4. "gap_analysis": Identify strategic angles or customer pain points targeted here that competitors frequently miss.
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
    """Dismisses Google consent/cookie overlays blocking the page."""
    try:
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
    """Simulates physical page scrolling to fire Google's AJAX dynamic loading observers."""
    previous_count = 0
    for i in range(max_scrolls):
        for _ in range(4):
            await page.keyboard.press("PageDown")
            await page.wait_for_timeout(300)
            
        await page.wait_for_timeout(2000)
        cards = await page.query_selector_all("creative-preview")
        current_count = len(cards)
        print(f"  Scrolled ({i+1}/{max_scrolls}) — Found {current_count} creative elements so far...")
        
        if current_count == previous_count and i > 2:
            print("  Reached end of available ad stream.")
            break
        previous_count = current_count

async def scrape_google_ads(competitor_domain, db_path="competitor_ads.db"):
    """Launches Playwright, deep-scrolls Google Transparency Center, and logs all ads."""
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    clean_domain = competitor_domain.replace("https://", "").replace("http://", "").replace("www.", "").strip("/")
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
            await page.goto(url, wait_until="domcontentloaded", timeout=40000)
            await page.wait_for_timeout(4000)

            await dismiss_popups(page)
            await deep_scroll_page(page)

            ad_cards = await page.query_selector_all("creative-preview")
            print(f"Total Creative Elements Captured: {len(ad_cards)}")

            for index, card in enumerate(ad_cards):
                text_content = await card.inner_text()
                if not text_content.strip():
                    text_content = f"Visual Ad Creative ({clean_domain})"

                img_elem = await card.query_selector("img")
                img_url = await img_elem.get_attribute("src") if img_elem else ""

                # MD5 hash ensures unique ads are stored without overwriting
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

if __name__ == "__main__":
    init_db()

    # Priority 1: Domain passed via CLI argument
    if len(sys.argv) > 1 and sys.argv[1].strip():
        target_domain = sys.argv[1].strip()
        print(f"🎯 Running targeted scrape for domain: {target_domain}")
        asyncio.run(scrape_google_ads(target_domain))

    # Priority 2: Re-scrape all existing domains from DB (for scheduled runs)
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
            print(f"🔄 Re-scraping {len(existing_domains)} tracked domain(s): {existing_domains}")
            for domain in existing_domains:
                asyncio.run(scrape_google_ads(domain))
        else:
            print("ℹ️ No target domain provided and database is empty. Exiting cleanly.")
            sys.exit(0)
