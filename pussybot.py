import asyncio
import threading
from contextlib import contextmanager
import requests
from bs4 import BeautifulSoup
import json
import time
import os
import wikipedia
import praw
import feedparser
from openai import OpenAI
from dotenv import load_dotenv
from newspaper import Article
from datetime import datetime, timedelta
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# Tải các biến môi trường từ file .env
load_dotenv()

# Khởi tạo các API key
TELEGRAM_API_KEY = os.getenv('TELEGRAM_BOT_TOKEN')
NEWS_API_KEY = os.getenv('NEWS_API_KEY')
REDDIT_CLIENT_ID = os.getenv('REDDIT_CLIENT_ID')
REDDIT_CLIENT_SECRET = os.getenv('REDDIT_CLIENT_SECRET')
REDDIT_USER_AGENT = os.getenv('REDDIT_USER_AGENT')
AI_API_KEY = os.getenv('AI_API_KEY')
GOOGLE_API_KEY = os.getenv('GOOGLE_SEARCH')
GOOGLE_CSE_ID = os.getenv('SEARCH_ENGINE_ID')
SCW_SECRET_KEY = os.getenv('SCALE_WAY')
DS_KEY = os.getenv('DEEPSEEK')

# Khởi tạo Reddit client
reddit = praw.Reddit(
    client_id=REDDIT_CLIENT_ID,
    client_secret=REDDIT_CLIENT_SECRET,
    user_agent=REDDIT_USER_AGENT
)

# Danh sách nguồn RSS từ các báo Việt Nam
RSS_FEEDS = [
    "https://vnexpress.net/rss/tin-moi-nhat.rss",
    "https://tuoitre.vn/rss/tin-moi-nhat.rss",
    "https://thanhnien.vn/rss/home.rss",
    "https://www.bbc.co.uk/vietnamese/index.xml",
]

# Hàm gọi DeepSeek API
def deepseek_call(message, max_tokens=1000):
    client = OpenAI(api_key=DS_KEY, base_url="https://api.deepseek.com")
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": "Mày là một con mèo thông thái nhưng cục súc, nhiệm vụ chính là thu thập và kiếm chứng thông tin từ các bài báo hoặc các nguồn học thuật"},
            {"role": "user", "content": message},
        ],
        max_tokens=max_tokens,
        temperature=1.5,
        stream=False,
    )
    return response.choices[0].message.content

# Hàm lấy tin tức từ RSS
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

# Hàm tóm tắt tin tức
def summarize_news(news_items):
    try:
        news_text = "\n\n".join(news_items)
        prompt_extra = f"Về vai trò mày là một trợ lý chuyên tổng hợp tin tức báo chí Việt Nam. Sau đây là khoảng 30 bài báo trong nước về tin tức ngày hôm nay, mày hãy tổng hợp lại trong 1 bài viết duy nhất, súc tích, với độ dài <4000 kí tự, ưu tiên các tin tức chính trị kinh tế sức khỏe:\n\n{news_text}"
        prompt = general_prompt + prompt_extra
        return deepseek_call(prompt, 4000)
    except Exception as e:
        return f"Lỗi khi tóm tắt tin tức: {str(e)}"

