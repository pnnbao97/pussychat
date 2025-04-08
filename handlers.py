from telegram import Update
from telegram.ext import CommandHandler, MessageHandler, filters, ContextTypes
from api import fetch_news, summarize_news, get_wiki_info, get_news_info, get_reddit_info, get_google_search_results, extract_content_from_url, analyze_with_openai
from utils import create_meme_from_image, track_id, get_chunk, check_group_id, analyze_content_with_openai, general_prompt, chatbot
from conversation import conversation_manager
from datetime import datetime
import requests
import logging
import os

logger = logging.getLogger(__name__)

ALLOWED_GROUP_ID = "-1002679588220"
ALLOWED_GROUP_ID_2 = ""
GOOGLE_API_KEY = os.getenv('GOOGLE_SEARCH')
GOOGLE_CSE_ID = os.getenv('SEARCH_ENGINE_ID')
COINGECKO_API = "https://api.coingecko.com/api/v3"

def setup_handlers(application):
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("analyze", analyze_command))
    application.add_handler(CommandHandler("ask", ask_command))
    application.add_handler(CommandHandler("domestic_news", domestic_news))
    application.add_handler(CommandHandler("search", search))
    application.add_handler(CommandHandler("wiki", wiki))
    application.add_handler(CommandHandler("searchimg", searchimg))
    application.add_handler(CommandHandler("news", news))
    application.add_handler(CommandHandler("meme", meme))
    application.add_handler(CommandHandler("crypto", crypto))
    application.add_handler(CommandHandler("macro", macro))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

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
    
    if not update.message.reply_to_message or not update.message.reply_to_message.photo:
        await update.message.reply_text("Mày phải reply một ảnh kèm text để tao làm meme, đm! Gửi lại đi!")
        return
    
    try:
        photo = update.message.reply_to_message.photo[-1]
        file = await photo.get_file()
        image_url = file.file_path
        logger.info(f"Received photo URL: {image_url}")
        
        await update.message.reply_text("Đợi tao vẽ cái meme từ ảnh mày gửi...")
        meme_img = await create_meme_from_image(image_url, text)
        
        if isinstance(meme_img, str):
            await update.message.reply_text(meme_img)
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
    
    user_id = update.message.from_user.id
    group_id = update.message.chat_id
    user_name = track_id(user_id)
    
    url = f"{COINGECKO_API}/coins/{coin}?localization=false&tickers=false&market_data=true&community_data=false&developer_data=false&sparkline=false"
    response = requests.get(url)
    data = response.json()
    
    if "error" in data or "id" not in data:
        await update.message.reply_text(f"Đéo tìm thấy coin '{coin}' nào cả! Check lại tên coin đi tml.")
        return
    
    today = datetime.now().strftime("%d/%m/%Y")
    market_data = data["market_data"]
    price = market_data["current_price"]["usd"]
    volume_24h = market_data["total_volume"]["usd"]
    market_cap = market_data["market_cap"]["usd"]
    price_change_24h = market_data["price_change_percentage_24h"]
    high_24h = market_data["high_24h"]["usd"]
    low_24h = market_data["low_24h"]["usd"]
    last_updated = market_data["last_updated"]
    
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
    await conversation_manager.add_message(group_id, user_id, user_name, f"Tìm thông tin đồng coin, cập nhật {today}", response_text)

async def macro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from api import get_fred_data
    if not await check_group_id(update, context):
        return
    
    user_id = update.message.from_user.id
    group_id = update.message.chat_id
    user_name = track_id(user_id)
    await update.message.reply_text("Đợi tao moi dữ liệu kinh tế vĩ mô từ FRED, tml đừng hối!")
    
    macro_data = []
    macro_values = {}
    
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
    
    response_text = (
        "📊 **CHỈ SỐ KINH TẾ VĨ MÔ TỪ FRED** - Dữ liệu mới nhất:\n\n" +
        "\n".join(macro_data))
    await update.message.reply_text(response_text)
    
    await update.message.reply_text("Mấy tml trong nhóm ngồi im nghe tao phân tích")
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
    from api import chat_service, execution_settings
    analysis = await chat_service.get_chat_message_content(chat_history, execution_settings)
    
    await update.message.reply_text(analysis)
    await conversation_manager.add_message(group_id, user_id, user_name, "Phân tích dữ liệu kinh tế vĩ mô", analysis)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_group_id(update, context):
        return
    if not update.message.forward_origin:
        return
    if update.message.text:
        text = update.message.text
    elif update.message.caption:
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
