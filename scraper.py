import sys
import os
import sqlite3
import json
import asyncio
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
    import requests

# --- Sidebar: Trigger New Scrape ---
st.sidebar.divider()
st.sidebar.subheader("➕ Scrape New Competitor")
new_domain = st.sidebar.text_input("Enter domain to analyze", placeholder="e.g. hubspot.com")

if st.sidebar.button("🚀 Run Scraper", use_container_width=True):
    if not new_domain.strip():
        st.sidebar.warning("Please enter a valid domain.")
    else:
        # Retrieve secrets
        pat = st.secrets.get("GITHUB_PAT")
        owner = st.secrets.get("GITHUB_OWNER")
        repo = st.secrets.get("GITHUB_REPO")

        if not all([pat, owner, repo]):
            st.sidebar.error("GitHub API secrets not configured properly.")
        else:
            # Trigger GitHub Action via REST API
            api_url = f"https://api.github.com/repos/{owner}/{repo}/actions/workflows/daily_scrape.yml/dispatches"
            headers = {
                "Authorization": f"Bearer {pat}",
                "Accept": "application/vnd.github.v3+json",
            }
            payload = {
                "ref": "main",  # or master
                "inputs": {
                    "competitor_domain": new_domain.strip()
                }
            }
            
            response = requests.post(api_url, headers=headers, json=payload)
            
            if response.status_code == 204:
                st.sidebar.success(f"Scraper triggered for `{new_domain}`! Results will appear in ~2–3 minutes.")
            else:
                st.sidebar.error(f"Error ({response.status_code}): {response.text}")
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

async def scrape_google_ads(competitor_domain, db_path="competitor_ads.db"):
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Clean domain input (e.g., convert https://www.hubspot.com/ -> hubspot.com)
    clean_domain = competitor_domain.replace("https://", "").replace("http://", "").replace("www.", "").strip("/")
    url = f"https://adstransparency.google.com/?region=anywhere&domain={clean_domain}"
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        print(f"Fetching ads for: {clean_domain}...")
        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(4000)

            ad_cards = await page.query_selector_all("creative-preview")
            print(f"Found {len(ad_cards)} creative elements for {clean_domain}.")

            for index, card in enumerate(ad_cards[:10]):
                ad_id = f"{clean_domain}_{datetime.now().strftime('%Y%m%d')}_{index}"

                cursor.execute("SELECT id FROM ads WHERE id = ?", (ad_id,))
                if cursor.fetchone():
                    continue

                text_content = await card.inner_text()
                if not text_content.strip():
                    text_content = f"Visual Ad Creative from {clean_domain}"

                img_elem = await card.query_selector("img")
                img_url = await img_elem.get_attribute("src") if img_elem else ""

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
                print(f"  [+] Logged ad for {clean_domain}: {ad_id}")

            conn.commit()
        except Exception as e:
            print(f"Error scraping {clean_domain}: {e}")
        finally:
            conn.close()
            await browser.close()

if __name__ == "__main__":
    # If a domain was passed via command line (e.g. `python scraper.py hubspot.com`)
    if len(sys.argv) > 1:
        domains_to_scrape = [sys.argv[1]]
    else:
        # Default fallback list for daily scheduled runs
        domains_to_scrape = ["slack.com", "asana.com", "monday.com", "secondfront.com"]
    
    for domain in domains_to_scrape:
        asyncio.run(scrape_google_ads(domain))