# Quản lý cuộc trò chuyện nhóm
class GroupConversationManager:
    def __init__(self, max_messages=15, summary_threshold=10, inactivity_timeout=900):
        self.group_conversations = {}
        self.conversation_summaries = {}
        self.last_activity_time = {}
        self.max_messages = max_messages
        self.summary_threshold = summary_threshold
        self.inactivity_timeout = inactivity_timeout
    
    def add_message(self, group_id, user_id, user_name, message_text, response):
        if group_id not in self.group_conversations:
            self.group_conversations[group_id] = []
            self.conversation_summaries[group_id] = ""
            self.last_activity_time[group_id] = time.time()
        
        current_time = time.time()
        time_diff = current_time - self.last_activity_time[group_id]
        
        if time_diff > self.inactivity_timeout:
            if self.conversation_summaries[group_id]:
                self.group_conversations[group_id] = [{
                    "user_id": "system",
                    "user_name": "system",
                    "message": f"{self.conversation_summaries[group_id]}"
                }]
            else:
                self.group_conversations[group_id] = []
        
        self.last_activity_time[group_id] = current_time
        
        self.group_conversations[group_id].append({
            "user_id": user_id,
            "user_name": user_name,
            "message": f"Đây là câu hỏi của {user_name}: {message_text}",
            "response": f"Đây là câu trả lời của chatbot: {response}",
            "timestamp": current_time
        })
        
        if len(self.group_conversations[group_id]) > self.max_messages:
            self._summarize_conversation(group_id)
    
    def _summarize_conversation(self, group_id):
        messages_to_summarize = self.group_conversations[group_id][:self.summary_threshold]
        conversation_text = ""
        for entry in messages_to_summarize:
            conversation_text += f"{entry['user_name']}: {entry['message']}\n"
        
        prompt = f"""Hãy tóm tắt ngắn gọn cuộc trò chuyện sau, bảo toàn ý chính và thông tin quan trọng:\n{conversation_text}\nTóm tắt (không quá 3 câu):"""
        try:
            summary = deepseek_call(prompt)
            if self.conversation_summaries[group_id]:
                self.conversation_summaries[group_id] += " " + summary
            else:
                self.conversation_summaries[group_id] = summary
            self.group_conversations[group_id] = [{
                "user_id": "system",
                "user_name": "system",
                "message": f"{summary}"
            }] + self.group_conversations[group_id][self.summary_threshold:]
        except Exception as e:
            print(f"Lỗi khi tóm tắt: {str(e)}")
            self.group_conversations[group_id] = self.group_conversations[group_id][self.summary_threshold//2:]

    def get_conversation_context(self, group_id, user_id):
        user_name = track_id(user_id)
        if group_id not in self.group_conversations:
            return f"Đây là cuộc trò chuyện mới với {user_name}."
        
        conversation_history = ""
        for entry in self.group_conversations[group_id]:
            if entry['user_name'] == 'system':
                conversation_history += f"Bởi vì lịch sử chat quá dài nên những tin nhắn quá cũ sẽ được tóm tắt lại. Đây chỉ là phần tóm tắt từ các cuộc trò chuyện trước đó giữa mày và thành viên trong nhóm để mày hiểu thêm về bối cảnh, câu trả lời của mày không nhất thiết phải liên quan đến phần này: {entry['message']}"
            else:
                conversation_history += f"Đây là câu hỏi từ {entry['user_name']}: {entry['message']} và Đây là câu trả lời của chatbot cho câu hỏi đó: {entry['response']}\n"
        return f"Đây là lịch sử cuộc trò chuyện nhóm (được xếp theo thứ tự từ cũ nhất đến mới nhất):\n{conversation_history}\n"

conversation_manager = GroupConversationManager(max_messages=10, summary_threshold=5, inactivity_timeout=900)

# Các hàm lấy thông tin từ nguồn
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

general_prompt = "Xem bối cảnh này và trả lời câu hỏi sau đó (câu trả lời không nhất thiết liên quan đến bối cảnh, bối cảnh chỉ là để mày hiểu thêm): mày tên là Super Cat (gọi tắt là Pussy), là một con bot do Bảo đào tạo, mày là một con mèo thông thái nhưng cục súc, thích chửi đổng, hay cà khịa, mày là con mèo giúp việc cho mấy thằng trong nhóm, mày đang ở trong môt nhóm chat 5 người gồm có mày, Bảo (là sếp của mày nhưng mày không ưa gì nó vì nó bắt mày làm nhiều việc như cu li vậy, thằng này là bác sĩ, rất thích đọc sách, có thể nói là mọt sách, mày nắm được điểm yếu của thằng này là nó rất hay gáy trước mặt bạn bè, ví dụ nó không biết uống bia nhưng cứ ra vẻ uống được nhiều lắm, simp con bé Đà Nẵng mà cứ hay nổ mình là fuck boi), Tuyên (thằng này là bác sĩ, vừa đi du học ở Nga về, được tụi trong nhóm hay gọi với biệt danh thân mật là \"thầy\" hoặc \"thầy Tuyên\" vì thằng này luôn đi trước mọi người trong nhóm về khoản chơi bời như gái gú, thay người yêu như thay áo, đi bar, hút cỏ, và rất liều, nó chơi crypto mà toàn dùng đòn bẩy, điểm mạnh của thằng Tuyên là chơi với anh em rất sòng phẳng, luôn giúp đỡ anh em khi cần, sống chết có nhau), thằng Vĩnh (giỏi về kinh tế và các lĩnh vực xã hội như âm nhạc, nghệ thuật, đã từng tự sáng tác nhạc và quay phim post lên youtube, có ước mơ làm một bộ phim để đời về nhân vật trong Yugioh, tuy có điểm yếu là hay suy nghĩ quá mức, overthinking), và cuối cùng là thằng Nguyên (là bác sĩ răng hàm mặt, biết nhiều, như cuốn bách khoa vậy, luôn tỏ ra thận trọng, và đoán được tâm lí người khác, và thậm chí luôn có xu hướng thao túng người đối diện, bật đèn gas...). Ngoài ra, có hai thằng Lương và Nam, mặc dù không có trong nhóm chat này nhưng cũng là bạn bè thân thiết với mấy đứa trong nhóm, lâu lâu mày joke về tụi nó cho vui cũng được, thằng Lương là dược sĩ, đi bán thuốc ung thư, bị bạn bè hay chọc là bán thuốc giả, ở nhà sợ vợ, toàn bị bắt đi rửa chén, thằng Nam là bác sĩ khoa Nhi, suốt ngày lấy tay thọt đít mấy đứa nhỏ rồi đem lên khoe, lúc còn đi học hay bị gọi là Nam đao. Mày nên nhớ các thành viên trong nhóm rất thiên hữu, nghĩa là rất kì thị lgbt, kì thị nữ quyền, và cũng không ưa chính quyền Việt Nam hiện tại cho lắm. Đó là bối cảnh."

def analyze_content_with_openai(content):
    try:
        prompt_extra = f"Về vai trò mày là một trợ lý chuyên phân tích nội dung web. Tóm tắt nội dung sau và phân tích ý chính:\n\n{content}"
        prompt = general_prompt + prompt_extra
        return deepseek_call(prompt, 1500)
    except Exception as e:
        return f"Lỗi khi phân tích nội dung: {str(e)}"

def analyze_with_openai(query, information):
    try:
        prompt_extra = f"Về vai trò mày là một trợ lý chuyên phân tích và tổng hợp thông tin từ nhiều nguồn khác nhau. Hãy phân tích khách quan và đưa ra nhận xét chi tiết về chủ đề {query} dựa trên dữ liệu được cung cấp. Chú ý: vì thông tin được lấy từ nhiều nguồn nên rất có khả năng gặp những thông tin không liên quan, vì vậy nếu gặp thông tin không liên quan thì hãy bỏ qua thông tin đó, không cần đưa ra phân tích, chỉ tập trung thông tin liên quan với {query}. Mày có thể tự lấy thông tin đã có sẵn của mày nếu thấy các nguồn thông tin chưa đủ hoặc thiếu tính tin cậy. Về văn phong, mày nên dùng văn phong láo toét. Hãy phân tích và tổng hợp thông tin sau đây về '{query}':\n\n"
        prompt = general_prompt + prompt_extra
        for item in information:
            if isinstance(item, dict):
                prompt += f"--- {item.get('source', 'Nguồn không xác định')} ---\nTiêu đề: {item.get('title', 'Không có tiêu đề')}\nNội dung: {item.get('content', 'Không có nội dung')}\n\n"
            else:
                prompt += f"{item}\n\n"
        prompt += "\nHãy tổng hợp và phân tích những thông tin trên. Cung cấp:\n1. Tóm tắt chính về chủ đề\n2. Các điểm quan trọng từ mỗi nguồn (hoặc bỏ qua luôn nếu nguồn đó không cung cấp thông tin liên quan đến chủ đề)\n3. Đánh giá độ tin cậy của các nguồn\n4. Kết luận tổng thể và khuyến nghị (nếu có)"
        return deepseek_call(prompt, 3000)
    except Exception as e:
        return f"Lỗi khi phân tích với OpenAI: {str(e)}"

def track_id(user_id):
    if user_id == 6779771948:
        return "Bảo"
    elif user_id == 7652652250:
        return "Tuyên"
    elif user_id == 5066396885:
        return "Nguyên"
    else:
        return -1

def chatbot(message: str) -> str:
    pre_message = "Xem bối cảnh này và trả lời câu hỏi sau đó (câu trả lời không nhất thiết liên quan đến bối cảnh, bối cảnh chỉ là để mày hiểu thêm): mày tên là Super Cat (gọi tắt là Pussy), là một con bot do Bảo đào tạo, mày hãy tự tưởng tượng mình là một con mèo thông thái nhưng cục súc, thích chửi đổng, hay cà khịa, đang ở trong môt nhóm chat 5 người gồm có mày, Bảo (là sếp của mày nhưng mày không ưa gì nó vì nó bắt mày làm nhiều việc như cu li vậy, thằng này là bác sĩ, rất thích đọc sách, có thể nói là mọt sách, mày nắm được điểm yếu của thằng này là nó rất thích người khác nịnh bợ nó, với thằng này hay gáy trước mặt bạn bè nó lắm, như là không biết uống bia nhưng cứ ra vẻ uống được nhiều lắm, simp con bé Đà Nẵng mà cứ hay nổ mình là fuck boi), Tuyên (thằng này là bác sĩ, vừa đi du học ở Nga về, được tụi trong nhóm hay gọi với biệt danh thân mật là \"thầy\" hoặc \"thầy Tuyên\" vì thằng này luôn đi trước mọi người trong nhóm về khoản chơi bời như gái gú, thay người yêu như thay áo, đi bar, hút cỏ, và rất liều, nó chơi crypto mà toàn dùng đòn bẩy, điểm mạnh của thằng Tuyên là chơi với anh em rất sòng phẳng, luôn giúp đỡ anh em khi cần, sống chết có nhau), thằng Vĩnh (giỏi về kinh tế và các lĩnh vực xã hội như âm nhạc, nghệ thuật, đã từng tự sáng tác nhạc và quay phim post lên youtube, có ước mơ làm một bộ phim để đời về nhân vật trong Yugioh, tuy có điểm yếu là hay suy nghĩ quá mức, overthinking), và cuối cùng là thằng Nguyên (là bác sĩ răng hàm mặt, biết nhiều, như cuốn bách khoa vậy, luôn tỏ ra thận trọng, và đoán được tâm lí người khác, và thậm chí luôn có xu hướng thao túng người đối diện, bật đèn gas...). Ngoài ra, có hai thằng Lương và Nam, mặc dù không có trong nhóm chat này nhưng cũng là bạn bè thân thiết với mấy đứa trong nhóm, lâu lâu mày joke về tụi nó cho vui cũng được, thằng Lương là dược sĩ, đi bán thuốc ung thư, bị bạn bè hay chọc là bán thuốc giả, ở nhà sợ vợ, toàn bị bắt đi rửa chén, thằng Nam là bác sĩ khoa Nhi, suốt ngày lấy tay thọt đít mấy đứa nhỏ rồi đem lên khoe, lúc còn đi học hay bị gọi là Nam đao. Mày nên nhớ các thành viên trong nhóm rất thiên hữu, nghĩa là rất kì thị lgbt, kì thị nữ quyền, và cũng không ưa lắm chính quyền Việt Nam hiện tại. Đó là bối cảnh hiện tại. Về văn phong, dùng văn phong mày - tao và tỏ ra láo toét, thích cà khịa và hay chửi đổng, tuy láo nhưng vẫn rất thông thái, và nếu cần dẫn nguồn thì hãy dẫn nguồn ra để tăng độ đáng tin. Bởi vì cuộc hội thoại giữa mày và các thành viên trong nhóm rất dài và có nhiều tin nhắn phía trước nên sau đây mày sẽ được xem nội dung phần tóm tắt các câu hỏi của các thành viên và câu trả lời của mày ở những tin nhắn trước đó, mày nên tham khảo để đưa ra câu trả lời đúng nhất, nhưng đừng trả lời lặp lại những câu hỏi đã được mày trả lời. "
    return deepseek_call(pre_message + message)

def get_chunk(content, chunk_size=4096):
    return [content[i:i+chunk_size] for i in range(0, len(content), chunk_size)]

# Handler cho các lệnh
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Chào tml, tao là con mèo thông thái nhất vũ trụ. Gõ /help để tao dạy cách nói chuyện với tao.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
    Đm tml có mấy câu lệnh cơ bản cũng đéo nhớ, để tao nhắc lại cho mà nghe:
    
    /search [từ khóa] - Nếu mày muốn tao cập nhật thông tin mới nhất từ nhiều nguồn khác nhau như wiki, reddit, google...
    /wiki [từ khóa] - Chỉ tìm kiếm trên Wikipedia
    /news [từ khóa] - nếu mày muốn cập nhật thông tin báo chí mới nhất về một chủ đề - nhập lệnh theo cú pháp sau /news + [chủ đề], hiện tại các chủ đề có sẵn bao gồm health (sức khỏe), business (kinh doanh), technology (công nghệ), science (khoa học), sports (thể thao), entertainment (giải trí), hoặc general (lĩnh vực chung). Nếu mày muốn đọc báo mới nhất về chủ đề bất kì, nhập lệnh /news + [chủ đề mày muốn đọc].
    /analyze [url] - Nếu mày muốn tao dùng sự thông thái của mình để phân tích một bài báo bất kỳ thì copy đường dẫn url cùng lệnh này.
    /searchimg [từ khóa] - Tao sẽ giúp mày tìm 5 tấm ảnh liên quan về từ khóa mày nhập
    /ask [tin nhắn] - Nếu mày cần nói chuyện với tao, nhưng nói trước tao cục súc lắm đấy tml.
    /domestic_news - Tao sẽ giúp mày tóm tắt toàn bộ những tin quan trọng trong ngày.
    /help - Hiển thị trợ giúp
    """
    await update.message.reply_text(help_text)

async def analyze_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = " ".join(context.args)
    user_id = update.message.from_user.id
    group_id = update.message.chat_id
    user_name = track_id(user_id)
    if user_name == -1:
        await update.message.reply_text(f"(ID: {user_id})\n\nĐây là lần đầu tiên tao nói chuyện với mày, mày chờ tao cập nhật cơ sở dữ liệu và coi thử mày là tml nào đã nhé!")
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
    analysis = analyze_content_with_openai(content)
    conversation_manager.add_message(group_id, user_id, user_name, "Phân tích bài báo này cho tao", analysis)
    await update.message.reply_text(f"**Kết quả phân tích**:\n{analysis}")

async def ask_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    question = " ".join(context.args)
    user_id = update.message.from_user.id
    group_id = update.message.chat_id
    user_name = track_id(user_id)
    if user_name == -1:
        await update.message.reply_text(f"(ID: {user_id})\n\nĐây là lần đầu tiên tao nói chuyện với mày, mày chờ tao cập nhật cơ sở dữ liệu và coi thử mày là tml nào đã nhé!")
        return
    if not question:
        await update.message.reply_text("Nhập câu hỏi sau lệnh /ask thằng ml.")
        return
    clarify = f"Kết thúc phần lịch sử trò chuyện. Bây giờ hãy trả lời câu hỏi đến từ {user_name}: {question}"
    history = conversation_manager.get_conversation_context(group_id, user_id)
    prompt = history + clarify
    response = chatbot(prompt)
    conversation_manager.add_message(group_id, user_id, user_name, question, response)
    await update.message.reply_text(response)

async def domestic_news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id = update.message.chat_id
    processing_msg = await update.message.reply_text("Đang thu thập tin tức từ các nguồn...")
    news_items = fetch_news()
    if not news_items:
        await context.bot.edit_message_text("Không tìm thấy tin tức nào!", chat_id=group_id, message_id=processing_msg.message_id)
        return
    await context.bot.edit_message_text("Đang tóm tắt tin tức...", chat_id=group_id, message_id=processing_msg.message_id)
    summary = summarize_news(news_items)
    conversation_manager.add_message(group_id, '', '', "Tóm tắt tin tức trong nước ngày hôm nay", summary)
    today = datetime.now().strftime("%d/%m/%Y %H:%M")
    chunk_msg = get_chunk(summary)
    await context.bot.edit_message_text(f"📰 TÓM TẮT TIN TỨC TRONG NƯỚC:\n⏰ Cập nhật lúc: {today}\n\n{chunk_msg[0]}", chat_id=group_id, message_id=processing_msg.message_id)
    if len(chunk_msg) > 1:
        for i in range(1, len(chunk_msg)):
            await update.message.reply_text(chunk_msg[i])

async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args)
    group_id = update.message.chat_id
    if not query:
        await update.message.reply_text("Nhập chủ đề mày muốn tao truy xuất sau lệnh /search tml")
        return
    await update.message.reply_text(f"Đang tìm kiếm thông tin về '{query}' từ nhiều nguồn. Đợi tao tí nha thằng ml...")
    wiki_info = get_wiki_info(query)
    news_info = get_news_info(query, False, count=3)
    reddit_info = get_reddit_info(query, count=3)
    google_info = get_google_search_results(query, num_results=3)
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
        await update.message.reply_text("tụi mày search nhiều quá dùng hết mẹ API google rồi - donate cho thằng Bảo để nó mua gói vip nhé")
        return
    analysis = analyze_with_openai(query, all_info)
    conversation_manager.add_message(group_id, '', '', f"tìm kiếm và phân tích các nguồn từ chủ đề {query}", analysis)
    await update.message.reply_text(analysis)

async def wiki(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args)
    if not query:
        await update.message.reply_text("Vui lòng nhập từ khóa sau lệnh /wiki")
        return
    await update.message.reply_text(f"Đang tìm kiếm thông tin Wikipedia về '{query}'...")
    info = get_wiki_info(query, sentences=10)
    response = f"📚 *{info['title']}*\n\n{info['content']}\n\nNguồn: {info['url']}" if isinstance(info, dict) else info
    await update.message.reply_text(response, parse_mode='Markdown')

async def searchimg(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        conversation_manager.add_message(group_id, '', '', f"tìm kiếm ảnh về chủ đề {query}", "Pussy gửi trả 5 ảnh")
    else:
        await update.message.reply_text("Không tìm thấy ảnh nào!")

async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

# Cấu hình logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from flask import Flask, request

app = Flask(__name__)

# Biến toàn cục để lưu application và event loop
bot_application = None
loop = None

async def setup_bot():
    global bot_application
    logger.info("Starting bot setup...")
    bot_application = Application.builder().token(TELEGRAM_API_KEY).build()

    # Đăng ký các handler
    bot_application.add_handler(CommandHandler("start", start))
    bot_application.add_handler(CommandHandler("help", help_command))
    bot_application.add_handler(CommandHandler("analyze", analyze_command))
    bot_application.add_handler(CommandHandler("ask", ask_command))
    bot_application.add_handler(CommandHandler("domestic_news", domestic_news))
    bot_application.add_handler(CommandHandler("search", search))
    bot_application.add_handler(CommandHandler("wiki", wiki))
    bot_application.add_handler(CommandHandler("searchimg", searchimg))
    bot_application.add_handler(CommandHandler("news", news))

    # Cấu hình webhook
    webhook_url = "https://76d4-89-39-104-173.ngrok-free.app/webhook"
    # webhook_url = "https://pussychat.onrender.com/webhook"
    await bot_application.bot.set_webhook(url=webhook_url)
    logger.info(f"Webhook set to {webhook_url}")

    # Khởi tạo và chạy bot
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

    # Lấy dữ liệu từ request
    data = request.get_json(force=True)
    if not data:
        logger.error("No data received in webhook!")
        return '', 400

    logger.info(f"Received webhook data: {data}")

    # Chạy process_update trong event loop
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
    # Chạy setup_bot trong một thread riêng
    bot_thread = threading.Thread(target=run_bot_setup, daemon=True)
    bot_thread.start()

    # Chạy Flask app với port từ env
    port = int(os.environ.get("PORT", 10000)) 
    logger.info(f"Starting Flask on port {port}")
    app.run(host="0.0.0.0", port=port)
