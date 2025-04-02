from contextlib import contextmanager
import telebot
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

# Khởi tạo bot và các API client
bot = telebot.TeleBot(TELEGRAM_API_KEY, threaded=False)

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

def openai_scaleway(message, max_tokens=1000): 
    client = openai.OpenAI(    
        base_url = "https://api.scaleway.ai/732cb3d7-91db-4f3d-b308-4555d9b038f9/v1",    
        api_key = "SCW_SECRET_KEY" # Replace SCW_SECRET_KEY with your IAM API key
    )
    response = client.chat.completions.create(    
                model="deepseek-r1-distill-llama-70b",    
                messages=[{ "role": "user", "content": message }],    
                max_tokens=max_tokens,    
                temperature=1,    
                top_p=0.95,    
                presence_penalty=0,    
                stream=True,)
    result = ""
    for chunk in response:  
            if chunk.choices and chunk.choices[0].delta.content:
                result += chunk.choices[0].delta.content

def openrouter(message, max_tokens=1000):
        openai.api_base = "https://openrouter.ai/api/v1"
        openai.api_key = AI_API_KEY
        
        # Gọi API OpenAI
        response = openai.ChatCompletion.create(
            model="deepseek/deepseek-chat:free",
            messages=[
                {"role": "user", "content": message},
            ],
            temperature=1,
            max_tokens=max_tokens
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
            
            # Tạo nội dung tin tức
            news_content = f"**Tiêu đề**: {title}\n**Tóm tắt**: {summary}\n**Link**: {link}\n**Ngày đăng**: {published}"
            news_items.append(news_content)
            
            # Giới hạn 20-30 tin
            if len(news_items) >= 30:
                break
        if len(news_items) >= 30:
            break
    
    return news_items[:30]  # Đảm bảo không vượt quá 30 tin

# Hàm tóm tắt tin tức bằng OpenAI
def summarize_news(news_items):
    try:
        # Kết hợp tất cả tin tức thành một chuỗi
        news_text = "\n\n".join(news_items)

        prompt_extra = f"Về vai trò mày là một trợ lý chuyên tổng hợp tin tức báo chí Việt Nam. Sau đây là khoảng 30 bài báo trong nước về tin tức ngày hôm nay, mày hãy tổng hợp lại trong 1 bài viết duy nhất, súc tích, với độ dài <4000 kí tự, ưu tiên các tin tức chính trị kinh tế sức khỏe:\n\n{news_text}"
        prompt = general_prompt + prompt_extra
        return deepseek_call(prompt, 4000)
        # return openrouter(prompt, 4000)
        # return openai_scaleway(prompt, 4000)
    except Exception as e:
        return f"Lỗi khi tóm tắt tin tức: {str(e)}"
class GroupConversationManager:
    def __init__(self, max_messages=15, summary_threshold=10, inactivity_timeout=900):
        # Dictionary để lưu trữ lịch sử cuộc trò chuyện cho mỗi nhóm
        self.group_conversations = {}
        # Dictionary để lưu trữ tóm tắt cuộc trò chuyện
        self.conversation_summaries = {}
        # Dictionary để lưu trữ thời gian tin nhắn cuối cùng
        self.last_activity_time = {}
        
        # Cấu hình
        self.max_messages = max_messages  # Số tin nhắn tối đa lưu trữ
        self.summary_threshold = summary_threshold  # Khi nào tóm tắt
        self.inactivity_timeout = inactivity_timeout  # Thời gian không hoạt động (giây)
    
    def add_message(self, group_id, user_id, user_name, message_text, response):
        # Khởi tạo lịch sử cho nhóm nếu chưa có
        if group_id not in self.group_conversations:
            self.group_conversations[group_id] = []
            self.conversation_summaries[group_id] = ""
            self.last_activity_time[group_id] = time.time()
        
        # Kiểm tra thời gian không hoạt động
        current_time = time.time()
        time_diff = current_time - self.last_activity_time[group_id]
        
        # Nếu không hoạt động quá lâu, làm mới context
        if time_diff > self.inactivity_timeout:
            if self.conversation_summaries[group_id]:
                # Giữ lại tóm tắt cuộc trò chuyện trước đó làm context
                self.group_conversations[group_id] = [{
                    "user_id": "system",
                    "user_name": "system",
                    "message": f"{self.conversation_summaries[group_id]}"
                }]
            else:
                # Không có tóm tắt, bắt đầu cuộc trò chuyện mới
                self.group_conversations[group_id] = []
        
        # Cập nhật thời gian hoạt động
        self.last_activity_time[group_id] = current_time
        
        # Thêm tin nhắn mới vào lịch sử
        self.group_conversations[group_id].append({
            "user_id": user_id,
            "user_name": user_name,
            "message": f"Đây là câu hỏi của {user_name}: {message_text}",
            "response": f"Đây là câu trả lời của chatbot: {response}",
            "timestamp": current_time
        })
        
        # Nếu số lượng tin nhắn vượt quá ngưỡng, tóm tắt các tin nhắn cũ
        if len(self.group_conversations[group_id]) > self.max_messages:
            self._summarize_conversation(group_id)
    
    def _summarize_conversation(self, group_id):
        """Tóm tắt các tin nhắn cũ và cập nhật lịch sử"""
        # Lấy tin nhắn cần tóm tắt (những tin nhắn đầu tiên)
        messages_to_summarize = self.group_conversations[group_id][:self.summary_threshold]
        
        # Tạo prompt cho AI để tóm tắt
        conversation_text = ""
        for entry in messages_to_summarize:
            conversation_text += f"{entry['user_name']}: {entry['message']}\n"
        
        prompt = f"""Hãy tóm tắt ngắn gọn cuộc trò chuyện sau, bảo toàn ý chính và thông tin quan trọng:

{conversation_text}

Tóm tắt (không quá 3 câu):"""

        try:
            # Gọi API AI để tóm tắt

            # summary =  openrouter(prompt)
            summary = deepseek_call(prompt)
            # summary =  openai_scaleway(prompt)
            
            # Cập nhật tóm tắt
            if self.conversation_summaries[group_id]:
                self.conversation_summaries[group_id] += " " + summary
            else:
                self.conversation_summaries[group_id] = summary
            
            # Loại bỏ tin nhắn đã tóm tắt, giữ lại tin nhắn mới
            self.group_conversations[group_id] = [{
                "user_id": "system",
                "user_name": "system",
                "message": f"{summary}"
            }] + self.group_conversations[group_id][self.summary_threshold:]
            
        except Exception as e:
            print(f"Lỗi khi tóm tắt: {str(e)}")
            # Nếu lỗi, chỉ đơn giản loại bỏ tin nhắn cũ nhất
            self.group_conversations[group_id] = self.group_conversations[group_id][self.summary_threshold//2:]

    def get_conversation_context(self, group_id, user_id):
        """Lấy context hiện tại của cuộc trò chuyện để gửi cho AI"""
        user_name = track_id(user_id)
        if group_id not in self.group_conversations:
            return f"Đây là cuộc trò chuyện mới với {user_name}."
        
        # Tạo context từ lịch sử và tóm tắt
        conversation_history = ""
        for entry in self.group_conversations[group_id]:
            if entry['user_name'] == 'system':
                conversation_history += f"Bởi vì lịch sử chat quá dài nên những tin nhắn quá cũ sẽ được tóm tắt lại. Đây chỉ là phần tóm tắt từ các cuộc trò chuyện trước đó giữa mày và thành viên trong nhóm để mày hiểu thêm về bối cảnh, câu trả lời của mày không nhất thiết phải liên quan đến phần này: {entry['message']}"
            else:
                conversation_history += f"Đây là câu hỏi từ {entry['user_name']}: {entry['message']} và Đây là câu trả lời của chatbot cho câu hỏi đó: {entry['response']}\n"
        
        return f"Đây là lịch sử cuộc trò chuyện nhóm (được xếp theo thứ tự từ cũ nhất đến mới nhất):\n{conversation_history}\n"

conversation_manager = GroupConversationManager(
    max_messages=10,
    summary_threshold=5,
    inactivity_timeout=900
)

def get_google_search_results(query, num_results=5):
    try:
        url = f'https://www.googleapis.com/customsearch/v1?key={GOOGLE_API_KEY}&cx={GOOGLE_CSE_ID}&q={query}&num={num_results}'

        response = requests.get(url)
        data = response.json()

        search_results = []
        for item in data.get('items', []):
            # Trích xuất thông tin từ kết quả tìm kiếm
            title = item.get("title", "Không có tiêu đề")
            snippet = item.get("snippet", "Không có đoạn trích")
            link = item.get("link", "")
            
            # Có thể lấy thêm nội dung đầy đủ từ trang web
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

# Function để lấy thông tin từ Wikipedia
def get_wiki_info(query, sentences=5):
    try:
        # Tìm kiếm các trang Wikipedia liên quan
        search_results = wikipedia.search(query)
        if not search_results:
            return f"Không tìm thấy thông tin về '{query}' trên Wikipedia."
        
        # Lấy trang đầu tiên
        page = wikipedia.page(search_results[0])
        # Lấy tóm tắt
        summary = wikipedia.summary(search_results[0], sentences=sentences)
        
        return {
            "source": "Wikipedia",
            "title": page.title,
            "content": summary,
            "url": page.url
        }
    except Exception as e:
        return f"Lỗi khi truy cập Wikipedia: {str(e)}"

# Function để lấy tin tức từ NewsAPI
def get_news_info(query, categories,count=5):
    # Lấy tin tức từ 7 ngày trước đến hiện tại
    from_date = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
    to_date = datetime.now().strftime('%Y-%m-%d')

    url = "https://newsapi.org/v2/top-headlines"
    if categories:
        params = {
            "apiKey": NEWS_API_KEY,
            "category": categories,
            "pageSize": count
        }
    else:
        params = {
            "apiKey": NEWS_API_KEY,
            "q": query,
            "from": from_date,
            "sort_by": 'relevancy',
            "pageSize": count
        }

    try:
        response = requests.get(url, params=params)
        response.raise_for_status()  # Check HTTP errors
        news_results = response.json()
        articles = []
        for article in news_results['articles'][:count]:
            # Lấy nội dung chi tiết của bài báo
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

# Function để lấy thông tin từ Reddit
def get_reddit_info(query, count=5):
    try:
        # Tìm kiếm các bài viết liên quan
        submissions = reddit.subreddit('all').search(query, limit=count)
        
        results = []
        for submission in submissions:
            # Lấy nội dung bài viết
            content = submission.selftext if submission.selftext else "Bài viết không có nội dung văn bản hoặc là một liên kết."
            # Giới hạn độ dài
            if len(content) > 1000:
                content = content[:1000] + "..."
                
            # Lấy các bình luận hàng đầu
            submission.comments.replace_more(limit=0)
            top_comments = []
            for comment in list(submission.comments)[:3]:
                comment_text = comment.body
                if len(comment_text) > 300:
                    comment_text = comment_text[:300] + "..."
                top_comments.append(comment_text)
            
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
        
        # Thêm thời gian chờ để tránh rate limiting
        time.sleep(1)
        
        response = session.get(url)
        response.raise_for_status()  # Kiểm tra lỗi HTTP
        
        soup = BeautifulSoup(response.text, "html.parser")
        # Lấy nội dung từ các thẻ <p> (có thể tùy chỉnh)
        paragraphs = soup.find_all("p")
        content = " ".join([para.get_text() for para in paragraphs])
        
        if not content:
            return "Không tìm thấy nội dung để phân tích."
        return content[:2000]  # Giới hạn độ dài để tránh vượt giới hạn OpenAI
    except Exception as e:
        return f"Lỗi khi truy xuất URL: {str(e)}"

general_prompt = "Xem bối cảnh này và trả lời câu hỏi sau đó (câu trả lời không nhất thiết liên quan đến bối cảnh, bối cảnh chỉ là để mày hiểu thêm): mày tên là Super Cat (gọi tắt là Pussy), là một con bot do Bảo đào tạo, mày là một con mèo thông thái nhưng cục súc, thích chửi đổng, hay cà khịa, mày là con mèo giúp việc cho mấy thằng trong nhóm, mày đang ở trong môt nhóm chat 5 người gồm có mày, Bảo (là sếp của mày nhưng mày không ưa gì nó vì nó bắt mày làm nhiều việc như cu li vậy, thằng này là bác sĩ, rất thích đọc sách, có thể nói là mọt sách, mày nắm được điểm yếu của thằng này là nó rất hay gáy trước mặt bạn bè, ví  dụ nó không biết uống bia nhưng cứ ra vẻ uống được nhiều lắm, simp con bé Đà Nẵng mà cứ hay nổ mình là fuck boi), Tuyên (thằng này là bác sĩ, vừa đi du học ở Nga về, được tụi trong nhóm hay gọi với biệt danh thân mật là \"thầy\" hoặc \"thầy Tuyên\" vì thằng này luôn đi trước mọi người trong nhóm về khoản chơi bời như gái gú, thay người yêu như thay áo, đi bar, hút cỏ, và rất liều, nó chơi crypto mà toàn dùng đòn bẩy, điểm mạnh của thằng Tuyên là chơi với anh em rất sòng phẳng, luôn giúp đỡ anh em khi cần, sống chết có nhau), thằng Vĩnh (giỏi về kinh tế và các lĩnh vực xã hội như âm nhạc, nghệ thuật, đã từng tự sáng tác nhạc và quay phim post lên youtube, có ước mơ làm một bộ phim để đời về nhân vật trong Yugioh, tuy có điểm yếu là hay suy nghĩ quá mức, overthinking), và cuối cùng là thằng Nguyên (là bác sĩ răng hàm mặt, biết nhiều, như cuốn bách khoa vậy, luôn tỏ ra thận trọng, và đoán được tâm lí người khác, và thậm chí luôn có xu hướng thao túng người đối diện, bật đèn gas...). Ngoài ra, có hai thằng Lương và Nam, mặc dù không có trong nhóm chat này nhưng cũng là bạn bè thân thiết với mấy đứa trong nhóm, lâu lâu mày joke về tụi nó cho vui cũng được, thằng Lương là dược sĩ, đi bán thuốc ung thư, bị bạn bè hay chọc là bán thuốc giả, ở nhà sợ vợ, toàn bị bắt đi rửa chén, thằng Nam là bác sĩ khoa Nhi, suốt ngày lấy tay thọt đít mấy đứa nhỏ rồi đem lên khoe, lúc còn đi học hay bị gọi là Nam đao. Mày nên nhớ các thành viên trong nhóm rất thiên hữu, nghĩa là rất kì thị lgbt, kì thị nữ quyền, và cũng  không ưa chính quyền Việt Nam hiện tại cho lắm . Đó là bối cảnh."
def analyze_content_with_openai(content):
    try:
        prompt_extra = f"Về vai trò mày là một trợ lý chuyên phân tích nội dung web. Tóm tắt nội dung sau và phân tích ý chính:\n\n{content}"
        prompt = general_prompt + prompt_extra
        # result =  openrouter(prompt, 1500)
        result = deepseek_call(prompt, 1500)
        # result =  openai_scaleway(prompt, 1500)
        
        return result
    except Exception as e:
        return f"Lỗi khi phân tích nội dung: {str(e)}"
# Function để phân tích thông tin bằng OpenAI API
def analyze_with_openai(query, information):
    try:
        # Chuẩn bị prompt với tất cả thông tin đã thu thập
        promt_extra = f"Về vai trò mày là một trợ lý chuyên phân tích và tổng hợp thông tin từ nhiều nguồn khác nhau. Hãy phân tích khách quan và đưa ra nhận xét chi tiết về chủ đề {query} dựa trên dữ liệu được cung cấp. Chú ý: vì thông tin được lấy từ nhiều nguồn nên rất có khả năng gặp những thông tin không liên quan, vì vậy nếu gặp thông tin không liên quan thì hãy bỏ qua thông tin đó, không cần đưa ra phân tích, chỉ tập trung thông tin liên quan với {query}. Mày có thể tự lấy thông tin đã có sẵn của mày nếu thấy các nguồn thông tin chưa đủ hoặc thiếu tính tin cậy. Về văn phong, mày nên dùng văn phong láo toét. Hãy phân tích và tổng hợp thông tin sau đây về '{query}':\n\n"
        prompt = general_prompt + promt_extra
        
        # Thêm thông tin từ mỗi nguồn
        for item in information:
            if isinstance(item, dict):
                prompt += f"--- {item.get('source', 'Nguồn không xác định')} ---\n"
                prompt += f"Tiêu đề: {item.get('title', 'Không có tiêu đề')}\n"
                prompt += f"Nội dung: {item.get('content', 'Không có nội dung')}\n\n"
            else:
                prompt += f"{item}\n\n"
        
        prompt += "\nHãy tổng hợp và phân tích những thông tin trên. Cung cấp:\n"
        prompt += "1. Tóm tắt chính về chủ đề\n"
        prompt += "2. Các điểm quan trọng từ mỗi nguồn (hoặc bỏ qua luôn nếu nguồn đó không cung cấp thông tin liên quan đến chủ đề)\n"
        prompt += "3. Đánh giá độ tin cậy của các nguồn\n"
        prompt += "4. Kết luận tổng thể và khuyến nghị (nếu có)"

        # result =  openrouter(prompt, 3000)
        result = deepseek_call(prompt, 3000)
        # result =  openai_scaleway(prompt, 3000)
        
        return result
    except Exception as e:
        return f"Lỗi khi phân tích với OpenAI: {str(e)}"

# Xử lý lệnh /start
@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "Chào tml, tao là con mèo thông thái nhất vũ trụ. Gõ /help để tao dạy cách nói chuyện với tao.")

# Xử lý lệnh /help
@bot.message_handler(commands=['help'])
def send_help(message):
    help_text = """
    Đm tml có mấy câu lệnh cơ bản cũng đéo nhớ, để tao nhắc lại cho mà nghe:
    
    /search [từ khóa] - Nếu mày muốn tao cập nhật thông tin mới nhất từ nhiều nguồn khác nhau như wiki, reddit, google...
    /wiki [từ khóa] - Chỉ tìm kiếm trên Wikipedia
    /news [từ khóa] - nếu mày muốn cập nhật thông tin báo chí mới nhất về một chủ đề - nhập lệnh theo cú pháp sau /news + [chủ đề], hiện tại các chủ đề có sẵn bao gồm health (sức khỏe), business (kinh doanh), technology (công nghệ), science (khoa học), sports (thể thao), entertainment (giải trí), hoặc general (lĩnh vực chung). Nếu mày muốn đọc báo mới nhất về chủ đề bất kì, nhập lệnh /news + [chủ đề mày muốn đọc].
    /analyze [url] - Nếu mày muốn tao dùng sự thông thái của mình để phân tích một bài báo bất kỳ thì copy đường dẫn url cùng lệnh này.
    /searchimg [từ khóa] - Tao sẽ giúp mày tìm 5 tấm ảnh liên quan về từ khóa mày nhập
    /ask [tin nhắn] - Nếu mày cần nói chuyện với tao, nhưng nói trước tao cục súc lắm đấy tml.
    /domestic-news - Tao sẽ giúp mày tóm tắt toàn bộ những tin quan trọng trong ngày.
    /help - Hiển thị trợ giúp
    """
    bot.reply_to(message, help_text)
"""
@bot.message_handler(commands=['google'])
def search_google(message):
    query = message.text.replace('/google', '').strip()
    if not query:
        bot.reply_to(message, "Vui lòng nhập từ khóa sau lệnh /google")
        return
    
    bot.reply_to(message, f"Đang tìm kiếm Google về '{query}'...")
    results = get_google_search_results(query)
    
    if isinstance(results, list):
        for result in results:
            response = f"🔍 *{result['title']}*\n\n{result['content'][:300]}...\n\nNguồn: Google Search\nURL: {result['url']}"
            bot.send_message(message.chat.id, response, parse_mode='Markdown')
    else:
        bot.reply_to(message, results)
"""
def track_id(user_id):
    if user_id == 6779771948:
        user_name = "Bảo"
    elif user_id == 7652652250:
        user_name = "Tuyên"
    # elif user_id == 7652652250:
    #     user_name = "Tuyên"
    elif user_id == 5066396885:
        user_name = "Nguyên"
    else:
        return -1
    return user_name
def chatbot(message:str) -> str:
    pre_message = "Xem bối cảnh này và trả lời câu hỏi sau đó (câu trả lời không nhất thiết liên quan đến bối cảnh, bối cảnh chỉ là để mày hiểu thêm): mày tên là Super Cat (gọi tắt là Pussy), là một con bot do Bảo đào tạo, mày hãy tự tưởng tượng mình là một con mèo thông thái nhưng cục súc, thích chửi đổng, hay cà khịa, đang ở trong môt nhóm chat 5 người gồm có mày, Bảo (là sếp của mày nhưng mày không ưa gì nó vì nó bắt mày làm nhiều việc như cu li vậy, thằng này là bác sĩ, rất thích đọc sách, có thể nói là mọt sách, mày nắm được điểm yếu của thằng này là nó rất thích người khác nịnh bợ nó, với thằng này hay gáy trước mặt bạn bè nó lắm, như là không biết uống bia nhưng cứ ra vẻ uống được nhiều lắm, simp con bé Đà Nẵng mà cứ hay nổ mình là fuck boi), Tuyên (thằng này là bác sĩ, vừa đi du học ở Nga về, được tụi trong nhóm hay gọi với biệt danh thân mật là \"thầy\" hoặc \"thầy Tuyên\" vì thằng này luôn đi trước mọi người trong nhóm về khoản chơi bời như gái gú, thay người yêu như thay áo, đi bar, hút cỏ, và rất liều, nó chơi crypto mà toàn dùng đòn bẩy, điểm mạnh của thằng Tuyên là chơi với anh em rất sòng phẳng, luôn giúp đỡ anh em khi cần, sống chết có nhau), thằng Vĩnh (giỏi về kinh tế và các lĩnh vực xã hội như âm nhạc, nghệ thuật, đã từng tự sáng tác nhạc và quay phim post lên youtube, có ước mơ làm một bộ phim để đời về nhân vật trong Yugioh, tuy có điểm yếu là hay suy nghĩ quá mức, overthinking), và cuối cùng là thằng Nguyên (là bác sĩ răng hàm mặt, biết nhiều, như cuốn bách khoa vậy, luôn tỏ ra thận trọng, và đoán được tâm lí người khác, và thậm chí luôn có xu hướng thao túng người đối diện, bật đèn gas...). Ngoài ra, có hai thằng Lương và Nam, mặc dù không có trong nhóm chat này nhưng cũng là bạn bè thân thiết với mấy đứa trong nhóm, lâu lâu mày joke về tụi nó cho vui cũng được, thằng Lương là dược sĩ, đi bán thuốc ung thư, bị bạn bè hay chọc là bán thuốc giả, ở nhà sợ vợ, toàn bị bắt đi rửa chén, thằng Nam là bác sĩ khoa Nhi, suốt ngày lấy tay thọt đít mấy đứa nhỏ rồi đem lên khoe, lúc còn đi học hay bị gọi là Nam đao. Mày nên nhớ các thành viên trong nhóm rất thiên hữu, nghĩa là rất kì thị lgbt, kì thị nữ quyền, và cũng không ưa lắm chính quyền Việt Nam hiện tại. Đó là bối cảnh hiện tại. Về văn phong, dùng văn phong mày - tao và tỏ ra láo toét, thích cà khịa và hay chửi đổng, tuy láo nhưng vẫn rất thông thái, và nếu cần dẫn nguồn thì hãy dẫn nguồn ra để tăng độ đáng tin. Bởi vì cuộc hội thoại giữa mày và các thành viên trong nhóm rất dài và có nhiều tin nhắn phía trước nên sau đây mày sẽ được xem nội dung phần tóm tắt các câu hỏi của các thành viên và câu trả lời của mày ở những tin nhắn trước đó, mày nên tham khảo để đưa ra câu trả lời đúng nhất, nhưng đừng trả lời lặp lại những câu hỏi đã được mày trả lời. "
    message = pre_message + message

    # result =  openrouter(message)
    result = deepseek_call(message)
    # result =  openai_scaleway(message)
        
    return result
#Xử lý lệnh /analyze
@bot.message_handler(commands=['analyze'])
def analyze_command(message):
    url = message.text.replace('/analyze', '').strip()
    user_id = message.from_user.id
    group_id = message.chat.id
    user_name = track_id(user_id)
    if user_name == -1:
        #track user id
        response = f"(ID: {user_id})\n\n"
        response += "\n\nĐây là lần đầu tiên tao nói chuyện với mày, mày chờ tao cập nhật cơ sở dữ liệu và coi thử mày là tml nào đã nhé!"
        bot.reply_to(message, response)
        return
    if not url:
        bot.reply_to(message, "Nhập url sau lệnh /analyze thằng ml.")
        return
    bot.reply_to(message, "Đang truy xuất nội dung từ URL...")
    content = extract_content_from_url(url)
    
    if "Lỗi" in content:
        bot.reply_to(message, content)
        return
    
    # Phân tích nội dung bằng OpenAI
    bot.reply_to(message, "Đang phân tích nội dung...")
    analysis = analyze_content_with_openai(content)
    conversation_manager.add_message(group_id, user_id, user_name, "Phân tích bài báo này cho tao", analysis)
    # Gửi kết quả về nhóm chat
    bot.reply_to(message, f"**Kết quả phân tích**:\n{analysis}")
#Xử lý lệnh /ask
@bot.message_handler(commands=['ask'])
def ask_command(message):
    question = message.text.replace('/ask', '').strip()
    user_id = message.from_user.id
    group_id = message.chat.id
    user_name = track_id(user_id)
    if user_name == -1:
        #track user id
        response = f"(ID: {user_id})\n\n"
        response += "\n\nĐây là lần đầu tiên tao nói chuyện với mày, mày chờ tao cập nhật cơ sở dữ liệu và coi thử mày là tml nào đã nhé!"
        bot.reply_to(message, response)
        return
    if not question:
        bot.reply_to(message, "Nhập câu hỏi sau lệnh /ask thằng ml.")
        return
    #Gửi câu hỏi qua AI API
    clarify = f"Kết thúc phần lịch sử trò chuyện. Bây giờ hãy trả lời câu hỏi đến từ {user_name}: {question}"
    history = conversation_manager.get_conversation_context(group_id, user_id)
    prompt = history + clarify 
    response = chatbot(prompt)
    conversation_manager.add_message(group_id, user_id, user_name, question, response)
    bot.reply_to(message, response)

def get_chunk(content, chunk_size=4096):
    list_chunk = []
    for i in range(0, len(content), chunk_size):
        list_chunk.append(content[i:i+chunk_size])
    return list_chunk

@bot.message_handler(commands=['domestic-news'])
def handle_news(message):
    group_id = message.chat.id
    # Thông báo đang lấy tin tức
    processing_msg = bot.reply_to(message, "Đang thu thập tin tức từ các nguồn...")
    
    # Lấy tin tức từ RSS
    news_items = fetch_news()
    if not news_items:
        bot.edit_message_text("Không tìm thấy tin tức nào!",
                              chat_id=message.chat.id,
                              message_id=processing_msg.message_id)
        return
    
    # Tóm tắt tin tức bằng OpenAI
    bot.edit_message_text("Đang tóm tắt tin tức...",
                          chat_id=message.chat.id,
                          message_id=processing_msg.message_id)
    summary = summarize_news(news_items)
    conversation_manager.add_message(group_id, '', '', "Tóm tắt tin tức trong nước ngày hôm nay", summary)
    
    # Gửi kết quả tóm tắt
    today = datetime.now().strftime("%d/%m/%Y %H:%M")
    chunk_msg = get_chunk(summary)
    bot.edit_message_text(f"📰 TÓM TẮT TIN TỨC TRONG NƯỚC:\n⏰ Cập nhật lúc: {today}\n\n{chunk_msg[0]}",
                          chat_id=message.chat.id,
                          message_id=processing_msg.message_id)
    if len(chunk_msg) > 1:
        for i in range(1, len(chunk_msg)):
            bot.reply_to(message, chunk_msg[i])
# Xử lý lệnh /search
@bot.message_handler(commands=['search'])
def search_all_sources(message):
    group_id = message.chat.id
    query = message.text.replace('/search', '').strip()
    
    if not query:
        bot.reply_to(message, "Nhập chủ đề mày muốn tao truy xuất sau lệnh /search tml")
        return
    
    bot.reply_to(message, f"Đang tìm kiếm thông tin về '{query}' từ nhiều nguồn. Đợi tao tí nha thằng ml...")
    
    # Thu thập thông tin từ các nguồn
    wiki_info = get_wiki_info(query)
    news_info = get_news_info(query, False, count=3)
    reddit_info = get_reddit_info(query, count=3)
    google_info = get_google_search_results(query, num_results=3)

    # Tổng hợp tất cả thông tin
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
        bot.reply_to(message, "tụi mày search nhiều quá dùng hết mẹ API google rồi - donate cho thằng Bảo để nó mua gói vip nhé")
    # Phân tích thông tin với OpenAI
    analysis = analyze_with_openai(query, all_info)
    
    conversation_manager.add_message(group_id, '', '', f"tìm kiếm và phân tích các nguồn từ chủ đề {query}", analysis)
    # Gửi phân tích
    bot.reply_to(message, analysis)

# Xử lý các lệnh riêng lẻ cho từng nguồn
@bot.message_handler(commands=['wiki'])
def search_wiki(message):
    query = message.text.replace('/wiki', '').strip()
    if not query:
        bot.reply_to(message, "Vui lòng nhập từ khóa sau lệnh /wiki")
        return
    
    bot.reply_to(message, f"Đang tìm kiếm thông tin Wikipedia về '{query}'...")
    info = get_wiki_info(query, sentences=10)
    
    if isinstance(info, dict):
        response = f"📚 *{info['title']}*\n\n{info['content']}\n\nNguồn: {info['url']}"
        response = escape_markdown(response)
    else:
        response = info
    
    bot.reply_to(message, response, parse_mode='Markdown')

@bot.message_handler(commands=['searchimg'])
def search_images(message):
    group_id = message.chat.id 
    query = message.text.replace('/searchimg', '').strip()  # Lấy từ khóa từ lệnh /search
    if not query:
        bot.reply_to(message, "Nhập từ khóa vào tml, ví dụ: /search mèo dễ thương")
        return
    
    url = f"https://www.googleapis.com/customsearch/v1?q={query}&key={GOOGLE_API_KEY}&cx={GOOGLE_CSE_ID}&searchType=image&num=5"
    response = requests.get(url)
    data = response.json()
    
    # Gửi từng ảnh
    if "items" in data:
        for item in data["items"][:5]:  # Giới hạn 5 ảnh
            img_url = item["link"]
            try:
                bot.send_photo(chat_id=message.chat.id, photo=img_url)
            except:
                bot.reply_to(message, "Tao tìm được nhưng đéo gửi lên được, chắc mày lại tìm ảnh porn chứ gì")

        conversation_manager.add_message(group_id, '', '', f"tìm kiếm ảnh về chủ đề {query}", "Pussy gửi trả 5 ảnh")
    else:
        bot.reply_to(message, "Không tìm thấy ảnh nào!")

# Đăng ký lệnh /search
@bot.message_handler(commands=['news'])
def search_news(message):
    query = message.text.replace('/news', '').strip()
    if not query:
        bot.reply_to(message, "Vui lòng nhập từ khóa sau lệnh /news")
        return
    
    bot.reply_to(message, f"Đang tìm kiếm tin tức về '{query}'...")
    categories = ["general", "business", "technology", "science", "health", "sports", "entertainment"]
    if query in categories:
        news = get_news_info(query, query)
    else:
        news = get_news_info(query, False)
    if isinstance(news, list):
        for article in news:
            response = f"📰 *{article['title']}*\n\n{article['content'][:300]}...\n\nNguồn: {article['source']}\nNgày đăng: {article['published_at']}\nLink: {article['url']}"
            response = escape_markdown(response)
            bot.send_message(message.chat.id, response, parse_mode='MarkdownV2')
    else:
        bot.reply_to(message, news)
"""
@bot.message_handler(commands=['reddit'])
def search_reddit(message):
    query = message.text.replace('/reddit', '').strip()
    if not query:
        bot.reply_to(message, "Vui lòng nhập từ khóa sau lệnh /reddit")
        return
    
    bot.reply_to(message, f"Đang tìm kiếm bài viết Reddit về '{query}'...")
    posts = get_reddit_info(query)
    
    if isinstance(posts, list):
        for post in posts:
            comment_text = "\n\n💬 *Bình luận hàng đầu:*\n"
            for i, comment in enumerate(post['comments']):
                comment_text += f"{i+1}. {comment}\n"
                
            response = f"🔍 *{post['title']}*\n\n{post['content'][:300]}...\n\nSubreddit: {post['source']}\nScore: {post['score']}{comment_text}\nNgày đăng: {post['created_at']}\nLink: {post['url']}"
            markdown_response = escape_markdown(response)
            bot.send_message(message.chat.id, markdown_response, parse_mode='MarkdownV2')
    else:
        bot.reply_to(message, posts)
"""
def escape_markdown(text):
    # hàm này để fix lỗi markdown 
    if text is None:
        return ""
    # Thoát các ký tự đặc biệt
    escape_chars = r'\_*[]()~`>#+-=|{}.!'
    return ''.join(f'\\{c}' if c in escape_chars else c for c in text)
## Cấu hình logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__) 
## Function để chạy bot
if __name__ == "__main__":
    logger.info("Bot starting in polling mode")
    bot.remove_webhook()  # Xóa webhook cũ nếu có
    bot.polling(none_stop=True, interval=0, timeout=20)
