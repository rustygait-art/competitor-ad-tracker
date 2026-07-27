import streamlit as st
import sqlite3
import pandas as pd
import os

st.set_page_config(
    page_title="Competitor Ad Intelligence", 
    page_icon="🎯",
    layout="wide"
)

DB_PATH = "competitor_ads.db"

def load_data():
    if not os.path.exists(DB_PATH):
        return pd.DataFrame()
    conn = sqlite3.connect(DB_PATH)
    try:
        df = pd.read_sql_query("SELECT * FROM ads ORDER BY date_scraped DESC", conn)
    except Exception:
        df = pd.DataFrame()
    finally:
        conn.close()
    return df

st.title("🎯 Competitor Ad Intelligence Dashboard")
st.markdown("Single source of truth for competitor messaging, thematic grouping, and ad gap analysis.")

df = load_data()

if df.empty:
    st.info("💡 No ad data found yet. Run `python scraper.py` locally or trigger the GitHub Action workflow to populate the database.")
    st.stop()

# --- Top Key Metrics ---
col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Ads Tracked", len(df))
col2.metric("Competitors Monitored", df['competitor'].nunique())
col3.metric("Dominant Theme", df['theme'].mode()[0] if not df['theme'].empty else "N/A")
col4.metric("Last Updated", df['date_scraped'].max())

st.divider()

# --- Sidebar Filters ---
st.sidebar.header("Filter Ads")

all_competitors = sorted(df['competitor'].unique().tolist())
selected_competitors = st.sidebar.multiselect(
    "Competitor Domain", 
    options=all_competitors, 
    default=all_competitors
)

all_themes = sorted(df['theme'].unique().tolist())
selected_themes = st.sidebar.multiselect(
    "Messaging Theme", 
    options=all_themes, 
    default=all_themes
)

all_funnels = sorted(df['funnel_stage'].unique().tolist())
selected_funnels = st.sidebar.multiselect(
    "Funnel Stage", 
    options=all_funnels, 
    default=all_funnels
)

# Apply Filters
filtered_df = df[
    (df['competitor'].isin(selected_competitors)) &
    (df['theme'].isin(selected_themes)) &
    (df['funnel_stage'].isin(selected_funnels))
]

# --- Main Views ---
tab_feed, tab_gap, tab_raw = st.tabs(["📢 Ad Feed & Summaries", "💡 Strategic Gap Analysis", "📊 Database Table"])

with tab_feed:
    st.subheader(f"Showing {len(filtered_df)} Ads")
    
    if filtered_df.empty:
        st.warning("No ads match the selected sidebar filters.")
    else:
        for _, row in filtered_df.iterrows():
            with st.container(border=True):
                col_img, col_info = st.columns([1, 3])
                
                with col_img:
                    if row['image_url']:
                        st.image(row['image_url'], use_container_width=True)
                    else:
                        st.caption("🖼️ No image preview available")
                
                with col_info:
                    st.markdown(f"### {row['headline']}")
                    st.caption(f"**Competitor:** `{row['competitor']}` | **Scraped:** {row['date_scraped']}")
                    
                    st.markdown(f"🏷️ **Theme:** `{row['theme']}`  |  🎯 **Funnel Stage:** `{row['funnel_stage']}`")
                    
                    st.markdown("**AI Executive Summary:**")
                    st.info(row['summary'] if row['summary'] else "No summary available.")
                    
                    with st.expander("View Full Raw Ad Text"):
                        st.text(row['body'])

with tab_gap:
    st.subheader("Competitor Messaging Gap Analysis")
    st.markdown("Automated insights on unique hooks and gaps identified in competitor campaigns:")
    
    if filtered_df.empty:
        st.warning("No data available for gap analysis based on current filters.")
    else:
        for comp in selected_competitors:
            comp_df = filtered_df[filtered_df['competitor'] == comp]
            if not comp_df.empty:
                st.markdown(f"#### 🔍 {comp}")
                for _, row in comp_df.iterrows():
                    if row['gap_analysis']:
                        st.write(f"- **[{row['theme']}]**: {row['gap_analysis']}")

with tab_raw:
    st.dataframe(filtered_df, use_container_width=True)
