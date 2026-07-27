import streamlit as st
import sqlite3
import pandas as pd
import requests
import os
import json
from google import genai

st.set_page_config(page_title="Competitor Ad Intelligence", layout="wide")

@st.cache_data(ttl=5)
def load_data():
    conn = sqlite3.connect("competitor_ads.db")
    cursor = conn.cursor()
    # Purge default seed entries if present
    cursor.execute("""
        DELETE FROM ads 
        WHERE competitor IN ('Slack', 'Asana', 'Monday.com', 'Example', 'default') 
           OR competitor LIKE '%sample%'
    """)
    conn.commit()
    
    try:
        df = pd.read_sql_query("SELECT * FROM ads", conn)
    except Exception:
        df = pd.DataFrame(columns=[
            "id", "competitor", "headline", "body", "format", 
            "image_url", "theme", "funnel_stage", "summary", 
            "gap_analysis", "date_scraped"
        ])
    conn.close()
    return df

def generate_competitor_rollup(competitor_name, ads_df):
    """Uses Gemini to generate a high-level strategic rollup across all ads for a competitor."""
    api_key = os.environ.get("GEMINI_API_KEY") or st.secrets.get("GEMINI_API_KEY")
    if not api_key:
        return "⚠️ **GEMINI_API_KEY Missing:** Add your Gemini API key to Streamlit secrets or environment variables to enable automatic AI rollups."

    # Sample top 15 ad summaries to avoid token overflow
    sample_ads = ads_df[['format', 'theme', 'funnel_stage', 'summary', 'gap_analysis']].head(20).to_dict(orient='records')
    
    prompt = f"""
    You are a VP of B2B Growth Marketing. Analyze this aggregated ad intelligence data for competitor: "{competitor_name}".
    
    Total Scraped Ads: {len(ads_df)}
    Ad Sample Data: {json.dumps(sample_ads)}

    Provide an Executive Strategy Rollup in clean Markdown format with the following headers:
    ### 🎯 Core Strategic Positioning
    (What overall story are they selling across their campaigns?)

    ### 📊 Funnel Allocation & Ad Mix
    (How are they balancing Top vs. Bottom of funnel, and what formats—Image, Video, Text—are predominant?)

    ### 🛡️ Primary Pain Points Targeted
    (What buyer anxieties or compliance/operational requirements are they pressing on?)

    ### ⚔️ Recommended Counter-Messaging / Gaps to Exploit
    (Where are they vulnerable or silent that we can position against?)
    """

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )
        return response.text
    except Exception as e:
        return f"Error generating rollup: {e}"

df = load_data()

st.title("🛡️ Competitor Ad Intelligence Dashboard")

# --- Sidebar Controls ---
st.sidebar.header("Controls & Tools")

if st.sidebar.button("🔄 Refresh Data", use_container_width=True):
    st.cache_data.clear()
    st.rerun()

if st.sidebar.button("🗑️ Clear All Saved Data", use_container_width=True):
    conn = sqlite3.connect("competitor_ads.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM ads")
    conn.commit()
    conn.close()
    st.cache_data.clear()
    st.sidebar.success("Database purged cleanly.")
    st.rerun()

st.sidebar.divider()

all_competitors = sorted(df["competitor"].unique().tolist()) if not df.empty else []
selected_competitor = st.sidebar.selectbox(
    "Select Competitor to Analyze",
    options=["All Competitors"] + all_competitors if all_competitors else ["No Data"]
)

st.sidebar.divider()
st.sidebar.subheader("➕ Run New Scrape")
new_domain = st.sidebar.text_input("Enter target domain", placeholder="secondfront.com")

