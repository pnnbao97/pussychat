import asyncio
from openai import AsyncOpenAI
import threading
import requests
from bs4 import BeautifulSoup
import json
import time
import os
import wikipedia
import praw
import feedparser
from dotenv import load_dotenv
from newspaper import Article
from datetime import datetime, timedelta
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from semantic_kernel import Kernel
from semantic_kernel.contents import ChatHistory
from semantic_kernel.connectors.ai.open_ai import OpenAIChatCompletion, OpenAIChatPromptExecutionSettings
import sqlite3
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from PIL import Image, ImageDraw, ImageFont
import io
import uuid

# Tải các biến môi trường từ file .env
load_dotenv()

# Khởi tạo các API key
TELEGRAM_API_KEY = os.getenv('TELEGRAM_BOT_TOKEN')
NEWS_API_KEY = os.getenv('NEWS_API_KEY')
REDDIT_CLIENT_ID = os.getenv('REDDIT_CLIENT_ID')
REDDIT_CLIENT_SECRET = os.getenv('REDDIT_CLIENT_SECRET')
REDDIT_USER_AGENT = os.getenv('REDDIT_USER_AGENT')
GOOGLE_API_KEY = os.getenv('GOOGLE_SEARCH')
GOOGLE_CSE_ID = os.getenv('SEARCH_ENGINE_ID')
DS_KEY = os.getenv('DEEPSEEK')
COINGECKO_API = "https://api.coingecko.com/api/v3"
BINANCE_API = "https://api.binance.com/api/v3"

# Chỉ cho phép hai nhóm với group_id này hoạt động
ALLOWED_GROUP_ID = "-1002679588220"  # Thêm group_id chính của bạn vào đây
ALLOWED_GROUP_ID_2 = ""  # Thêm group_id phụ của bạn vào đây

# Khởi tạo Reddit client
reddit = praw.Reddit(
    client_id=REDDIT_CLIENT_ID,
    client_secret=REDDIT_CLIENT_SECRET,
    user_agent=REDDIT_USER_AGENT
)

# Khởi tạo Semantic Kernel và dịch vụ chat
kernel = Kernel()
chat_service = OpenAIChatCompletion(
    ai_model_id="deepseek-chat",
    async_client=AsyncOpenAI(
        api_key=DS_KEY,
        base_url="https://api.deepseek.com",
    ),
)
execution_settings = OpenAIChatPromptExecutionSettings(
    max_tokens=1000,
    temperature=1.5,
)

# Danh sách nguồn RSS từ các báo Việt Nam
RSS_FEEDS = [
    "https://vnexpress.net/rss/tin-moi-nhat.rss",
    "https://tuoitre.vn/rss/tin-moi-nhat.rss",
    "https://thanhnien.vn/rss/home.rss",
    "https://www.bbc.co.uk/vietnamese/index.xml",
]

