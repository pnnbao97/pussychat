import os
import time
from typing import List, Tuple, Dict, Any, Optional
import numpy as np
from semantic_kernel import Kernel
from semantic_kernel.contents import ChatHistory
from semantic_kernel.connectors.ai.open_ai import OpenAIChatCompletion, OpenAIChatPromptExecutionSettings
from semantic_kernel.functions.kernel_plugin import KernelPlugin
from semantic_kernel.functions import kernel_function, KernelArguments
from semantic_kernel.connectors.ai.google.google_ai import GoogleAIChatCompletion, GoogleAITextEmbedding
from semantic_kernel.agents import ChatCompletionAgent
from openai import AsyncClient
from build_prompt import general_prompt, rag_manager_prompt, rag_summarizer_prompt
from rager import search_news
import logging
from dotenv import load_dotenv
import asyncio
from conversation import conversation_manager
from utils import track_id

logging.basicConfig(level=logging.INFO)

load_dotenv()

AI_API_KEY= os.getenv('AI_API_KEY')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
model_id = os.getenv('model_id')
base_url = os.getenv('base_url')

class AIModelFactory:
    @staticmethod
    def create_kernel():
        kernel = Kernel()
        kernel.add_service(OpenAIChatCompletion(
            ai_model_id=model_id,
            async_client=AsyncClient(api_key=AI_API_KEY,
                                     base_url=base_url)
        ))
        kernel.add_service(GoogleAIChatCompletion(
            gemini_model_id="gemini-2.0-flash",
            api_key=GEMINI_API_KEY
        ))
        kernel.add_service(GoogleAITextEmbedding(
            embedding_model_id="models/text-embedding-004",
            api_key=GEMINI_API_KEY
        ))

        return kernel

execution_settings = OpenAIChatPromptExecutionSettings(max_tokens=1000, temperature=1.5)
kernel = AIModelFactory.create_kernel()

embed_model = kernel.get_service('models/text-embedding-004')


class RAGHistoryManager():

    def __init__(self):
        self.group_rag_history = {}  # {user_id: [{query, embedding, timestamp}]}
        self.similarity_threshold = 0.8  # Ngưỡng để xác định truy vấn tương tự
        self.session_timeout = 15 * 60  # 15 phút tính bằng giây
        self.last_activity_time  = {}

    @kernel_function(name="check_similar_query")
    async def check_similar_query(self, group_id: int, query: str) -> str:
        """
        Kiểm tra xem query hiện tại có tương tự với query nào trong history không
        """
        # Nếu không có history, return "cần rag"
        if group_id not in self.group_rag_history or not self.group_rag_history[group_id]:
            return "cần rag"
        
        # Tạo embedding cho query hiện tại
        query_embedding = await self._get_embedding(query)
        
        # Kiểm tra độ tương đồng với các query trong history
        for history_item in self.group_rag_history[group_id]:
            history_embedding = history_item["embedding"]
            similarity = self._compute_similarity(query_embedding, history_embedding)
            
            if similarity >= self.similarity_threshold:
                return "không cần rag"
        
        return "cần rag"
    
    @kernel_function(name="add_to_history")
    async def add_to_history(self, group_id: int, query: str) -> None:
        """
        Thêm query vào history
        """
        current_time = time.time()
        if group_id not in self.group_rag_history:
            self.group_rag_history[group_id] = []
            self.last_activity_time[group_id] = current_time
        
        embedding = await self._get_embedding(query)
        
        time_diff = current_time - self.last_activity_time[group_id]
        if time_diff > self.session_timeout and len(self.group_rag_history[group_id]) > 0:
            self.group_rag_history[group_id] = []

        self.group_rag_history[group_id].append({
            "query": query,
            "embedding": embedding,
        })

        self.last_activity_time[group_id] = current_time
    
    @kernel_function(name="clear_history")
    def clear_history(self, group_id: int) -> None:

        if group_id in self.group_rag_history:
            self.group_rag_history[group_id] = []
    
    async def _get_embedding(self, text: str) -> List[float]:
        """
        Tạo embedding cho text sử dụng mô hình embedding
        """
        # Sử dụng embedding model từ AIModelFactory
        result = await embed_model.generate_embeddings([text])
        return result[0]
    
    def _compute_similarity(self, embedding1: List[float], embedding2: List[float]) -> float:
        """
        Tính độ tương đồng cosine giữa hai embedding
        """
        embedding1 = np.array(embedding1)
        embedding2 = np.array(embedding2)
        
        dot_product = np.dot(embedding1, embedding2)
        norm1 = np.linalg.norm(embedding1)
        norm2 = np.linalg.norm(embedding2)
        
        return dot_product / (norm1 * norm2)
    
kernel.add_plugin(RAGHistoryManager(), plugin_name="rag_history")


# async def main():
#     embed1 = await rag_history._get_embedding("tin tức về ông trump và đàn bồ câu") 
#     embed2 = await rag_history._get_embedding("tin tức về ông trump") 
#     similar = rag_history._compute_similarity(embed1,embed2)
#     print(similar)
#
# asyncio.run(main())

history = ChatHistory()

pussy = ChatCompletionAgent(
    name = "Pussy",
    instructions=general_prompt,
    service=kernel.get_service(model_id)
)


rag_manager = ChatCompletionAgent(
    name="rager",
    instructions=rag_manager_prompt,
    service=kernel.get_service("gemini-2.0-flash")
)

rag_summarizer = ChatCompletionAgent(
    name="rag_summarizer",
    instructions=rag_summarizer_prompt,
    service=kernel.get_service("gemini-2.0-flash")
)

async def pussy_bot(message: str, group_id, user_id):

    user_name = track_id(user_id)
    history = await conversation_manager.get_conversation_context(group_id, user_id)
    question_completion = history + f"Kết thúc phần lịch sử trò chuyện. Bây giờ hãy trả lời câu hỏi của {user_name}: {message}."
    rag_completion = await rag_manager.get_response(messages=message)
    rag_query = str(rag_completion).strip().lower()  
    if rag_query != "không cần rag":
        similarity_checking = await kernel.invoke(
            function=kernel.plugins["rag_history"]["check_similar_query"],
            arguments=KernelArguments(group_id=group_id, query=rag_query)            
        )

        print(f"rag_query: {rag_query}")
        print(f"similarity_checking: {similarity_checking}")

        if str(similarity_checking) == "cần rag":

            rag_return = search_news(str(rag_completion))
            await kernel.invoke(
                function=kernel.plugins["rag_history"]["add_to_history"],
                arguments=KernelArguments(group_id=group_id, query=rag_query)
            )

            quest = f"Đây là câu hỏi của người dùng: {message}. Đây là dữ liệu được RAG từ kho tin tức trong vòng 10 ngày: {rag_return}"
            rag_analyze = await rag_summarizer.get_response(messages=quest)
            question_completion = history + f"Kết thúc phần lịch sử trò chuyện. Bây giờ hãy trả lời câu hỏi của {user_name}: {message}. Có thể tham khảo thông tin được rag từ tin tức 10 ngày gần đây {rag_analyze}"
    response = await pussy.get_response(messages=question_completion)
    return str(response)

