import google.generativeai as genai
import requests
from telegram.ext import ContextTypes
from telegram import Update
import os
from dotenv import load_dotenv
load_dotenv()


GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

def track_id(user_id):
    if user_id == 6779771948:
        return "Bảo"
    elif user_id == 7652652250:
        return "Tuyên"
    elif user_id == 5066396885:
        return "Nguyên"
    else:
        return -1

def get_chunk(content, chunk_size=4096):
    return [content[i:i+chunk_size] for i in range(0, len(content), chunk_size)]

async def check_group_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.message.chat_id)
    user_id = update.message.from_user.id
    if chat_id not in ["-1002679588220", ""]:
        if user_id != 6779771948: 
            await update.message.reply_text("Đm mày ở nhóm nào mà đòi xài tao? Chỉ nhóm của thằng Bảo mới được thôi!")
            return False
    return True


genai.configure(api_key=GEMINI_API_KEY)  # Cấu hình API key
client = genai.GenerativeModel('gemini-2.0-flash-exp')  # Khởi tạo model trực tiếp
async def analyze_image(image_url=None, image_data=None, prompt="Mô tả những gì có trong ảnh (nếu ảnh có người thì nhận diện người đó luôn nếu được)"):
    try:
        if image_url:
            response = requests.get(image_url, timeout=10)
            response.raise_for_status()
            image_content = response.content
            mime_type = "image/jpeg" if image_url.endswith(".jpg") or image_url.endswith(".jpeg") else "image/png"
        elif image_data:
            image_content = image_data
            mime_type = "image/jpeg"  # Giả định mặc định, có thể cần điều chỉnh

        # Tạo nội dung cho Gemini
        response = client.generate_content(
            [prompt, {"mime_type": mime_type, "data": image_content}]
        )
        return response.text
    except Exception as e:
        return f"Lỗi khi phân tích ảnh: {str(e)}"
