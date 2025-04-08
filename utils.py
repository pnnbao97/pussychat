import io
import requests
from PIL import Image, ImageDraw, ImageFont
from semantic_kernel.contents import ChatHistory
from api import chat_service, execution_settings
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
        img = img.resize((500, 300))  # Kích thước ảnh

        # Tạo đối tượng vẽ
        d = ImageDraw.Draw(img)

        # Thử tải font hỗ trợ tiếng Việt
        try:
            # Dùng font DejaVuSans hỗ trợ tiếng Việt, tải từ hệ thống hoặc fallback
            font = ImageFont.truetype("DejaVuSans.ttf", 50)  # Tăng kích thước font
        except:
            try:
                font = ImageFont.truetype("LiberationSans-Regular.ttf", 50)  # Font khác hỗ trợ tiếng Việt
            except:
                font = ImageFont.load_default()  # Fallback cuối cùng, nhưng size nhỏ hơn
                font = ImageFont.truetype(font.path, 50) if hasattr(font, 'path') else font

        # Tính toán kích thước text để căn giữa
        text_bbox = d.textbbox((0, 0), text, font=font)
        text_width = text_bbox[2] - text_bbox[0]
        text_height = text_bbox[3] - text_bbox[1]
        img_width, img_height = img.size
        x = (img_width - text_width) // 2  # Căn giữa ngang
        y = (img_height - text_height) // 2  # Căn giữa dọc

        # Thêm nền đen trong suốt để text nổi bật
        d.rectangle(
            [(x - 10, y - 10), (x + text_width + 10, y + text_height + 10)],
            fill=(0, 0, 0, 180)  # Màu đen, độ trong suốt 180/255
        )

        # Vẽ text với màu vàng (hoặc đỏ) để nổi bật
        d.text(
            (x, y),
            text,
            font=font,
            fill=(255, 215, 0),  # Màu vàng gold
            stroke_width=2,
            stroke_fill=(0, 0, 0)  # Viền đen để tăng độ tương phản
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
