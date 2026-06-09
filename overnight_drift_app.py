import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
import time

st.set_page_config(page_title="Overnight Drift Scanner", page_icon="📈", layout="wide")
st.title("📈 Overnight Drift Scanner")
st.caption("Finds stocks that consistently gap open vs prior close — Polygon API")

with st.sidebar:
    st.header("⚙️ Settings")
    api_key = st.text_input("Polygon API Key", type="password", placeholder="Paste key here...")

    default_tickers = (
        "NVDA, META, TSLA, PLTR, AXON, CRWD, ANET, SMCI, SOUN, "
        "RKLB, MASI, AVTR, CELC, RBRK, CELH, VRNS, RIOT, EVTC, "
        "MSFT, AAPL, AMZN, GOOGL, AMD, NFLX, CRM, PANW"
    )
    ticker_input  = st.text_area("Tickers", value=default_tickers, height=120)
    lookback      = st.slider("Lookback Days", 10, 90, 30)
    min_avg_drift = st.slider("Min Avg Drift %", 0.0, 2.0, 0.10, step=0.05)
    min_cons      = st.slider("Min Consistency", 0.30, 1.0, 0.50, step=0.05)
    run_btn       = st.button("▶  Run Scan", type="primary", use_container_width=True)


def fetch_bars(ticker, api_key, lookback):
    to_dt   = datetime.today()
    from_dt = to_dt - timedelta(days=lookback + 45)
    url = (
        f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/day"
        f"/{from_dt.strftime('%Y-%m-%d')}/{to_dt.strftime('%Y-%m-%d')}"
        f"?adjusted=true&sort=asc&limit=120&apiKey={api_key}"
    )
    try:
        r = requests.get(url, timeout=10)
        if r.status_code != 200:
            return None, f"HTTP {r.status_code}"
        data = r.json()
        if not data.get("results"):
            return None, "no data"
        return data["results"], None
    except Exception as e:
        return None, str(e)


def calc_drift(bars, lookback):
    recent = bars[-lookback:]
    drifts = []
    for i in range(1, len(recent)):
        prev_c = recent[i-1]["c"]
        open_  = recent[i]["o"]
        if prev_c > 0:
            drifts.append((open_ - prev_c) / prev_c * 100)
    if len(drifts) < 5:
        return None
    avg         = sum(drifts) / len(drifts)
    pos         = sum(1 for d in drifts if d >  0.10)
    neg         = sum(1 for d in drifts if d < -0.10)
    consistency = max(pos, neg) / len(drifts)
    direction   = "▲ UP" if pos >= neg else "▼ DN"
    max_drift   = max(abs(d) for d in drifts)
    stddev      = (sum((d - avg)**2 for d in drifts) / len(drifts)) ** 0.5
    score       = abs(avg) * consistency
    return dict(avg=avg, abs_avg=abs(avg), pos=pos, neg=neg,
                consistency=consistency, direction=direction,
                max_drift=max_drift, stddev=stddev, score=score,
                last=bars[-1]["c"], drifts=drifts)


if run_btn:
    if not api_key:
        st.error("Paste your Polygon API key in the sidebar.")
        st.stop()

    tickers = [t.strip().upper() for t in ticker_input.replace(",", " ").split() if t.strip()]

    progress_bar = st.progress(0, text="Starting...")
    log_box      = st.empty()
    results      = []
    log_lines    = []

    for i, ticker in enumerate(tickers):
        progress_bar.progress(int(i / len(tickers) * 100), text=f"Scanning {ticker}... ({i+1}/{len(tickers)})")

        bars, err = fetch_bars(ticker, api_key, lookback)
        if err:
            log_lines.append(f"⚠ {ticker}: {err}")
        else:
            stats = calc_drift(bars, lookback)
            if not stats:
                log_lines.append(f"— {ticker}: not enough bars")
            else:
                matched = stats["abs_avg"] >= min_avg_drift and stats["consistency"] >= min_cons
                if matched:
                    results.append({
                        "Ticker":      ticker,
                        "Last":        stats["last"],
                        "Dir":         stats["direction"],
                        "Avg Drift %": stats["avg"],
                        "Consistency": stats["consistency"],
                        "▲ Days":      stats["pos"],
                        "▼ Days":      stats["neg"],
                        "Max Drift %": stats["max_drift"],
                        "Stddev":      stats["stddev"],
                        "Score":       stats["score"],
                        "_drifts":     stats["drifts"],
                    })
                log_lines.append(
                    f"{'✅' if matched else '—'} {ticker}: "
                    f"avg={stats['avg']:+.3f}%  "
                    f"cons={stats['consistency']*100:.0f}%  "
                    f"score={stats['score']:.4f}"
                )

        log_box.code("\n".join(log_lines[-15:]), language=None)
        time.sleep(0.12)

    progress_bar.progress(100, text="Done!")

    if not results:
        st.warning("No stocks matched. Try lowering Min Avg Drift or Min Consistency.")
    else:
        df = pd.DataFrame(results).sort_values("Score", ascending=False).reset_index(drop=True)
        df.index += 1

        st.success(f"Found **{len(df)}** stocks with consistent overnight drift")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Found",         len(df))
        c2.metric("Best Score",    f"{df['Score'].max():.4f}")
        c3.metric("Top Avg Drift", f"{df['Avg Drift %'].iloc[0]:+.3f}%")
        c4.metric("Top Consistency", f"{df['Consistency'].max()*100:.0f}%")

        st.divider()

        display = df.drop(columns=["_drifts"]).copy()
        display["Last"]         = display["Last"].map("${:.2f}".format)
        display["Avg Drift %"]  = display["Avg Drift %"].map("{:+.3f}%".format)
        display["Consistency"]  = display["Consistency"].map("{:.0%}".format)
        display["Max Drift %"]  = display["Max Drift %"].map("{:.2f}%".format)
        display["Stddev"]       = display["Stddev"].map("{:.3f}".format)
        display["Score"]        = display["Score"].map("{:.4f}".format)
        st.dataframe(display, use_container_width=True, height=400)

        # Simple bar chart — no altair facets
        st.subheader("Score by Ticker")
        chart_df = df[["Ticker", "Score"]].set_index("Ticker")
        st.bar_chart(chart_df)

        csv = df.drop(columns=["_drifts"]).to_csv(index=False)
        st.download_button("⬇ Download CSV", data=csv,
                           file_name=f"overnight_drift_{datetime.today().strftime('%Y%m%d')}.csv",
                           mime="text/csv")

st.divider()
st.caption(
    "Overnight drift = (Open − PrevClose) / PrevClose × 100. "
    "Consistency = % of days drifting in dominant direction (>0.1% threshold). "
    "Score = |avg drift| × consistency."
)
