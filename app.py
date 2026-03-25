import streamlit as st
import yfinance as yf
import plotly.graph_objects as go
import pandas as pd
import google.generativeai as genai
import feedparser
import re
import time
from datetime import datetime, timedelta

# ==========================================
# 1. 網頁基本設定
# ==========================================
st.set_page_config(page_title="AI 個股分析儀表板", layout="wide")
st.title("📈 專屬 AI 個股分析儀表板")

# ==========================================
# 2. 側邊欄設定 (Sidebar)
# ==========================================
st.sidebar.header("設定區")
ticker_symbol = st.sidebar.text_input("請輸入美股代碼", value="ONDS").upper()
time_period = st.sidebar.selectbox("選擇 K 線圖時間範圍", ["1mo", "3mo", "6mo", "1y", "ytd"])

# --- 圖表顯示開關 ---
st.sidebar.markdown("---")
st.sidebar.subheader("⚙️ 圖表顯示開關")
show_bb = st.sidebar.checkbox("顯示布林通道 (Bollinger Bands)", value=True)
show_fib = st.sidebar.checkbox("顯示黃金分割線 (Fibonacci)", value=True)

# 💡 在 value=" " 裡面的引號中間，貼上你的 API Key
api_key = st.sidebar.text_input("請輸入 Gemini API Key (選填)", type="password", value="")

st.sidebar.markdown("---")
st.sidebar.subheader("🔒 獨家付費情報")
st.sidebar.write("可直接貼上文字，或將大叔的文章存成 PDF 上傳")
kol_text = st.sidebar.text_area("請貼上文字段落 (選填)", height=100)
kol_pdf = st.sidebar.file_uploader("📄 匯入完整文章 (PDF)", type=['pdf'])

if kol_pdf:
    st.sidebar.success("✅ PDF 檔案已載入，準備交由 AI 研讀！")

st.sidebar.markdown("---")
st.sidebar.subheader("🌐 社群動態追蹤 (RSS)")

# 💡 在 value=" " 裡面的引號中間，貼上你轉換好的 RSS 網址
rss_url = st.sidebar.text_input("KOL 追蹤 (如大叔FB)", value="")
ceo_rss_url = st.sidebar.text_input("公司/CEO 追蹤 (如官方 X)", value="")


# ==========================================
# 3. 獲取市場數據 (使用 yfinance 內建破防機制)
# ==========================================
@st.cache_data(ttl=3600) # 快取資料1小時，避免重複抓取
def load_data(ticker, period):
    # 移除剛剛的 session，讓最新版的 yfinance 用它自己的方式突破封鎖
    stock = yf.Ticker(ticker)
    hist = stock.history(period=period)
    info = stock.info
    news = stock.news
    return hist, info, news

st.write(f"正在載入 **{ticker_symbol}** 的即時數據...")
hist_data, stock_info, stock_news = load_data(ticker_symbol, time_period)

if hist_data.empty:
    st.error("找不到該股票的數據，請確認代碼是否正確。")
