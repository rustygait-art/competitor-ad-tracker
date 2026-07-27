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

async def auto_scroll(page):
    """Scrolls down the page to trigger infinite loading for all ad cards."""
    previous_height = await page.evaluate("document.body.scrollHeight")
    while True:
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(2500)
        new_height = await page.evaluate("document.body.scrollHeight")
        if new_height == previous_height:
            break
        previous_height = new_height

async def scrape_google_ads(competitor_domain, db_path="competitor_ads.db"):
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    clean_domain = competitor_domain.replace("https://", "").replace("http://", "").replace("www.", "").strip("/")
    url = f"https://adstransparency.google.com/?region=anywhere&domain={clean_domain}"
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        print(f"\n--- Scraping ALL ads for domain: {clean_domain} ---")
        try:
            await page.goto(url, wait_until="networkidle", timeout=35000)
            await page.wait_for_timeout(3000)

            # Auto-scroll to load every single ad card available
            print("Auto-scrolling to load entire ad index...")
            await auto_scroll(page)

            ad_cards = await page.query_selector_all("creative-preview")
            print(f"Total creative elements discovered: {len(ad_cards)}")

            if len(ad_cards) == 0:
                print(f"⚠️ No ads found for '{clean_domain}'. Ensure domain name is exact (e.g. 'hubspot.com' vs 'hubspot').")

            for index, card in enumerate(ad_cards):  # Scrapes EVERY ad found (no cap)
                text_content = await card.inner_text()
                if not text_content.strip():
                    text_content = f"Visual Ad Creative from {clean_domain}"

                img_elem = await card.query_selector("img")
                img_url = await img_elem.get_attribute("src") if img_elem else ""

                # Create a unique content hash so every ad is stored individually
                unique_str = f"{clean_domain}_{text_content[:150]}_{img_url}"
                content_hash = hashlib.md5(unique_str.encode('utf-8')).hexdigest()
                ad_id = f"{clean_domain}_{content_hash[:10]}"

                # Check if this exact ad already exists in our database
                cursor.execute("SELECT id FROM ads WHERE id = ?", (ad_id,))
                if cursor.fetchone():
                    print(f"  [-] Ad already in database ({ad_id}). Skipping.")
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
                print(f"  [+] Logged NEW ad [{index+1}/{len(ad_cards)}]: {ad_id}")

            conn.commit()
        except Exception as e:
            print(f"Error scraping {clean_domain}: {e}")
        finally:
            conn.close()
            await browser.close()

if __name__ == "__main__":
    if len(sys.argv) > 1:
        domains_to_scrape = [sys.argv[1]]
    else:
        domains_to_scrape = ["secondfront.com"]
    
    for domain in domains_to_scrape:
        asyncio.run(scrape_google_ads(domain))
