import os
import requests
from bs4 import BeautifulSoup
import wikipedia
import praw
import feedparser
from dotenv import load_dotenv
from datetime import datetime, timedelta
from semantic_kernel import Kernel
from semantic_kernel.contents import ChatHistory
from openai import AsyncOpenAI
from semantic_kernel.connectors.ai.open_ai import OpenAIChatCompletion, OpenAIChatPromptExecutionSettings
import time
import logging
from build_prompt import general_prompt

from utils import GEMINI_API_KEY

logger = logging.getLogger(__name__)

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
    from conversation import conversation_manager
    chat_history = ChatHistory()
    chat_history.add_system_message(general_prompt)
    user_name = track_id(user_id)
    history = await conversation_manager.get_conversation_context(group_id, user_id)
    chat_history.add_user_message(history + f"Kết thúc phần lịch sử trò chuyện. Bây giờ hãy trả lời câu hỏi của {user_name}: {message}")
    response = await chat_service.get_chat_message_content(chat_history, execution_settings)
    return str(response)

async def analyze_content_with_openai(content):
    chat_history = ChatHistory()
    chat_history.add_system_message(general_prompt)
    chat_history.add_user_message(f"Về vai trò mày là một trợ lý chuyên phân tích nội dung web. Tóm tắt nội dung sau và phân tích ý chính:\n\n{content}")
    response = await chat_service.get_chat_message_content(chat_history, execution_settings)
    return str(response)

load_dotenv()
NEWS_API_KEY = os.getenv('NEWS_API_KEY')
REDDIT_CLIENT_ID = os.getenv('REDDIT_CLIENT_ID')
REDDIT_CLIENT_SECRET = os.getenv('REDDIT_CLIENT_SECRET')
REDDIT_USER_AGENT = os.getenv('REDDIT_USER_AGENT')
GOOGLE_API_KEY = os.getenv('GOOGLE_SEARCH')
GOOGLE_CSE_ID = os.getenv('SEARCH_ENGINE_ID')
AI_API_KEY = os.getenv('AI_API_KEY')

# COINGECKO_API = "https://api.coingecko.com/api/v3"
# FRED_API_KEY = os.getenv("FRED_API")
# FRED_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"

reddit = praw.Reddit(client_id=REDDIT_CLIENT_ID, client_secret=REDDIT_CLIENT_SECRET, user_agent=REDDIT_USER_AGENT)
RSS_FEEDS = [
    "https://vnexpress.net/rss/tin-moi-nhat.rss",
    "https://tuoitre.vn/rss/tin-moi-nhat.rss",
    "https://thanhnien.vn/rss/home.rss",
    "https://www.bbc.co.uk/vietnamese/index.xml",
]

kernel = Kernel()
chat_service = OpenAIChatCompletion(
    ai_model_id="deepseek-chat",
    async_client=AsyncOpenAI(api_key=AI_API_KEY, base_url="https://api.deepseek.com"),
)
execution_settings = OpenAIChatPromptExecutionSettings(max_tokens=1000, temperature=1.5)

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
            content = item.get("snippet", "Không có đoạn trích")
            link = item.get("link", "")
            search_results.append({
                "source": "Google Search",
                "title": title,
                "content": content,
                "url": link
            })
        return search_results
    except Exception as e:
        logger.error(f"Lỗi khi truy cập Google Search API: {str(e)}")
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

# async def fetch_crypto_and_macro(context):
#     conn = get_db_connection()
#     c = conn.cursor()
#
#     coins = ["bitcoin", "ethereum", "binancecoin"]
#     response = requests.get(f"{COINGECKO_API}/simple/price?ids={','.join(coins)}&vs_currencies=usd&include_24hr_vol=true")
#     data = response.json()
#     timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
#     for coin in coins:
#         price = data[coin]['usd']
#         volume = data[coin]['usd_24h_vol']
#         c.execute("INSERT INTO crypto (coin, price, volume, timestamp) VALUES (?, ?, ?, ?)",
#                   (coin, price, volume, timestamp))
#
#     macro_indicators = [
#         ("FEDFUNDS", "fed_rate", "Lãi suất Fed (%)"),
#         ("CPIAUCSL", "cpi", "Chỉ số giá tiêu dùng (CPI)"),
#         ("UNRATE", "unemployment_rate", "Tỷ lệ thất nghiệp (%)")
#     ]
#
#     for series_id, indicator, name in macro_indicators:
#         text, value, date = get_fred_data(series_id, name)
#         if value is not None:
#             c.execute("INSERT INTO macro (indicator, value, source, timestamp) VALUES (?, ?, ?, ?)",
#                       (indicator, value, "FRED", date if date else timestamp))
#         else:
#             logger.warning(f"Không lấy được dữ liệu cho {indicator}: {text}")
#
#     conn.commit()
#     conn.close()
#
# def get_fred_data(series_id, name, icon=None):
#     try:
#         params = {
#             "series_id": series_id,
#             "api_key": FRED_API_KEY,
#             "file_type": "json",
#             "limit": 1,
#             "sort_order": "desc"
#         }
#         response = requests.get(FRED_BASE_URL, params=params)
#         data = response.json()
#         if "observations" in data and data["observations"]:
#             value = data["observations"][0]["value"]
#             date = data["observations"][0]["date"]
#             if icon:
#                 return f"{icon} {name}: {value} (Cập nhật: {date})", value, date
#             return f"{name}: {value} (Cập nhật: {date})", value, date
#         return f"{icon} {name}: Không lấy được dữ liệu từ FRED!" if icon else f"{name}: Không lấy được dữ liệu từ FRED!", None, None
#     except Exception as e:
#         return f"{icon} {name}: Lỗi - {str(e)}" if icon else f"{name}: Lỗi - {str(e)}", None, None
#
async def analyze_with_openai(query, information):
    chat_history = ChatHistory()
    chat_history.add_system_message(general_prompt)
    prompt = f"Về vai trò mày là một trợ lý chuyên phân tích và tổng hợp thông tin từ nhiều nguồn khác nhau. Hãy phân tích khách quan và đưa ra nhận xét chi tiết về chủ đề {query} dựa trên dữ liệu được cung cấp. Chú ý: vì thông tin được lấy từ nhiều nguồn nên rất có khả năng gặp những thôngtin không liên quan, vì vậy nếu gặp thông tin không liên quan thì hãy bỏ qua thông tin đó, chỉ tập trung thông tin liên quan với {query}. Mày có thể tự lấy thông tin đã có sẵn của mày nếu thấy các nguồn thông tin chưa đủ hoặc thiếu tính tin cậy. Về văn phong, mày nên dùng văn phong láo toét. Hãy phân tích và tổng hợp thông tin sau đây về '{query}':\n\n"
    for item in information:
        if isinstance(item, dict):
            prompt += f"--- {item.get('source', 'Nguồn không xác định')} ---\nTiêu đề: {item.get('title', 'Không có tiêu đề')}\nNội dung: {item.get('content', 'Không có nội dung')}\n\n"
        else:
            prompt += f"{item}\n\n"
    prompt += "\nHãy tổng hợp và phân tích những thông tin trên. Cung cấp:\n1. Tóm tắt chính về chủ đề\n2. Các điểm quan trọng từ mỗi nguồn\n3. Đánh giá độ tin cậy của các nguồn\n4. Kết luận tổng thể và khuyến nghị (nếu có)"
    chat_history.add_user_message(prompt)
    response = await chat_service.get_chat_message_content(chat_history, OpenAIChatPromptExecutionSettings(max_tokens=2000, temperature=1.2))
    return str(response)
