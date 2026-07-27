import os
import sqlite3
import json
import asyncio
from datetime import datetime
from playwright.async_api import async_playwright
from google import genai
from google.genai import types

# 1. Initialize SQLite Database
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

# 2. Gemini AI Analysis Engine
def analyze_ad_with_gemini(competitor, ad_copy):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Warning: GEMINI_API_KEY not found. Skipping AI categorization.")
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
    4. "gap_analysis": Identify if this ad targets a strategic angle or customer pain point that competitors frequently miss.
    """

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json"
            )
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

# 3. Playwright Scraper
async def scrape_google_ads(competitor_domain, db_path="competitor_ads.db"):
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    url = f"https://adstransparency.google.com/?region=anywhere&domain={competitor_domain}"
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        print(f"Fetching ads for: {competitor_domain}...")
        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(4000)

            # Query ad elements from Google Transparency Center UI
            ad_cards = await page.query_selector_all("creative-preview")
            print(f"Found {len(ad_cards)} creative elements for {competitor_domain}.")

            for index, card in enumerate(ad_cards[:10]):  # Top 10 ads per run
                ad_id = f"{competitor_domain}_{datetime.now().strftime('%Y%m%d')}_{index}"

                # Skip if ad already exists in database
                cursor.execute("SELECT id FROM ads WHERE id = ?", (ad_id,))
                if cursor.fetchone():
                    continue

                text_content = await card.inner_text()
                if not text_content.strip():
                    text_content = f"Visual Ad Creative from {competitor_domain}"

                # Extract preview image link if available
                img_elem = await card.query_selector("img")
                img_url = await img_elem.get_attribute("src") if img_elem else ""

                # Run free Gemini analysis
                ai_data = analyze_ad_with_gemini(competitor_domain, text_content)

                cursor.execute("""
                    INSERT OR REPLACE INTO ads 
                    (id, competitor, headline, body, format, image_url, theme, funnel_stage, summary, gap_analysis, date_scraped)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    ad_id,
                    competitor_domain,
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
                print(f"  [+] Logged ad: {ad_id}")

            conn.commit()
        except Exception as e:
            print(f"Error scraping {competitor_domain}: {e}")
        finally:
            conn.close()
            await browser.close()

if __name__ == "__main__":
    # Configure target competitor domains here:
    COMPETITORS = ["slack.com", "asana.com", "monday.com"]
    
    for domain in COMPETITORS:
        asyncio.run(scrape_google_ads(domain))