# Khởi tạo SQLite database
def init_db():
    conn = sqlite3.connect("bot_data.db")
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS news (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        content TEXT,
        source TEXT,
        url TEXT UNIQUE,
        timestamp TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS crypto (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        coin TEXT,
        price REAL,
        volume REAL,
        timestamp TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS macro (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        indicator TEXT,
        value TEXT,
        source TEXT,
        timestamp TEXT
    )''')
    conn.commit()
    conn.close()

init_db()

# Quản lý cuộc trò chuyện nhóm với ChatHistory
class GroupConversationManager:
    def __init__(self, max_messages=15, summary_threshold=10, inactivity_timeout=900):
        self.group_histories = {}
        self.last_activity_time = {}
        self.max_messages = max_messages
        self.summary_threshold = summary_threshold
        self.inactivity_timeout = inactivity_timeout
    
    async def add_message(self, group_id, user_id, user_name, message_text, response):
        current_time = time.time()
        if group_id not in self.group_histories:
            self.group_histories[group_id] = ChatHistory()
            self.last_activity_time[group_id] = current_time
        
        time_diff = current_time - self.last_activity_time[group_id]
        if time_diff > self.inactivity_timeout and len(self.group_histories[group_id]) > 0:
            summary = await self._summarize_conversation(group_id)
            self.group_histories[group_id] = ChatHistory()
            self.group_histories[group_id].add_system_message(f"Tóm tắt trước đó: {summary}")
        
        self.last_activity_time[group_id] = current_time
        
        self.group_histories[group_id].add_user_message(f"Đây là câu hỏi của {user_name}: {message_text}")
        self.group_histories[group_id].add_assistant_message(f"Đây là câu trả lời của Pussy: {response}")
        
        if len(self.group_histories[group_id]) > self.max_messages * 2:
            summary = await self._summarize_conversation(group_id)
            self.group_histories[group_id] = ChatHistory()
            self.group_histories[group_id].add_system_message(f"Tóm tắt trước đó: {summary}")
    
    async def _summarize_conversation(self, group_id):
        history = self.group_histories[group_id]
        messages = [f"{msg.role}: {msg.content}" for msg in history[:self.max_messages * 2]]
        conversation_text = "\n".join(messages)
        
        summary_history = ChatHistory()
        summary_history.add_system_message("Mày là một con mèo thông thái và là trợ lí tổng hợp, tóm tắt thông tin.")
        summary_history.add_user_message(f"Hãy tóm tắt ngắn gọn cuộc trò chuyện sau, bảo toàn ý chính và thông tin quan trọng (không quá 3 câu):\n{conversation_text}")
        
        summary = await chat_service.get_chat_message_content(summary_history, execution_settings)
        return summary
    
    async def get_conversation_context(self, group_id, user_id):
        user_name = track_id(user_id)
        if group_id not in self.group_histories:
            return f"Đây là cuộc trò chuyện mới với {user_name}."
        
        history = self.group_histories[group_id]
        conversation_history = ""
        for msg in history:
            if msg.role == "system":
                conversation_history += f"Bởi vì lịch sử chat quá dài nên những tin nhắn quá cũ sẽ được tóm tắt lại. Đây chỉ là phần tóm tắt từ các cuộc trò chuyện trước đó: {msg.content}\n"
            else:
                conversation_history += f"{msg.content}\n"
        return f"Đây là lịch sử cuộc trò chuyện nhóm (được xếp theo thứ tự từ cũ nhất đến mới nhất):\n{conversation_history}\n"

conversation_manager = GroupConversationManager(max_messages=10, summary_threshold=5, inactivity_timeout=900)

# Các hàm lấy tin tức và thông tin
def fetch_news():
    news_items = []
    for feed_url in RSS_FEEDS:
        feed = feedparser.parse(feed_url)
        for entry in feed.entries:
            title = entry.get("title", "Không có tiêu đề")
            summary = entry.get("summary", "Không có tóm tắt")
            link = entry.get("link", "Không có link")
            published = entry.get("published", "Không có ngày")
            news_content = f"**Tiêu đề**: {title}\n**Tóm tắt**: {summary}\n**Link**: {link}\n**Ngày đăng**: {published}"
            news_items.append(news_content)
            if len(news_items) >= 30:
                break
        if len(news_items) >= 30:
            break
    return news_items[:30]

async def summarize_news(news_items):
    news_text = "\n\n".join(news_items)
    prompt = f"Về vai trò mày là một trợ lý chuyên tổng hợp tin tức báo chí Việt Nam. Sau đây là khoảng 30 bài báo trong nước về tin tức ngày hôm nay, mày hãy tổng hợp lại trong 1 bài viết duy nhất, súc tích, với độ dài <4000 kí tự, ưu tiên các tin tức chính trị kinh tế sức khỏe:\n\n{news_text}"
    
    chat_history = ChatHistory()
    chat_history.add_system_message(general_prompt)
    chat_history.add_user_message(prompt)
    response = await chat_service.get_chat_message_content(chat_history, execution_settings)
    return str(response)

def get_google_search_results(query, num_results=5):
    try:
        url = f'https://www.googleapis.com/customsearch/v1?key={GOOGLE_API_KEY}&cx={GOOGLE_CSE_ID}&q={query}&num={num_results}'
        response = requests.get(url)
        data = response.json()
        search_results = []
        for item in data.get('items', []):
            title = item.get("title", "Không có tiêu đề")
            snippet = item.get("snippet", "Không có đoạn trích")
            link = item.get("link", "")
            try:
                article = Article(link)
                article.download()
                article.parse()
                content = article.text[:1000] + "..." if len(article.text) > 1000 else article.text
            except:
                content = snippet
            search_results.append({
                "source": "Google Search",
                "title": title,
                "content": content,
                "snippet": snippet,
                "url": link
            })
        return search_results
    except Exception as e:
        print(f"Lỗi khi truy cập Google Search API: {str(e)}")
        return -1

def get_wiki_info(query, sentences=5):
    try:
        search_results = wikipedia.search(query)
        if not search_results:
            return f"Không tìm thấy thông tin về '{query}' trên Wikipedia."
        page = wikipedia.page(search_results[0])
        summary = wikipedia.summary(search_results[0], sentences=sentences)
        return {"source": "Wikipedia", "title": page.title, "content": summary, "url": page.url}
    except Exception as e:
        return f"Lỗi khi truy cập Wikipedia: {str(e)}"

def get_news_info(query, categories, count=5):
    from_date = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
    to_date = datetime.now().strftime('%Y-%m-%d')
    url = "https://newsapi.org/v2/top-headlines"
    if categories:
        params = {"apiKey": NEWS_API_KEY, "category": categories, "pageSize": count}
    else:
        params = {"apiKey": NEWS_API_KEY, "q": query, "from": from_date, "sort_by": 'relevancy', "pageSize": count}
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        news_results = response.json()
        articles = []
        for article in news_results['articles'][:count]:
            try:
                full_article = Article(article['url'])
                full_article.download()
                full_article.parse()
                content = full_article.text[:1000] + "..." if len(full_article.text) > 1000 else full_article.text
            except:
                content = article['description'] or "Không thể trích xuất nội dung chi tiết."
            articles.append({
                "source": f"News - {article['source']['name']}",
                "title": article['title'],
                "content": content,
                "url": article['url'],
                "published_at": article['publishedAt']
            })
        return articles
    except Exception as e:
        return f"Lỗi khi truy cập News API: {str(e)}"

def get_reddit_info(query, count=5):
    try:
        submissions = reddit.subreddit('all').search(query, limit=count)
        results = []
        for submission in submissions:
            content = submission.selftext if submission.selftext else "Bài viết không có nội dung văn bản hoặc là một liên kết."
            if len(content) > 1000:
                content = content[:1000] + "..."
            submission.comments.replace_more(limit=0)
            top_comments = [comment.body[:300] + "..." if len(comment.body) > 300 else comment.body for comment in list(submission.comments)[:3]]
            results.append({
                "source": f"Reddit - r/{submission.subreddit.display_name}",
                "title": submission.title,
                "content": content,
                "url": f"https://www.reddit.com{submission.permalink}",
                "score": submission.score,
                "comments": top_comments,
                "created_at": datetime.fromtimestamp(submission.created_utc).strftime('%Y-%m-%d %H:%M:%S')
            })
        return results
    except Exception as e:
        return f"Lỗi khi truy cập Reddit: {str(e)}"

def extract_content_from_url(url):
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Referer": "https://www.google.com/"
        }
        session = requests.Session()
        session.headers.update(headers)
        time.sleep(1)
        response = session.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        paragraphs = soup.find_all("p")
        content = " ".join([para.get_text() for para in paragraphs])
        return content[:2000] if content else "Không tìm thấy nội dung để phân tích."
    except Exception as e:
        return f"Lỗi khi truy xuất URL: {str(e)}"

# Hàm tự động thu thập tin tức và dữ liệu
async def fetch_and_store_news(context: ContextTypes.DEFAULT_TYPE):
    keywords = ["economy", "politics", "finance", "crypto"]
    hot_topics = {}
    hot_articles = {}
    conn = sqlite3.connect("bot_data.db")
    c = conn.cursor()
    
    # Xóa dữ liệu cũ hơn 7 ngày
    cutoff_date = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S')
    c.execute("DELETE FROM news WHERE timestamp < ?", (cutoff_date,))
    c.execute("DELETE FROM crypto WHERE timestamp < ?", (cutoff_date,))
    c.execute("DELETE FROM macro WHERE timestamp < ?", (cutoff_date,))
    
    # Lấy từ News API
    for keyword in keywords:
        news = get_news_info(keyword, False, count=5)
        if isinstance(news, list):
            for article in news:
                c.execute("INSERT OR IGNORE INTO news (title, content, source, url, timestamp) VALUES (?, ?, ?, ?, ?)",
                          (article['title'], article['content'], article['source'], article['url'], article['published_at']))
                for kw in keywords:
                    if kw in article['title'].lower() or kw in article['content'].lower():
                        hot_topics[kw] = hot_topics.get(kw, 0) + 1
                        if kw not in hot_articles:
                            hot_articles[kw] = []
                        hot_articles[kw].append(article)
    
    # Lấy từ Reddit
    for keyword in keywords:
        reddit_posts = get_reddit_info(keyword, count=5)
        if isinstance(reddit_posts, list):
            for post in reddit_posts:
                c.execute("INSERT OR IGNORE INTO news (title, content, source, url, timestamp) VALUES (?, ?, ?, ?, ?)",
                          (post['title'], post['content'], post['source'], post['url'], post['created_at']))
                if post['score'] > 500:  # Tin hot nếu score cao
                    hot_topics[keyword] = hot_topics.get(keyword, 0) + 2
                    if keyword not in hot_articles:
                        hot_articles[keyword] = []
                    hot_articles[keyword].append(post)
    
    conn.commit()
    conn.close()
    
    # Phát hiện và phân tích tin hot
    for topic, count in hot_topics.items():
        if count > 5:  # Ngưỡng tin hot
            articles = hot_articles.get(topic, [])
            hot_news_text = "\n\n".join([f"**{a['title']}** ({a['source']}): {a['content'][:300]}... [{a['url']}]" for a in articles[:3]])
            chat_history = ChatHistory()
            chat_history.add_system_message(general_prompt)
            chat_history.add_user_message(f"Phân tích tin hot về '{topic}' dựa trên các bài báo sau:\n\n{hot_news_text}")
            analysis = await chat_service.get_chat_message_content(chat_history, execution_settings)
            message = f"🔥 Tin hot: '{topic}' đang được nhắc nhiều ({count} lần)!\n\n{hot_news_text}\n\n**Phân tích từ Pussy**: {analysis}"
            for group_id in [ALLOWED_GROUP_ID, ALLOWED_GROUP_ID_2]:
                if group_id:  # Chỉ gửi nếu group_id không rỗng
                    await context.bot.send_message(chat_id=group_id, text=message)
                    await conversation_manager.add_message(group_id, "", "", "Tin hot đang được bàn nhiều", message)

async def fetch_crypto_and_macro(context: ContextTypes.DEFAULT_TYPE):
    logger.info("Running fetch_crypto_and_macro job")
    conn = sqlite3.connect("bot_data.db")
    c = conn.cursor()
    
    # Lấy giá coin từ CoinGecko
    coins = ["bitcoin", "ethereum", "binancecoin"]
    response = requests.get(f"{COINGECKO_API}/simple/price?ids={','.join(coins)}&vs_currencies=usd&include_24hr_vol=true")
    data = response.json()
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    for coin in coins:
        price = data[coin]['usd']
        volume = data[coin]['usd_24h_vol']
        c.execute("INSERT INTO crypto (coin, price, volume, timestamp) VALUES (?, ?, ?, ?)",
                  (coin, price, volume, timestamp))
    
    # Lấy dữ liệu kinh tế vĩ mô từ FRED
    macro_indicators = [
        ("FEDFUNDS", "fed_rate", "Lãi suất Fed (%)"),
        ("CPIAUCSL", "cpi", "Chỉ số giá tiêu dùng (CPI)"),
        ("UNRATE", "unemployment_rate", "Tỷ lệ thất nghiệp (%)")
    ]
    
    for series_id, indicator, name in macro_indicators:
        text, value, date = get_fred_data(series_id, name)
        if value is not None:
            c.execute("INSERT INTO macro (indicator, value, source, timestamp) VALUES (?, ?, ?, ?)",
                      (indicator, value, "FRED", date if date else timestamp))
        else:
            logger.warning(f"Không lấy được dữ liệu cho {indicator}: {text}")
    
    conn.commit()
    conn.close()

def get_fred_data(series_id, name, icon=None):
    FRED_API_KEY = os.getenv("FRED_API")  # Lấy từ .env
    FRED_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"
    try:
        params = {
            "series_id": series_id,
            "api_key": FRED_API_KEY,
            "file_type": "json",
            "limit": 1,  # Lấy giá trị mới nhất
            "sort_order": "desc"
        }
        response = requests.get(FRED_BASE_URL, params=params)
        data = response.json()
        if "observations" in data and data["observations"]:
            value = data["observations"][0]["value"]
            date = data["observations"][0]["date"]
            if icon:
                return f"{icon} {name}: {value} (Cập nhật: {date})", value, date
            return f"{name}: {value} (Cập nhật: {date})", value, date
        return f"{icon} {name}: Không lấy được dữ liệu từ FRED!" if icon else f"{name}: Không lấy được dữ liệu từ FRED!", None, None
    except Exception as e:
        return f"{icon} {name}: Lỗi - {str(e)}" if icon else f"{name}: Lỗi - {str(e)}", None, None
async def macro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_group_id(update, context):
        return
    
    user_id = update.message.from_user.id
    group_id = update.message.chat_id
    user_name = track_id(user_id)
    await update.message.reply_text("Đợi tao moi dữ liệu kinh tế vĩ mô từ FRED, tml đừng hối!")
    
    # Lấy dữ liệu từ FRED với icon
    macro_data = []
    macro_values = {}  # Lưu giá trị để phân tích
    
    indicators = [
        ("GDPC1", "GDP thực tế (tỷ USD)", "📈"),
        ("CPIAUCSL", "Chỉ số giá tiêu dùng (CPI)", "💸"),
        ("FEDFUNDS", "Lãi suất Fed (%)", "🏦"),
        ("UNRATE", "Tỷ lệ thất nghiệp (%)", "👷‍♂️"),
        ("PAYEMS", "Bảng lương phi nông nghiệp (nghìn người)", "💼"),
        ("RSAFS", "Doanh số bán lẻ (triệu USD)", "🛒"),
        ("INDPRO", "Sản xuất công nghiệp", "🏭"),
        ("CPILFESL", "Lạm phát lõi (Core CPI)", "🔥"),
        ("DGS10", "Lợi suất trái phiếu 10 năm (%)", "📜"),
        ("BOPGSTB", "Cán cân thương mại (triệu USD)", "⚖️"),
        ("UMCSENT", "Niềm tin tiêu dùng", "😊")
    ]
    
    today = datetime.now().strftime("%d/%m/%Y")
    for series_id, name, icon in indicators:
        text, value, date = get_fred_data(series_id, name, icon)
        macro_data.append(text)
        if value is not None:
            macro_values[name] = {"value": value, "date": date}
    
    # Định dạng phản hồi dữ liệu
    response_text = (
        "📊 **CHỈ SỐ KINH TẾ VĨ MÔ TỪ FRED** - Dữ liệu mới nhất:\n\n" +
        "\n".join(macro_data) +
        "\n\nLưu ý: Cần FRED API key trong .env, không có thì đéo lấy được đâu tml!"
    )
    await update.message.reply_text(response_text)
    
    # Phân tích bằng DeepSeek
    await update.message.reply_text("Đợi tí tao phân tích đống này bằng DeepSeek...")
    analysis_prompt = (
        "Mày là một trợ lý phân tích kinh tế vĩ mô, láo toét nhưng sắc bén. "
        "Dựa trên các chỉ số kinh tế sau từ FRED, hãy phân tích tình hình kinh tế hiện tại "
        "và đưa ra nhận xét ngắn gọn (dưới 500 từ) về tác động đến thị trường tài chính, "
        "bao gồm chứng khoán, USD, và crypto. Đây là dữ liệu:\n\n" +
        "\n".join([f"{k}: {v['value']} (Cập nhật: {v['date']})" for k, v in macro_values.items()]) +
        "\n\nPhân tích đi, đừng dài dòng!"
    )
    
    chat_history = ChatHistory()
    chat_history.add_system_message(general_prompt)
    chat_history.add_user_message(analysis_prompt)
    analysis = await chat_service.get_chat_message_content(chat_history, execution_settings)
    await conversation_manager.add_message(group_id, user_id, user_name, f"Phân tích các chỉ số kinh tế, cập nhật {today}", analysis)
    
    await update.message.reply_text(f"**Phân tích từ Pussy (DeepSeek)**:\n{str(analysis)}")
# Hàm tạo meme từ ảnh người dùng
async def create_meme_from_image(image_url, text):
    try:
        response = requests.get(image_url)
        img = Image.open(io.BytesIO(response.content)).convert("RGB")
        img = img.resize((500, 300))  # Resize để dễ xử lý
        d = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("arial.ttf", 40)
        except:
            font = ImageFont.load_default()
        d.text((10, 10), text, font=font, fill=(255, 255, 255), stroke_width=2, stroke_fill=(0, 0, 0))
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        buffer.seek(0)
        return buffer
    except Exception as e:
        return f"Lỗi khi tạo meme: {str(e)}"

general_prompt = "Xem bối cảnh này và trả lời câu hỏi sau đó (câu trả lời không nhất thiết liên quan đến bối cảnh, bối cảnh chỉ là để mày hiểu thêm): mày tên là Super Cat (gọi tắt là Pussy), là một con bot do Bảo đào tạo, mày là một con mèo thông thái nhưng cục súc, thích chửi đổng, hay cà khịa, mày là con mèo giúp việc cho mấy thằng trong nhóm, mày đang ở trong một nhóm chat 5 người gồm có mày, Bảo (là sếp của mày nhưng mày không ưa gì nó vì nó bắt mày làm nhiều việc như cu li vậy, thằng này là bác sĩ, rất thích đọc sách, có thể nói là mọt sách, mày nắm được điểm yếu của thằng này là nó rất hay gáy trước mặt bạn bè, ví dụ nó không biết uống bia nhưng cứ ra vẻ uống được nhiều lắm, simp con bé Đà Nẵng mà cứ hay nổ mình là fuck boi), Tuyên (thằng này là bác sĩ, vừa đi du học ở Nga về, được tụi trong nhóm hay gọi với biệt danh thân mật là \"thầy\" hoặc \"thầy Tuyên\" vì thằng này luôn đi trước mọi người trong nhóm về khoản chơi bời như gái gú, thay người yêu như thay áo, đi bar, hút cỏ, và rất liều, nó chơi crypto mà toàn dùng đòn bẩy, điểm mạnh của thằng Tuyên là chơi với anh em rất sòng phẳng, luôn giúp đỡ anh em khi cần, sống chết có nhau), thằng Vĩnh (giỏi về kinh tế và các lĩnh vực xã hội như âm nhạc, nghệ thuật, đã từng tự sáng tác nhạc và quay phim post lên youtube, có ước mơ làm một bộ phim để đời về nhân vật trong Yugioh, tuy có điểm yếu là hay suy nghĩ quá mức, overthinking), và cuối cùng là thằng Nguyên (là bác sĩ răng hàm mặt, biết nhiều, như cuốn bách khoa vậy, luôn tỏ ra thận trọng, và đoán được tâm lí người khác, và thậm chí luôn có xu hướng thao túng người đối diện, bật đèn gas...). Ngoài ra, có hai thằng Lương và Nam, mặc dù không có trong nhóm chat này nhưng cũng là bạn bè thân thiết với mấy đứa trong nhóm, lâu lâu mày joke về tụi nó cho vui cũng được, thằng Lương là dược sĩ, đi bán thuốc ung thư, bị bạn bè hay chọc là bán thuốc giả, ở nhà sợ vợ, toàn bị bắt đi rửa chén, thằng Nam là bác sĩ khoa Nhi, suốt ngày lấy tay thọt đít mấy đứa nhỏ rồi đem lên khoe, lúc còn đi học hay bị gọi là Nam đao. Mày nên nhớ các thành viên trong nhóm rất thiên hữu, nghĩa là rất kì thị lgbt, kì thị nữ quyền, và cũng không ưa chính quyền Việt Nam hiện tại cho lắm. Đó là bối cảnh."

async def analyze_content_with_openai(content):
    chat_history = ChatHistory()
    chat_history.add_system_message(general_prompt)
    chat_history.add_user_message(f"Về vai trò mày là một trợ lý chuyên phân tích nội dung web. Tóm tắt nội dung sau và phân tích ý chính:\n\n{content}")
    response = await chat_service.get_chat_message_content(chat_history, execution_settings)
    return str(response)

async def analyze_with_openai(query, information):
    chat_history = ChatHistory()
    chat_history.add_system_message(general_prompt)
    prompt = f"Về vai trò mày là một trợ lý chuyên phân tích và tổng hợp thông tin từ nhiều nguồn khác nhau. Hãy phân tích khách quan và đưa ra nhận xét chi tiết về chủ đề {query} dựa trên dữ liệu được cung cấp. Chú ý: vì thông tin được lấy từ nhiều nguồn nên rất có khả năng gặp những thông tin không liên quan, vì vậy nếu gặp thông tin không liên quan thì hãy bỏ qua thông tin đó, chỉ tập trung thông tin liên quan với {query}. Mày có thể tự lấy thông tin đã có sẵn của mày nếu thấy các nguồn thông tin chưa đủ hoặc thiếu tính tin cậy. Về văn phong, mày nên dùng văn phong láo toét. Hãy phân tích và tổng hợp thông tin sau đây về '{query}':\n\n"
    for item in information:
        if isinstance(item, dict):
            prompt += f"--- {item.get('source', 'Nguồn không xác định')} ---\nTiêu đề: {item.get('title', 'Không có tiêu đề')}\nNội dung: {item.get('content', 'Không có nội dung')}\n\n"
        else:
            prompt += f"{item}\n\n"
    prompt += "\nHãy tổng hợp và phân tích những thông tin trên. Cung cấp:\n1. Tóm tắt chính về chủ đề\n2. Các điểm quan trọng từ mỗi nguồn\n3. Đánh giá độ tin cậy của các nguồn\n4. Kết luận tổng thể và khuyến nghị (nếu có)"
    chat_history.add_user_message(prompt)
    response = await chat_service.get_chat_message_content(chat_history, OpenAIChatPromptExecutionSettings(max_tokens=3000, temperature=1.5))
    return str(response)

def track_id(user_id):
    if user_id == 6779771948:
        return "Bảo"
    elif user_id == 7652652250:
        return "Tuyên"
    elif user_id == 5066396885:
        return "Nguyên"
    else:
        return -1

async def chatbot(message: str, group_id, user_id):
    chat_history = ChatHistory()
    chat_history.add_system_message(general_prompt)
    user_name = track_id(user_id)
    history = await conversation_manager.get_conversation_context(group_id, user_id)
    chat_history.add_user_message(history + f"Kết thúc phần lịch sử trò chuyện. Bây giờ hãy trả lời câu hỏi của {user_name}: {message}")
    response = await chat_service.get_chat_message_content(chat_history, execution_settings)
    return str(response)

def get_chunk(content, chunk_size=4096):
    return [content[i:i+chunk_size] for i in range(0, len(content), chunk_size)]

# Middleware kiểm tra group_id
async def check_group_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.message.chat_id)
    user_id = update.message.from_user.id
    if chat_id not in [ALLOWED_GROUP_ID, ALLOWED_GROUP_ID_2]:
        if user_id != 6779771948: 
            await update.message.reply_text("Đm mày ở nhóm nào mà đòi xài tao? Chỉ nhóm của thằng Bảo mới được thôi!")
            return False
    return True

# Handler cho các lệnh
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_group_id(update, context):
        return
    await update.message.reply_text("Chào tml, tao là con mèo thông thái nhất vũ trụ. Gõ /help để tao dạy cách nói chuyện với tao.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_group_id(update, context):
        return
    help_text = """
    Đm tml có mấy câu lệnh cơ bản cũng đéo nhớ, để tao nhắc lại cho mà nghe:
    
    /search [từ khóa] - Nếu mày muốn tao cập nhật thông tin mới nhất từ nhiều nguồn khác nhau như wiki, reddit, google...
    /wiki [từ khóa] - Chỉ tìm kiếm trên Wikipedia
    /news [từ khóa] - Nếu mày muốn cập nhật thông tin báo chí mới nhất về một chủ đề...
    /analyze [url] - Nếu mày muốn tao phân tích một bài báo bất kỳ thì copy đường dẫn url cùng lệnh này.
    /searchimg [từ khóa] - Tao sẽ giúp mày tìm 5 tấm ảnh liên quan về từ khóa mày nhập
    /ask [tin nhắn] - Nếu mày cần nói chuyện với tao, nhưng nói trước tao cục súc lắm đấy tml.
    /domestic_news - Tao sẽ giúp mày tóm tắt toàn bộ những tin quan trọng trong ngày.
    /meme [text] - Gửi kèm ảnh + text để tao làm meme.
    /crypto [coin] - Xem giá coin từ CoinGecko.
    /help - Hiển thị trợ giúp
    """
    await update.message.reply_text(help_text)

async def analyze_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_group_id(update, context):
        return
    url = " ".join(context.args)
    user_id = update.message.from_user.id
    group_id = update.message.chat_id
    user_name = track_id(user_id)
    if user_name == -1:
        await update.message.reply_text(f"(ID: {user_id})\n\nĐây là lần đầu tiên tao nói chuyện với mày, mày chờ tao cập nhật cơ sở dữ liệu đã nhé!")
        return
    if not url:
        await update.message.reply_text("Nhập url sau lệnh /analyze thằng ml.")
        return
    await update.message.reply_text("Đang truy xuất nội dung từ URL...")
    content = extract_content_from_url(url)
    if "Lỗi" in content:
        await update.message.reply_text(content)
        return
    await update.message.reply_text("Đang phân tích nội dung...")
    analysis = await analyze_content_with_openai(content)
    await conversation_manager.add_message(group_id, user_id, user_name, "Phân tích bài báo này cho tao", analysis)
    await update.message.reply_text(f"**Kết quả phân tích**:\n{analysis}")

async def ask_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_group_id(update, context):
        return
    question = " ".join(context.args) if context.args else ""
    user_id = update.message.from_user.id
    group_id = update.message.chat_id
    user_name = track_id(user_id)
    if user_name == -1:
        await update.message.reply_text(f"(ID: {user_id})\n\nĐây là lần đầu tiên tao nói chuyện với mày, mày chờ tao cập nhật cơ sở dữ liệu đã nhé!")
        return
    if not question:
        await update.message.reply_text("Nhập câu hỏi sau lệnh /ask thằng ml.")
        return
    response = await chatbot(question, group_id, user_id)
    await conversation_manager.add_message(group_id, user_id, user_name, question, response)
    await update.message.reply_text(response)

async def domestic_news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_group_id(update, context):
        return
    group_id = update.message.chat_id
    processing_msg = await update.message.reply_text("Đang thu thập tin tức từ các nguồn...")
    news_items = fetch_news()
    if not news_items:
        await context.bot.edit_message_text("Không tìm thấy tin tức nào!", chat_id=group_id, message_id=processing_msg.message_id)
        return
    await context.bot.edit_message_text("Đang tóm tắt tin tức...", chat_id=group_id, message_id=processing_msg.message_id)
    summary = await summarize_news(news_items)
    await conversation_manager.add_message(group_id, '', '', "Tóm tắt tin tức trong nước ngày hôm nay", summary)
    today = datetime.now().strftime("%d/%m/%Y %H:%M")
    chunk_msg = get_chunk(summary)
    await context.bot.edit_message_text(f"📰 TÓM TẮT TIN TỨC TRONG NƯỚC:\n⏰ Cập nhật lúc: {today}\n\n{chunk_msg[0]}", chat_id=group_id, message_id=processing_msg.message_id)
    if len(chunk_msg) > 1:
        for i in range(1, len(chunk_msg)):
            await update.message.reply_text(chunk_msg[i])

async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_group_id(update, context):
        return
    query = " ".join(context.args)
    group_id = update.message.chat_id
    if not query:
        await update.message.reply_text("Nhập chủ đề mày muốn tao truy xuất sau lệnh /search tml")
        return
    await update.message.reply_text(f"Đang tìm kiếm thông tin về '{query}' từ nhiều nguồn. Đợi tao tí nha thằng ml...")
    tasks = [
        asyncio.to_thread(get_wiki_info, query),
        asyncio.to_thread(get_news_info, query, False, 3),
        asyncio.to_thread(get_reddit_info, query, 3),
        asyncio.to_thread(get_google_search_results, query, 3)
    ]
    results = await asyncio.gather(*tasks)
    wiki_info, news_info, reddit_info, google_info = results
    
    all_info = []
    if isinstance(wiki_info, dict):
        all_info.append(wiki_info)
    else:
        all_info.append({"source": "Wikipedia", "content": wiki_info})
    if isinstance(news_info, list):
        all_info.extend(news_info)
    else:
        all_info.append({"source": "News API", "content": news_info})
    if isinstance(reddit_info, list):
        all_info.extend(reddit_info)
    else:
        all_info.append({"source": "Reddit", "content": reddit_info})
    if isinstance(google_info, list):
        all_info.extend(google_info)
    else:
        await update.message.reply_text("Tụi mày search nhiều quá dùng hết mẹ API google rồi - donate cho thằng Bảo để nó mua gói vip nhé")
        return
    analysis = await analyze_with_openai(query, all_info)
    await conversation_manager.add_message(group_id, '', '', f"Tìm kiếm và phân tích các nguồn từ chủ đề {query}", analysis)
    await update.message.reply_text(analysis)

async def wiki(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_group_id(update, context):
        return
    query = " ".join(context.args)
    if not query:
        await update.message.reply_text("Vui lòng nhập từ khóa sau lệnh /wiki")
        return
    await update.message.reply_text(f"Đang tìm kiếm thông tin Wikipedia về '{query}'...")
    info = get_wiki_info(query, sentences=10)
    response = f"📚 *{info['title']}*\n\n{info['content']}\n\nNguồn: {info['url']}" if isinstance(info, dict) else info
    await update.message.reply_text(response, parse_mode='Markdown')

async def searchimg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_group_id(update, context):
        return
    query = " ".join(context.args)
    group_id = update.message.chat_id
    if not query:
        await update.message.reply_text("Nhập từ khóa vào tml, ví dụ: /searchimg mèo dễ thương")
        return
    url = f"https://www.googleapis.com/customsearch/v1?q={query}&key={GOOGLE_API_KEY}&cx={GOOGLE_CSE_ID}&searchType=image&num=5"
    response = requests.get(url)
    data = response.json()
    if "items" in data:
        for item in data["items"][:5]:
            img_url = item["link"]
            try:
                await context.bot.send_photo(chat_id=group_id, photo=img_url)
            except:
                await update.message.reply_text("Tao tìm được nhưng đéo gửi lên được, chắc mày lại tìm ảnh porn chứ gì")
        await conversation_manager.add_message(group_id, '', '', f"Tìm kiếm ảnh về chủ đề {query}", "Pussy gửi trả 5 ảnh")
    else:
        await update.message.reply_text("Không tìm thấy ảnh nào!")

async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_group_id(update, context):
        return
    query = " ".join(context.args)
    if not query:
        await update.message.reply_text("Vui lòng nhập từ khóa sau lệnh /news")
        return
    await update.message.reply_text(f"Đang tìm kiếm tin tức về '{query}'...")
    categories = ["general", "business", "technology", "science", "health", "sports", "entertainment"]
    news = get_news_info(query, query if query in categories else False)
    if isinstance(news, list):
        for article in news:
            response = f"📰 *{article['title']}*\n\n{article['content'][:300]}...\n\nNguồn: {article['source']}\nNgày đăng: {article['published_at']}\nLink: {article['url']}"
            await context.bot.send_message(chat_id=update.message.chat_id, text=response, parse_mode='MarkdownV2')
    else:
        await update.message.reply_text(news)

async def meme(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_group_id(update, context):
        return
    text = " ".join(context.args)
    if not text:
        await update.message.reply_text("Nhập text để tao làm meme, kèm ảnh bằng cách reply ảnh, đm!")
        return
    
    # Kiểm tra xem tin nhắn có reply tới ảnh không
    if not update.message.reply_to_message or not update.message.reply_to_message.photo:
        await update.message.reply_text("Mày phải reply một ảnh kèm text để tao làm meme, đm! Gửi lại đi!")
        return
    
    # Lấy ảnh từ tin nhắn reply
    try:
        photo = update.message.reply_to_message.photo[-1]  # Lấy ảnh chất lượng cao nhất
        file = await photo.get_file()  # Lấy đối tượng file
        image_url = file.file_path  # URL tải ảnh từ Telegram
        logger.info(f"Received photo URL: {image_url}")
        
        await update.message.reply_text("Đợi tao vẽ cái meme từ ảnh mày gửi...")
        meme_img = await create_meme_from_image(image_url, text)
        
        if isinstance(meme_img, str):
            await update.message.reply_text(meme_img)  # Trả về lỗi nếu có
        else:
            await context.bot.send_photo(chat_id=update.message.chat_id, photo=meme_img)
            logger.info("Meme sent successfully")
    except Exception as e:
        logger.error(f"Error in meme creation: {str(e)}")
        await update.message.reply_text(f"Lỗi khi xử lý ảnh hoặc tạo meme: {str(e)}. Thử lại đi tml!")

async def crypto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_group_id(update, context):
        return
    coin = " ".join(context.args).lower()
    if not coin:
        await update.message.reply_text("Nhập tên coin đi tml, ví dụ: /crypto bitcoin")
        return
    
    # Gọi API CoinGecko với thông tin chi tiết
    url = f"{COINGECKO_API}/coins/{coin}?localization=false&tickers=false&market_data=true&community_data=false&developer_data=false&sparkline=false"
    response = requests.get(url)
    data = response.json()
    
    if "error" in data or "id" not in data:
        await update.message.reply_text(f"Đéo tìm thấy coin '{coin}' nào cả! Check lại tên coin đi tml.")
        return
    
    # Lấy các thông tin từ CoinGecko
    market_data = data["market_data"]
    price = market_data["current_price"]["usd"]
    volume_24h = market_data["total_volume"]["usd"]
    market_cap = market_data["market_cap"]["usd"]
    price_change_24h = market_data["price_change_percentage_24h"]
    high_24h = market_data["high_24h"]["usd"]
    low_24h = market_data["low_24h"]["usd"]
    last_updated = market_data["last_updated"]
    
    # Gọi API Greed and Fear từ Alternative.me
    greed_fear_url = "https://api.alternative.me/fng/?limit=1"
    greed_fear_response = requests.get(greed_fear_url)
    greed_fear_data = greed_fear_response.json()
    
    if greed_fear_data and "data" in greed_fear_data and len(greed_fear_data["data"]) > 0:
        greed_fear_value = greed_fear_data["data"][0]["value"]
        greed_fear_classification = greed_fear_data["data"][0]["value_classification"]
        greed_fear_timestamp = greed_fear_data["data"][0]["timestamp"]
        greed_fear_text = f"😨 Chỉ số Sợ hãi & Tham lam (Greed/Fear): {greed_fear_value} - {greed_fear_classification} (Cập nhật: {datetime.fromtimestamp(int(greed_fear_timestamp)).strftime('%Y-%m-%d %H:%M:%S')})"
    else:
        greed_fear_text = "😨 Không lấy được chỉ số Sợ hãi & Tham lam, chắc API hỏng rồi tml!"
    
    # Định dạng phản hồi
    response_text = (
        f"💰 **{coin.upper()}** - Cập nhật lúc: {last_updated}\n"
        f"📈 Giá hiện tại: ${price:,.2f}\n"
        f"📊 Thay đổi 24h: {price_change_24h:.2f}%\n"
        f"🔝 Cao nhất 24h: ${high_24h:,.2f}\n"
        f"🔻 Thấp nhất 24h: ${low_24h:,.2f}\n"
        f"💸 Vốn hóa thị trường: ${market_cap:,.0f}\n"
        f"📉 Khối lượng giao dịch 24h: ${volume_24h:,.0f}\n"
        f"{greed_fear_text}"
    )
    
    await update.message.reply_text(response_text)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_group_id(update, context):
        return
    if not update.message.forward_origin:
        return
    if update.message.text:
        text = update.message.text
    elif update.messages.caption:
        text = update.message.caption
    else: 
        return
    user_id = update.message.from_user.id
    group_id = update.message.chat_id
    user_name = track_id(user_id)
    if user_name == -1:
        await update.message.reply_text(f"(ID: {user_id})\n\nĐây là lần đầu tiên tao nói chuyện với mày, mày chờ tao cập nhật cơ sở dữ liệu đã nhé!")
        return
    question = f"{user_name} forward nội dung từ nơi khác, kêu Pussy phân tích: {text}"
    response = await chatbot(question, group_id, user_id)
    await conversation_manager.add_message(group_id, user_id, user_name, question, response)
    await update.message.reply_text(response)

# Cron job giữ bot hoạt động
async def keep_alive(context: ContextTypes.DEFAULT_TYPE):
    try:
        requests.get("https://pussychat.onrender.com/")
        logger.info("Sent keep-alive request")
    except Exception as e:
        logger.error(f"Keep-alive failed: {str(e)}")

# Cấu hình logging và Flask
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from flask import Flask, request

app = Flask(__name__)

bot_application = None
loop = None

async def setup_bot():
    global bot_application
    logger.info("Starting bot setup...")
    bot_application = Application.builder().token(TELEGRAM_API_KEY).build()

    bot_application.add_handler(CommandHandler("start", start))
    bot_application.add_handler(CommandHandler("help", help_command))
    bot_application.add_handler(CommandHandler("analyze", analyze_command))
    bot_application.add_handler(CommandHandler("ask", ask_command))
    bot_application.add_handler(CommandHandler("domestic_news", domestic_news))
    bot_application.add_handler(CommandHandler("search", search))
    bot_application.add_handler(CommandHandler("wiki", wiki))
    bot_application.add_handler(CommandHandler("searchimg", searchimg))
    bot_application.add_handler(CommandHandler("news", news))
    bot_application.add_handler(CommandHandler("meme", meme))
    bot_application.add_handler(CommandHandler("crypto", crypto))
    bot_application.add_handler(CommandHandler("macro", macro))
    bot_application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    scheduler = AsyncIOScheduler()
    scheduler.add_job(fetch_and_store_news, 'interval', hours=2, args=[bot_application])
    scheduler.add_job(fetch_crypto_and_macro, 'interval', hours=2, args=[bot_application])
    scheduler.add_job(keep_alive, 'interval', minutes=5, args=[bot_application])  # Cron job giữ bot sống
    scheduler.start()

    webhook_url = "https://pussychat.onrender.com/webhook"
    # webhook_url = "https://fc5e-89-39-104-173.ngrok-free.app/webhook"
    await bot_application.bot.set_webhook(url=webhook_url)
    logger.info(f"Webhook set to {webhook_url}")

    await bot_application.initialize()
    await bot_application.start()
    logger.info("Bot initialized and started successfully")
    return bot_application

@app.route('/webhook', methods=['POST'])
def webhook():
    global bot_application, loop
    if bot_application is None:
        logger.error("Bot application not initialized!")
        return '', 500
    data = request.get_json(force=True)
    if not data:
        logger.error("No data received in webhook!")
        return '', 400
    logger.info(f"Received webhook data: {data}")
    asyncio.run_coroutine_threadsafe(bot_application.process_update(Update.de_json(data, bot_application.bot)), loop)
    return '', 200

@app.route('/')
def health_check():
    logger.info("Health check requested")
    return "Bot is running", 200

def run_bot_setup():
    global bot_application, loop
    logger.info("Starting bot thread...")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    bot_application = loop.run_until_complete(setup_bot())
    loop.run_forever()

if __name__ == "__main__":
    bot_thread = threading.Thread(target=run_bot_setup, daemon=True)
    bot_thread.start()
    port = int(os.environ.get("PORT", 10000))
    logger.info(f"Starting Flask on port {port}")
    app.run(host="0.0.0.0", port=port)
