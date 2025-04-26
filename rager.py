import logging
from typing import List, Tuple, Dict, Any
from llama_index.core import Settings, VectorStoreIndex
from llama_index.core.query_engine import RetrieverQueryEngine
from llama_index.embeddings.google_genai import GoogleGenAIEmbedding
from llama_index.vector_stores.postgres import PGVectorStore
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.retrievers import VectorIndexRetriever
from llama_index.core.postprocessor import SimilarityPostprocessor
from utils import GEMINI_API_KEY
import os
from dotenv import load_dotenv
from sqlalchemy import make_url
load_dotenv()

# Setup logging
logging.basicConfig(level=logging.WARNING, format='%(asctime)s - %(levelname)s - %(message)s')

PG_CONN_STRING = os.getenv("PG_CONN_STRING", "postgresql://postgres:18121997@localhost:5432/llama_rag")

def setup_llama_index():
    """Set up LlamaIndex with Google GenAI embedding model."""
    try:
        embed_model = GoogleGenAIEmbedding(
            model_name="models/text-embedding-004",
            api_key=GEMINI_API_KEY,
            embed_batch_size=50,
        )
        Settings.embed_model = embed_model
        Settings.node_parser = SentenceSplitter(chunk_size=500, chunk_overlap=50)
        Settings.llm = None
        return embed_model
    except Exception as e:
        logging.error(f"Error setting up LlamaIndex: {e}")
        raise

embed_model = setup_llama_index()


url = make_url(PG_CONN_STRING)
def get_pg_vector_store(): 
    vector_store = PGVectorStore.from_params(
        database="llama_rag_sy4v",
        host=url.host,
        password=url.password,
        port="5432",
        user=url.username,
        schema_name="news",
        table_name="news_vectors",
        embed_dim=768,  # openai embedding dimension
        hnsw_kwargs={
            "hnsw_m": 16,
            "hnsw_ef_construction": 64,
            "hnsw_ef_search": 40,
            "hnsw_dist_method": "vector_cosine_ops",
        },
    )
    return vector_store

def get_retriever(similarity_top_k=5, similarity_threshold=0.5):
    """Create a retriever for vector store."""
    vector_store = get_pg_vector_store()
    index = VectorStoreIndex.from_vector_store(vector_store)
    retriever = VectorIndexRetriever(
        index=index,
        similarity_top_k=similarity_top_k,
    )
    return retriever

def get_query_engine(similarity_top_k=5, similarity_threshold=0.5):
    """Create a query engine for retrieving and ranking documents."""
    retriever = get_retriever(similarity_top_k, similarity_threshold)
    query_engine = RetrieverQueryEngine.from_args(
        retriever=retriever,
        llm = None,
        node_postprocessors=[
            SimilarityPostprocessor(similarity_cutoff=similarity_threshold)
        ]
    )
    return query_engine

def search_news(query: str, k: int = 10, threshold: float = 0.4) -> List[Dict[str, Any]]:
    query_engine = get_query_engine(similarity_top_k=k, similarity_threshold=threshold)
    try:
        response = query_engine.query(query)
        results = []
        for node in response.source_nodes:
            result = {
                "id": node.node_id,
                "url": node.metadata.get("url", "Unknown"),
                "content": node.text,
                "distance": 1.0 - node.score if hasattr(node, "score") and node.score is not None else 0.0,
                "timestamp": node.metadata.get("timestamp", None),
                "source": node.metadata.get("source", "news"),
            }
        
            results.append(result)
        results.sort(key=lambda x: x["timestamp"], reverse=True)  # Sắp xếp giảm dần
        return results[:k]
    except Exception as e:
        logging.error(f"LlamaIndex search error: {str(e)}")
        return []
