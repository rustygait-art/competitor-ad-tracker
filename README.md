# 🎯 Competitor Ad Intelligence Tracker

A 100% free, automated single-source-of-truth web app that scrapes competitor Google Ads, categorizes themes and funnel stages using Gemini 2.5 Flash, and highlights strategic messaging gaps.

## File Overview

- `app.py`: Streamlit dashboard web app interface.
- `scraper.py`: Playwright web scraper + Gemini AI analysis script.
- `.github/workflows/daily_scrape.yml`: GitHub Actions automated cron job script.
- `requirements.txt`: Python package requirements.

## Quick Setup Guide

1. **Get a Free Gemini API Key**
   - Go to [Google AI Studio](https://aistudio.google.com/) and generate an API key.

2. **GitHub Deployment**
   - Create a GitHub repository and push these files.
   - Go to **Settings > Secrets and variables > Actions** in GitHub.
   - Add a repository secret named `GEMINI_API_KEY` with your API key.

3. **Streamlit Deployment**
   - Log into [Streamlit Community Cloud](https://share.streamlit.io/).
   - Connect your GitHub repo and select `app.py` as the entry point.
   - Under **Advanced Settings**, add `GEMINI_API_KEY = "your-api-key"` under Secrets.

4. **Customize Competitors**
   - Edit the `COMPETITORS` list in `scraper.py` to add your specific target competitor domains.
