import streamlit as st
import sqlite3
import pandas as pd
import requests

st.set_page_config(page_title="Competitor Ad Intelligence", layout="wide")

@st.cache_data(ttl=10)
def load_data():
    conn = sqlite3.connect("competitor_ads.db")
    try:
        df = pd.read_sql_query("SELECT * FROM ads", conn)
    except Exception:
        # Fallback if table doesn't exist yet
        df = pd.DataFrame(columns=[
            "id", "competitor", "headline", "body", "format", 
            "image_url", "theme", "funnel_stage", "summary", 
            "gap_analysis", "date_scraped"
        ])
    conn.close()
    return df

df = load_data()

st.title("🛡️ Competitor Ad Intelligence Dashboard")

# --- Sidebar Controls ---
st.sidebar.header("Controls & Filters")

if st.sidebar.button("🔄 Sync & Refresh Database", use_container_width=True):
    st.cache_data.clear()
    st.rerun()

# Competitor Filter (Populated strictly from database records)
all_competitors = sorted(df["competitor"].unique().tolist()) if not df.empty else []
selected_competitors = st.sidebar.multiselect(
    "Filter Competitors",
    options=all_competitors,
    default=all_competitors
)

# Trigger New Scrape Form
st.sidebar.divider()
st.sidebar.subheader("➕ Scrape Target Domain")
new_domain = st.sidebar.text_input("Enter domain (e.g. secondfront.com)", placeholder="domain.com")

if st.sidebar.button("🚀 Run Scraper", use_container_width=True):
    if not new_domain.strip():
        st.sidebar.warning("Please enter a target domain.")
    else:
        pat = st.secrets.get("GITHUB_PAT")
        owner = st.secrets.get("GITHUB_OWNER")
        repo = st.secrets.get("GITHUB_REPO")

        if not all([pat, owner, repo]):
            st.sidebar.error("Secrets missing in Streamlit Cloud.")
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
                st.sidebar.success(f"Triggered scraper for `{new_domain}`! Hit 'Sync & Refresh' in ~2 mins.")
            else:
                st.sidebar.error(f"GitHub Error ({res.status_code}): {res.text}")

# Filter DataFrame based on selection
filtered_df = df[df["competitor"].isin(selected_competitors)] if selected_competitors else df

# Overview Metrics
col1, col2, col3 = st.columns(3)
col1.metric("Total Scraped Ads", len(filtered_df))
col2.metric("Tracked Domains", len(filtered_df["competitor"].unique()) if not filtered_df.empty else 0)
col3.metric("Latest Update", filtered_df["date_scraped"].max() if not filtered_df.empty else "N/A")

st.divider()

# --- Tab Layout ---
tab_feed, tab_gap = st.tabs(["📋 Ad Feed", "💡 Gap Analysis & Strategy"])

# ==========================================
# TAB 1: Visual Ad Feed
# ==========================================
with tab_feed:
    st.subheader("Creative & Copy Feed")
    if filtered_df.empty:
        st.info("No ads available. Enter a competitor domain in the sidebar to run a fresh scrape!")
    else:
        for idx, row in filtered_df.iterrows():
            with st.expander(f"[{row['competitor']}] {row['headline']} ({row['funnel_stage']})"):
                c1, c2 = st.columns([1, 2])
                with c1:
                    if row['image_url']:
                        st.image(row['image_url'], use_container_width=True)
                    else:
                        st.caption("No visual preview element available")
                with c2:
                    st.markdown(f"**Messaging Theme:** `{row['theme']}`")
                    st.markdown(f"**Funnel Stage:** `{row['funnel_stage']}`")
                    st.markdown(f"**Ad Copy Summary:** {row['summary']}")
                    st.caption(f"Scraped Date: {row['date_scraped']} | Ad ID: {row['id']}")

# ==========================================
# TAB 2: Strategic Gap Analysis (Grouped)
# ==========================================
with tab_gap:
    st.subheader("Strategic Positioning & Gap Analysis")
    if filtered_df.empty:
        st.info("No ad data to analyze. Add a competitor domain to get started.")
    else:
        # Group 1: By Competitor Domain
        grouped_competitors = filtered_df.groupby("competitor")

        for competitor, comp_group in grouped_competitors:
            st.markdown(f"## 🏢 Competitor: `{competitor}`")
            
            # Group 2: By Messaging Theme within Competitor
            grouped_themes = comp_group.groupby("theme")

            for theme, theme_group in grouped_themes:
                with st.expander(f"📌 Messaging Angle: **{theme}** ({len(theme_group)} Ads)", expanded=True):
                    for _, ad in theme_group.iterrows():
                        st.markdown(f"#### Hook / Headline: *\"{ad['headline']}\"*")
                        st.markdown(f"**Target Stage:** `{ad['funnel_stage']}`")
                        
                        # Callout container for Gap Analysis
                        st.info(f"**💡 Strategic Gap & Value Prop Angle:**\n\n{ad['gap_analysis']}")
                        
                        # Inspect underlying ad details
                        with st.popover("🔍 Inspect Underlying Ad Details"):
                            st.write(f"**Executive Summary:** {ad['summary']}")
                            st.write(f"**Full Extracted Copy:** {ad['body']}")
                            if ad['image_url']:
                                st.image(ad['image_url'], width=300)
                        st.divider()
            st.write("---")
