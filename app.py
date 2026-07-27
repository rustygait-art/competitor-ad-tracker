import streamlit as st
import sqlite3
import pandas as pd
import requests

st.set_page_config(page_title="Competitor Ad Intelligence", layout="wide")

# Force Streamlit to re-read SQLite database whenever button is clicked
@st.cache_data(ttl=10)
def load_data():
    conn = sqlite3.connect("competitor_ads.db")
    df = pd.read_sql_query("SELECT * FROM ads", conn)
    conn.close()
    return df

df = load_data()

st.title("🛡️ Competitor Ad Intelligence Dashboard")

# --- Sidebar Controls ---
st.sidebar.header("Controls & Filters")

if st.sidebar.button("🔄 Sync & Refresh Database", use_container_width=True):
    st.cache_data.clear()
    st.rerun()

# Dynamic Multi-Select for Competitors (Defaults to showing ALL scraped competitors)
all_competitors = df["competitor"].unique().tolist() if not df.empty else []
selected_competitors = st.sidebar.multiselect(
    "Filter Competitors",
    options=all_competitors,
    default=all_competitors  # Ensures EVERY scraped competitor is shown by default
)

# Trigger New Scrape Form
st.sidebar.divider()
st.sidebar.subheader("➕ Scrape New URL")
new_domain = st.sidebar.text_input("Enter domain (e.g. salesforce.com)", placeholder="hubspot.com")

if st.sidebar.button("🚀 Run Scraper", use_container_width=True):
    if not new_domain.strip():
        st.sidebar.warning("Please enter a domain.")
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
                st.sidebar.success(f"Scraping `{new_domain}`! Hit 'Sync & Refresh' in ~2 mins.")
            else:
                st.sidebar.error(f"GitHub Error ({res.status_code}): {res.text}")

# Filter DataFrame based on selection
filtered_df = df[df["competitor"].isin(selected_competitors)] if selected_competitors else df

# Metric Overview
col1, col2, col3 = st.columns(3)
col1.metric("Total Scraped Ads", len(filtered_df))
col2.metric("Tracked Domains", len(filtered_df["competitor"].unique()) if not filtered_df.empty else 0)
col3.metric("Latest Update", filtered_df["date_scraped"].max() if not filtered_df.empty else "N/A")

st.divider()

# Display Ads Feed
st.subheader("📋 Ad Feed")
if filtered_df.empty:
    st.info("No ads available. Scrape a domain using the sidebar!")
else:
    for idx, row in filtered_df.iterrows():
        with st.expander(f"[{row['competitor']}] {row['headline']} ({row['funnel_stage']})"):
            c1, c2 = st.columns([1, 2])
            with c1:
                if row['image_url']:
                    st.image(row['image_url'], use_container_width=True)
                else:
                    st.caption("No visual creative preview")
            with c2:
                st.markdown(f"**Theme:** `{row['theme']}`")
                st.markdown(f"**Summary:** {row['summary']}")
                st.markdown(f"**Strategic Gap Analysis:** {row['gap_analysis']}")
                st.caption(f"Scraped Date: {row['date_scraped']} | Ad ID: {row['id']}")
