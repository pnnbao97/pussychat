from semantic_kernel.contents import ChatHistory
from utils import track_id
from api import chat_service, execution_settings
import time

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
            self.group_histories[group_id] = ChatHistory()
        
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
                conversation_history += f"Đây là câu trả lời của Pussy: {msg.content}\n"
            else:
                conversation_history += f"Đây là câu hỏi của mấy thằng trong nhóm: {msg.content}\n"
        return f"Đây là lịch sử cuộc trò chuyện nhóm (được xếp theo thứ tự từ cũ nhất đến mới nhất):\n{conversation_history}\n"

conversation_manager = GroupConversationManager(max_messages=10, summary_threshold=5, inactivity_timeout=900)