else:
    # ==========================================
    # 4. 頂部數據看板
    # ==========================================
    col1, col2, col3, col4 = st.columns(4)
    current_price = hist_data['Close'].iloc[-1]
    prev_price = hist_data['Close'].iloc[-2]
    price_change = current_price - prev_price
    pct_change = (price_change / prev_price) * 100

    col1.metric("目前股價", f"${current_price:.2f}", f"{price_change:.2f} ({pct_change:.2f}%)")
    col2.metric("市值", f"${stock_info.get('marketCap', 0) / 1e6:.2f} M" if stock_info.get('marketCap') else "N/A")
    col3.metric("52週最高", f"${stock_info.get('fiftyTwoWeekHigh', 'N/A')}")
    col4.metric("52週最低", f"${stock_info.get('fiftyTwoWeekLow', 'N/A')}")

    st.markdown("---")

    # ==========================================
    # 5. 籌碼結構與做空數據 (美股專屬籌碼面)
    # ==========================================
    st.markdown("### 🕵️‍♂️ 籌碼結構與做空數據")
    chip_col1, chip_col2, chip_col3, chip_col4 = st.columns(4)

    # 抓取 yfinance 裡的籌碼與空單數據 (如果沒有數據則顯示 0)
    insider_pct = stock_info.get('heldPercentInsiders', 0) * 100
    inst_pct = stock_info.get('heldPercentInstitutions', 0) * 100
    short_pct = stock_info.get('shortPercentOfFloat', 0) * 100
    short_ratio = stock_info.get('shortRatio', 'N/A')

    chip_col1.metric("內部人持股比例", f"{insider_pct:.2f}%" if insider_pct else "N/A", help="公司高層與大股東持有的比例")
    chip_col2.metric("機構持股比例", f"{inst_pct:.2f}%" if inst_pct else "N/A", help="共同基金、退休基金等法人的總持股比例")
    chip_col3.metric("空單佔流通股比例", f"{short_pct:.2f}%" if short_pct else "N/A", help="越高代表市場看空情緒越重，但也越容易發生軋空")
    chip_col4.metric("空單回補天數 (Days to Cover)", f"{short_ratio}", help="空軍需要多少天的交易量才能買回所有空單")

    st.markdown("---")

    # ==========================================
    # 6. 技術面視覺化：全配版技術指標圖表 (含成交量)
    # ==========================================
    st.subheader(f"📊 {ticker_symbol} 技術面走勢 ({time_period})")
    from plotly.subplots import make_subplots
    
    # --- 1. 計算技術指標 ---
    # 均線與布林通道 (Bollinger Bands)
    hist_data['MA20'] = hist_data['Close'].rolling(window=20).mean()
    hist_data['STD20'] = hist_data['Close'].rolling(window=20).std()
    hist_data['Upper_Band'] = hist_data['MA20'] + (hist_data['STD20'] * 2) 
    hist_data['Lower_Band'] = hist_data['MA20'] - (hist_data['STD20'] * 2) 
    
    # 斐波那契回撤 (Fibonacci)
    period_high = hist_data['High'].max()
    period_low = hist_data['Low'].min()
    diff = period_high - period_low
    fib_levels = {
        '0.0%': period_high,
        '23.6%': period_high - 0.236 * diff,
        '38.2%': period_high - 0.382 * diff,
        '50.0%': period_high - 0.500 * diff,
        '61.8%': period_high - 0.618 * diff,
        '100.0%': period_low
    }

    # MACD (12, 26, 9)
    exp1 = hist_data['Close'].ewm(span=12, adjust=False).mean()
    exp2 = hist_data['Close'].ewm(span=26, adjust=False).mean()
    hist_data['MACD'] = exp1 - exp2
    hist_data['Signal'] = hist_data['MACD'].ewm(span=9, adjust=False).mean()
    hist_data['Histogram'] = hist_data['MACD'] - hist_data['Signal']
    
    # RSI (14)
    delta = hist_data['Close'].diff()
    gain = delta.where(delta > 0, 0).ewm(alpha=1/14, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14, adjust=False).mean()
    rs = gain / loss
    hist_data['RSI'] = 100 - (100 / (1 + rs))

    # 成交量顏色判定 (收盤>=開盤顯示綠色，否則顯示紅色)
    vol_colors = ['green' if close >= open else 'red' for close, open in zip(hist_data['Close'], hist_data['Open'])]

    # --- 2. 建立四層子圖表 ---
    # row_heights 設定四層的高度比例 (K線 45%, 成交量 15%, MACD 20%, RSI 20%)
    fig = make_subplots(rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.04, row_heights=[0.45, 0.15, 0.2, 0.2])

    # 第一層：K 線圖與指標
    fig.add_trace(go.Candlestick(x=hist_data.index, open=hist_data['Open'], high=hist_data['High'], low=hist_data['Low'], close=hist_data['Close'], name="K線"), row=1, col=1)
    
    if show_bb:
        fig.add_trace(go.Scatter(x=hist_data.index, y=hist_data['Upper_Band'], mode='lines', name='布林上軌', line=dict(color='rgba(173, 216, 230, 0.5)', width=1)), row=1, col=1)
        fig.add_trace(go.Scatter(x=hist_data.index, y=hist_data['Lower_Band'], mode='lines', name='布林下軌', line=dict(color='rgba(173, 216, 230, 0.5)', width=1), fill='tonexty', fillcolor='rgba(173, 216, 230, 0.1)'), row=1, col=1)
    
    fig.add_trace(go.Scatter(x=hist_data.index, y=hist_data['MA20'], mode='lines', name='20日均線', line=dict(color='orange', width=2)), row=1, col=1)

    if show_fib:
        fib_colors = ['red', 'orange', 'yellow', 'green', 'blue', 'purple']
        for (level_name, price), color in zip(fib_levels.items(), fib_colors):
            fig.add_hline(y=price, line_dash="dot", line_color=color, opacity=0.5, row=1, col=1, 
                          annotation_text=f"Fib {level_name} (${price:.2f})", annotation_position="right")

    # 第二層：成交量 (Volume)
    fig.add_trace(go.Bar(x=hist_data.index, y=hist_data['Volume'], name='成交量', marker_color=vol_colors), row=2, col=1)

    # 第三層：MACD
    hist_colors = ['green' if val >= 0 else 'red' for val in hist_data['Histogram']]
    fig.add_trace(go.Bar(x=hist_data.index, y=hist_data['Histogram'], name='MACD 柱狀圖', marker_color=hist_colors), row=3, col=1)
    fig.add_trace(go.Scatter(x=hist_data.index, y=hist_data['MACD'], mode='lines', name='MACD 快線', line=dict(color='blue')), row=3, col=1)
    fig.add_trace(go.Scatter(x=hist_data.index, y=hist_data['Signal'], mode='lines', name='MACD 慢線', line=dict(color='orange')), row=3, col=1)

    # 第四層：RSI
    fig.add_trace(go.Scatter(x=hist_data.index, y=hist_data['RSI'], mode='lines', name='RSI (14)', line=dict(color='purple')), row=4, col=1)
    fig.add_hline(y=70, line_dash="dash", line_color="red", row=4, col=1)
    fig.add_hline(y=30, line_dash="dash", line_color="green", row=4, col=1)

    # --- 3. 調整圖表版面 ---
    fig.update_layout(
        xaxis_rangeslider_visible=False, 
        xaxis2_rangeslider_visible=False,
        xaxis3_rangeslider_visible=False,
        xaxis4_rangeslider_visible=False,
        height=950, # 把整體圖表拉高到 950，確保四層圖表都不會太擠
        margin=dict(l=0, r=40, t=30, b=0), 
        showlegend=False
    )
    
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("---")

    # ==========================================
    # 7. 基本面新聞與 AI 戰略分析區 (終極三合一情報整合版)
    # ==========================================
    st.subheader("🤖 AI 每日新聞解讀與戰略分析")
    
    col_news, col_ai = st.columns([1, 1])

    safe_news_titles = []
    fb_intel_text = "" 

    with col_news:
        # --- 來源 1：Yahoo Finance ---
        st.write("**📰 近期重要新聞 (來源: Yahoo Finance)**")
        if not stock_news:
            st.write("目前找不到相關新聞。")
        else:
            for news in stock_news[:3]:
                title = "未知標題"
                link = "#"
                try:
                    if isinstance(news, dict):
                        if news.get('title'): title = news['title']
                        elif news.get('content') and isinstance(news['content'], dict) and news['content'].get('title'): title = news['content']['title']
                        if news.get('link'): link = news['link']
                        elif news.get('content') and isinstance(news['content'], dict) and news['content'].get('clickThroughUrl') and isinstance(news['content']['clickThroughUrl'], dict) and news['content']['clickThroughUrl'].get('url'): link = news['content']['clickThroughUrl']['url']
                except Exception:
                    pass 
                if title != "未知標題":
                    safe_news_titles.append(title)
                st.markdown(f"➤ [{title}]({link})")
        
        # --- 來源 2：Google News 權威媒體聚合 ---
        st.markdown("---")
        st.write("**🌍 權威媒體聚合 (CNBC/Reuters/WSJ等)**")
        try:
            gn_url = f"https://news.google.com/rss/search?q={ticker_symbol}+stock&hl=en-US&gl=US&ceid=US:en"
            gn_feed = feedparser.parse(gn_url)
            if gn_feed.entries:
                for entry in gn_feed.entries[:3]:
                    safe_news_titles.append(entry.title)
                    st.markdown(f"➤ [{entry.title}]({entry.link})")
            else:
                st.write("目前找不到相關聚合新聞。")
        except Exception as e:
            st.write("讀取權威媒體失敗。")

        # --- 來源 3：美國 SEC 官方財報與公告 ---
        st.markdown("---")
        st.write("**🏛️ 公司官方公告 (來源: 美國 SEC)**")
        try:
            sec_url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={ticker_symbol}&type=&dateb=&owner=exclude&start=0&count=40&output=atom"
            sec_feed = feedparser.parse(sec_url)
            if sec_feed.entries:
                for entry in sec_feed.entries[:2]:
                    safe_news_titles.append(f"【SEC官方文件】{entry.title}") 
                    st.markdown(f"➤ [{entry.title}]({entry.link})")
            else:
                st.write("近期無重大官方公告。")
        except Exception as e:
            st.write("讀取 SEC 官方公告失敗。")

        # --- 來源 4：社群動態 RSS ---
        if rss_url:
            st.markdown("---")
            st.write(f"**🌐 社群動態追蹤 (歷史軌跡: {ticker_symbol})**")
            try:
                feed = feedparser.parse(rss_url)
                if feed.entries:
                    target_texts = []
                    fetched_titles = []
                    one_year_ago = datetime.now() - timedelta(days=365)
                    
                    for entry in feed.entries:
                        entry_date = datetime.now()
                        if hasattr(entry, 'published_parsed') and entry.published_parsed:
                            entry_date = datetime.fromtimestamp(time.mktime(entry.published_parsed))
                        
                        if entry_date >= one_year_ago:
                            clean_text = re.sub('<[^<]+>', '', entry.summary)
                            if ticker_symbol.lower() in clean_text.lower() or ticker_symbol.lower() in entry.title.lower():
                                date_str = entry_date.strftime('%Y-%m-%d')
                                title = entry.title if hasattr(entry, 'title') else "無標題動態"
                                target_texts.append(f"【發布日期：{date_str}】\n{clean_text[:2000]}")
                                fetched_titles.append(f"{date_str} | {title}")
                    
                    if target_texts:
                        fb_intel_text = "\n\n---\n\n".join(target_texts)[:5000]
                        st.success(f"➤ 成功攔截 {len(target_texts)} 篇相關動態！已交由 AI 分析。")
                        with st.expander("👀 點擊查看已攔截的貼文標題"):
                            for t in fetched_titles:
                                st.markdown(f"- {t}")
                    else:
                        st.info(f"近期公開貼文中，暫未搜尋到關於 **{ticker_symbol}** 的討論。")
                else:
                    st.write("目前沒有抓取到最新動態。")
            except Exception as e:
                st.error("讀取社群動態失敗，請確認 RSS 網址是否正確。")

        # --- 來源 5：公司/CEO 官方社群 RSS ---
        if ceo_rss_url:
            st.markdown("---")
            st.write(f"**🐦 官方/CEO 動態追蹤 (X/Twitter)**")
            try:
                ceo_feed = feedparser.parse(ceo_rss_url)
                if ceo_feed.entries:
                    ceo_texts = []
                    ceo_titles = []
                    # 官方動態通常都很重要，我們抓近 30 天內的最新 3 篇
                    thirty_days_ago = datetime.now() - timedelta(days=30)
                    
                    for entry in ceo_feed.entries:
                        entry_date = datetime.now()
                        if hasattr(entry, 'published_parsed') and entry.published_parsed:
                            entry_date = datetime.fromtimestamp(time.mktime(entry.published_parsed))
                        
                        if entry_date >= thirty_days_ago:
                            clean_text = re.sub('<[^<]+>', '', entry.summary)
                            date_str = entry_date.strftime('%Y-%m-%d')
                            title = entry.title if hasattr(entry, 'title') else "無標題推文"
                            
                            ceo_texts.append(f"【官方發布日期：{date_str}】\n{clean_text[:1000]}")
                            ceo_titles.append(f"{date_str} | {title}")
                            
                            if len(ceo_texts) >= 3: # 最多抓 3 篇避免資訊過載
                                break
                    
                    if ceo_texts:
                        # 將 CEO 動態也加入給 AI 的百寶箱中
                        fb_intel_text += "\n\n【公司/CEO 官方社群動態】：\n" + "\n".join(ceo_texts) 
                        st.success(f"➤ 成功攔截 {len(ceo_texts)} 篇官方/CEO 近期動態！")
                        with st.expander("👀 點擊查看官方推文標題"):
                            for t in ceo_titles:
                                st.markdown(f"- {t}")
                    else:
                        st.info("近期暫無官方/CEO 動態。")
                else:
                    st.write("目前沒有抓取到最新動態。")
            except Exception as e:
                st.error("讀取官方社群失敗，請確認 RSS 網址是否正確。")
    with col_ai:
        st.write("**Gemini 綜合戰略分析**")
        if api_key:
            genai.configure(api_key=api_key)
            if st.button("✨ 點我生成 AI 戰略報告", use_container_width=True):
                try:
                    available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
                    if not available_models:
                        st.error("這個 API Key 找不到支援的模型，請確認是否有開通權限。")
                    else:
                        model_name = next((m for m in available_models if 'flash' in m or 'pro' in m), available_models[0])
                        model = genai.GenerativeModel(model_name)
                        
                        # 擷取最新的技術指標數值
                        latest_rsi = hist_data['RSI'].iloc[-1] if 'RSI' in hist_data else 0
                        latest_macd = hist_data['MACD'].iloc[-1] if 'MACD' in hist_data else 0
                        latest_signal = hist_data['Signal'].iloc[-1] if 'Signal' in hist_data else 0
                        
                        # --- 新增：擷取布林通道數值 ---
                        latest_upper = hist_data['Upper_Band'].iloc[-1] if 'Upper_Band' in hist_data else 0
                        latest_lower = hist_data['Lower_Band'].iloc[-1] if 'Lower_Band' in hist_data else 0
                        
                        news_text = "\n".join(safe_news_titles) if safe_news_titles else "今日無重大新聞"
                        kol_context_str = f"\n\n【獨家付費情報 (文字/PDF)】：\n{kol_text}" if kol_text else ""
                        fb_context_str = f"\n\n【公開社群動態 (歷史軌跡)】：\n{fb_intel_text}" if fb_intel_text else ""
                        
                        prompt = f"""你是一位頂尖的美股量化分析師。
請根據 {ticker_symbol} 的最新全方位數據與情報進行深度綜合判斷：

【量化技術與籌碼數據】：
- 最新收盤價：${current_price:.2f}
- 布林通道 (20, 2)：上軌 ${latest_upper:.2f} / 下軌 ${latest_lower:.2f}
- RSI (14)：{latest_rsi:.2f} (若大於70為超買，小於30為超賣)
- MACD 快線：{latest_macd:.2f} / 慢線：{latest_signal:.2f}
- 機構法人持股比例：{stock_info.get('heldPercentInstitutions', 0) * 100:.2f}%
- 空單佔流通股比例：{stock_info.get('shortPercentOfFloat', 0) * 100:.2f}%
- 空單回補天數 (Days to Cover)：{stock_info.get('shortRatio', 'N/A')}

【最新外電與官方公告】：
{news_text}
{kol_context_str}
{fb_context_str}

請撰寫一份專業的綜合戰略報告，嚴格按照以下「三個區塊」結構化輸出，並使用繁體中文（台灣）：

### 1. 📈 技術面與籌碼面診斷
請觀察「最新收盤價」與「布林通道上下軌」的相對位置（是否突破上軌過熱，或回測下軌尋求支撐），並結合 RSI、MACD 的現況判斷趨勢強弱；同時結合機構持股與空單比例，分析籌碼結構與潛在的軋空契機。

### 2. 📰 基本面與社群情報提煉
綜合外電新聞、SEC 官方財報公告，以及大叔/CEO等重要人物的獨家社群觀點，提煉出推動股價的核心基本面邏輯。

### 3. 🎯 全局戰略綜合決策
將上述的技術、籌碼、基本面與人物情報完美融合，給出客觀且具體的短線觀察重點與操作建議。
"""
                        loading_msg = f'系統已自動鎖定 {model_name}，正在為您整合情報...'
                        if kol_pdf is not None:
                            loading_msg = f'系統自動鎖定 {model_name}，研讀 PDF 中...'

                        with st.spinner(loading_msg):
                            contents = [prompt]
                            if kol_pdf is not None:
                                pdf_data = {
                                    "mime_type": "application/pdf",
                                    "data": kol_pdf.getvalue()
                                }
                                contents.append(pdf_data)
                                
                            response = model.generate_content(contents)
                            st.info(response.text.replace('$', r'\$'))
                            
                except Exception as e:
                    st.error(f"API 呼叫失敗: {e}")
            else:
                st.write("👈 請確認左側設定完畢後，點擊上方按鈕生成報告。")
        else:
            st.warning("⚠️ 請在左側輸入 Gemini API Key 以啟動 AI 自動分析功能。")

    # ==========================================
    # 8. 頁尾版權宣告與專屬署名 (Footer)
    # ==========================================
    st.markdown("---")
    st.markdown(
        """
        <div style='text-align: center; color: #888888; font-size: 14px;'>
            Designed & Built with 💡 by <b>Paul Wang</b> | 專屬 AI 個股分析儀表板 © 2026
        </div>
        """,
        unsafe_allow_html=True
    )
