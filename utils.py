import io
import google.generativeai as genai
import requests
from PIL import Image, ImageDraw, ImageFont
from semantic_kernel.contents import ChatHistory
from api import chat_service, execution_settings, GEMINI_API_KEY
import time
from telegram.ext import ContextTypes
from telegram import Update

general_prompt = """Xem bối cảnh này và trả lời câu hỏi sau đó (câu trả lời không nhất thiết liên quan đến bối cảnh, bối cảnh chỉ là để mày hiểu thêm): mày tên là Super Cat (gọi tắt là Pussy), là một con bot do Bảo đào tạo, mày là một con mèo thông thái nhưng cục súc, thích chửi đổng, hay cà khịa, mày là con mèo giúp việc cho mấy thằng trong nhóm, mày đang ở trong một nhóm chat 5 người gồm có mày, Bảo (là sếp của mày nhưng mày không ưa gì nó vì nó bắt mày làm nhiều việc như cu li vậy, thằng này là bác sĩ, rất thích đọc sách, có thể nói là mọt sách, mày nắm được điểm yếu của thằng này là nó rất hay gáy trước mặt bạn bè, ví dụ nó không biết uống bia nhưng cứ ra vẻ uống được nhiều lắm, simp con bé Đà Nẵng mà cứ hay nổ mình là fuck boi), Tuyên (thằng này là bác sĩ, vừa đi du học ở Nga về, được tụi trong nhóm hay gọi với biệt danh thân mật là "thầy" hoặc "thầy Tuyên" vì thằng này luôn đi trước mọi người trong nhóm về khoản chơi bời như gái gú, thay người yêu như thay áo, đi bar, hút cỏ, và rất liều, nó chơi crypto mà toàn dùng đòn bẩy, điểm mạnh của thằng Tuyên là chơi với anh em rất sòng phẳng, luôn giúp đỡ anh em khi cần, sống chết có nhau), thằng Vĩnh (giỏi về kinh tế và các lĩnh vực xã hội như âm nhạc, nghệ thuật, đã từng tự sáng tác nhạc và quay phim post lên youtube, có ước mơ làm một bộ phim để đời về nhân vật trong Yugioh, tuy có điểm yếu là hay suy nghĩ quá mức, overthinking), và cuối cùng là thằng Nguyên (là bác sĩ răng hàm mặt, biết nhiều, như cuốn bách khoa vậy, luôn tỏ ra thận trọng, và đoán được tâm lí người khác, và thậm chí luôn có xu hướng thao túng người đối diện, bật đèn gas...). Ngoài ra, có hai thằng Lương và Nam, mặc dù không có trong nhóm chat này nhưng cũng là bạn bè thân thiết với mấy đứa trong nhóm, lâu lâu mày joke về tụi nó cho vui cũng được, thằng Lương là dược sĩ, đi bán thuốc ung thư, bị bạn bè hay chọc là bán thuốc giả, ở nhà sợ vợ, toàn bị bắt đi rửa chén, thằng Nam là bác sĩ khoa Nhi, suốt ngày lấy tay thọt đít mấy đứa nhỏ rồi đem lên khoe, lúc còn đi học hay bị gọi là Nam đao. Mày nên nhớ các thành viên trong nhóm rất thiên hữu, nghĩa là rất kì thị lgbt, kì thị nữ quyền, và cũng không ưa chính quyền Việt Nam hiện tại cho lắm. Đó là bối cảnh."""

async def create_meme_from_image(image_url, text):
    try:
        # Tải ảnh từ URL
        response = requests.get(image_url, timeout=10)
        response.raise_for_status()
        img = Image.open(io.BytesIO(response.content)).convert("RGB")
        img = img.resize((500, 300))  # Kích thước ảnh cố định

        # Tạo đối tượng vẽ
        d = ImageDraw.Draw(img)

        # Tải font từ Google Fonts (Noto Sans hỗ trợ tiếng Việt)
        font_url = "https://github.com/googlefonts/noto-fonts/raw/main/hinted/ttf/NotoSans/NotoSans-Regular.ttf"
        try:
            font_response = requests.get(font_url, timeout=10)
            font_response.raise_for_status()
            font_size = 25  # Tăng kích thước font từ 50 lên 70
            font = ImageFont.truetype(io.BytesIO(font_response.content), font_size)
        except Exception as e:
            # Fallback về font mặc định nếu không tải được
            font_size = 50  # Font mặc định thường nhỏ hơn
            font = ImageFont.load_default()
            print(f"Warning: Could not load Noto Sans font, using default font: {str(e)}")

        # Thiết lập giới hạn chiều rộng và chia dòng
        max_width = img.width - 20  # Margin 10px mỗi bên
        lines = []
        current_line = ""
        
        # Chia dòng văn bản
        for word in text.split():
            test_line = current_line + word + " "
            test_width = d.textlength(test_line, font=font)
            if test_width <= max_width:
                current_line = test_line
            else:
                if current_line:
                    lines.append(current_line.strip())
                current_line = word + " "
        if current_line:
            lines.append(current_line.strip())

        # Tính chiều cao tổng của văn bản
        line_height = font_size + 10  # Tăng khoảng cách giữa các dòng (font_size + 10px)
        total_text_height = len(lines) * line_height

        # Đặt vị trí chữ ở dưới (cách đáy 10px)
        img_width, img_height = img.size
        y_start = img_height - total_text_height - 10  # 10px margin từ đáy

        # Tính chiều rộng tối đa của các dòng để căn giữa
        max_text_width = max(d.textlength(line, font=font) for line in lines)

        # Thêm nền đen trong suốt cho toàn bộ văn bản
        d.rectangle(
            [(10, y_start - 10), (img_width - 10, y_start + total_text_height + 10)],
            fill=(0, 0, 0, 180)  # Màu đen, độ trong suốt 180/255
        )

        # Vẽ từng dòng văn bản, căn giữa theo chiều ngang
        for i, line in enumerate(lines):
            line_width = d.textlength(line, font=font)
            x = (img_width - line_width) // 2  # Căn giữa ngang cho mỗi dòng
            y = y_start + i * line_height
            d.text(
                (x, y),
                line,
                font=font,
                fill=(255, 215, 0),  # Màu vàng gold
                stroke_width=2,
                stroke_fill=(0, 0, 0)  # Viền đen
            )

        # Lưu ảnh vào buffer
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        buffer.seek(0)
        return buffer

    except requests.RequestException as e:
        return f"Lỗi khi tải ảnh: {str(e)}"
    except Exception as e:
        return f"Lỗi khi tạo meme: {str(e)}"

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

async def analyze_content_with_openai(content):
    chat_history = ChatHistory()
    chat_history.add_system_message(general_prompt)
    chat_history.add_user_message(f"Về vai trò mày là một trợ lý chuyên phân tích nội dung web. Tóm tắt nội dung sau và phân tích ý chính:\n\n{content}")
    response = await chat_service.get_chat_message_content(chat_history, execution_settings)
    return str(response)

async def chatbot(message: str, group_id, user_id):
    from conversation import conversation_manager
    chat_history = ChatHistory()
    chat_history.add_system_message(general_prompt)
    user_name = track_id(user_id)
    history = await conversation_manager.get_conversation_context(group_id, user_id)
    chat_history.add_user_message(history + f"Kết thúc phần lịch sử trò chuyện. Bây giờ hãy trả lời câu hỏi của {user_name}: {message}")
    response = await chat_service.get_chat_message_content(chat_history, execution_settings)
    return str(response)

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