if st.sidebar.button("🚀 Trigger Scraper", use_container_width=True):
    if not new_domain.strip():
        st.sidebar.warning("Enter a valid domain.")
    else:
        pat = st.secrets.get("GITHUB_PAT")
        owner = st.secrets.get("GITHUB_OWNER")
        repo = st.secrets.get("GITHUB_REPO")

        if not all([pat, owner, repo]):
            st.sidebar.error("Secrets missing in Streamlit Cloud settings.")
        else:
            api_url = f"https://api.github.com/repos/{owner}/{repo}/actions/workflows/daily_scrape.yml/dispatches"
            headers = {
                "Authorization": f"Bearer {pat}",
                "Accept": "application/vnd.github.v3+json",
            }
            payload = {
                "ref": "main",
                "inputs": {"competitor_domain": new_domain.strip()}
            }
            res = requests.post(api_url, headers=headers, json=payload)
            if res.status_code == 204:
                st.sidebar.success(f"Scraper started for `{new_domain}`! Check back in 2 mins.")
            else:
                st.sidebar.error(f"GitHub Error ({res.status_code}): {res.text}")

# Filter Dataset
if selected_competitor != "All Competitors" and selected_competitor != "No Data":
    filtered_df = df[df["competitor"] == selected_competitor]
else:
    filtered_df = df

# Top Metrics
m1, m2, m3, m4 = st.columns(4)
m1.metric("Total Scraped Ads", len(filtered_df))
m2.metric("Tracked Competitors", len(df["competitor"].unique()) if not df.empty else 0)
m3.metric("Video Ads", len(filtered_df[filtered_df["format"] == "Video Ad"]) if not filtered_df.empty else 0)
m4.metric("Image / Text Ads", len(filtered_df[filtered_df["format"] != "Video Ad"]) if not filtered_df.empty else 0)

st.divider()

# Navigation Tabs
tab_rollup, tab_feed, tab_breakdown = st.tabs([
    "🤖 Executive AI Rollup", 
    "📋 Ad Feed & Formats", 
    "💡 Strategic Gap Analysis"
])

# TAB 1: Executive AI Rollup
with tab_rollup:
    st.subheader("Executive Portfolio Rollup & Strategy Summary")
    
    if filtered_df.empty:
        st.info("No scraped ad data available to summarize. Add a domain in the sidebar to get started!")
    else:
        target_comp = selected_competitor if selected_competitor != "All Competitors" else (all_competitors[0] if all_competitors else "")
        
        st.markdown(f"### 🏢 Competitor: `{target_comp}`")
        comp_df = filtered_df[filtered_df["competitor"] == target_comp] if target_comp else filtered_df

        if st.button(f"⚡ Generate / Refresh AI Rollup for {target_comp}") or "rollup_text" not in st.session_state:
            with st.spinner("Analyzing ad portfolio with Gemini..."):
                st.session_state["rollup_text"] = generate_competitor_rollup(target_comp, comp_df)
        
        st.markdown(st.session_state.get("rollup_text", ""))

# TAB 2: Ad Feed & Formats
with tab_feed:
    st.subheader("Creative Feed & Ad Formats")
    if filtered_df.empty:
        st.info("No ads in database.")
    else:
        for idx, row in filtered_df.iterrows():
            with st.expander(f"[{row['competitor']}] {row['headline']} | Format: {row['format']}"):
                c1, c2 = st.columns([1, 2])
                with c1:
                    if row['image_url']:
                        st.image(row['image_url'], use_container_width=True)
                    else:
                        st.caption("No visual preview available")
                with c2:
                    st.markdown(f"**Ad Type / Format:** `{row['format']}`")
                    st.markdown(f"**Messaging Theme:** `{row['theme']}`")
                    st.markdown(f"**Funnel Stage:** `{row['funnel_stage']}`")
                    st.markdown(f"**Ad Copy Summary:** {row['summary']}")
                    st.caption(f"Scraped Date: {row['date_scraped']} | ID: {row['id']}")

# TAB 3: Strategic Gap Analysis
with tab_breakdown:
    st.subheader("Messaging Angle & Gap Breakdown")
    if filtered_df.empty:
        st.info("No ad data available.")
    else:
        for theme, group in filtered_df.groupby("theme"):
            with st.expander(f"📌 Theme: **{theme}** ({len(group)} Ads)", expanded=True):
                for _, ad in group.iterrows():
                    st.markdown(f"#### Hook: *\"{ad['headline']}\"*")
                    st.markdown(f"**Ad Type / Format:** `{ad['format']}` | **Stage:** `{ad['funnel_stage']}`")
                    st.info(f"**💡 Value Prop & Gap Analysis:**\n\n{ad['gap_analysis']}")
                    st.divider()
