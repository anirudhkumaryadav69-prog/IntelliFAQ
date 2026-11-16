"""
IntelliFAQ NLP Package.

Exposes the text preprocessing pipeline and the TF-IDF + Cosine Similarity
FAQ matching engine.
"""

from .chatbot import FAQChatbot, get_chatbot
from .preprocessor import TextPreprocessor, preprocess_text

__all__ = [
    "TextPreprocessor",
    "preprocess_text",
    "FAQChatbot",
    "get_chatbot",
]
