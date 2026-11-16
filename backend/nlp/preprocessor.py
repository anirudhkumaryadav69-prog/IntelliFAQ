"""
Text Preprocessing Module for IntelliFAQ.

Provides reusable, lightweight NLP preprocessing tailored for FAQ retrieval:
- Safe input validation (handles None, non-strings, and empty/whitespace input)
- Contraction expansion and lowercasing
- Removal of unnecessary punctuation and special characters
- NLTK word tokenization (with regex fallback if NLTK corpora are offline)
- Selective English stopword removal that preserves domain/intent words
- WordNet lemmatization (nouns and verbs)
"""

import re
from typing import List, Set

import nltk
from nltk.corpus import stopwords
from nltk.stem import WordNetLemmatizer
from nltk.tokenize import word_tokenize

# Common contractions mapped to expanded forms prior to punctuation stripping
CONTRACTIONS_MAP = {
    "what's": "what is",
    "where's": "where is",
    "when's": "when is",
    "who's": "who is",
    "how's": "how is",
    "can't": "cannot",
    "won't": "will not",
    "don't": "do not",
    "doesn't": "does not",
    "didn't": "did not",
    "isn't": "is not",
    "aren't": "are not",
    "wasn't": "was not",
    "weren't": "were not",
    "haven't": "have not",
    "hasn't": "has not",
    "hadn't": "had not",
    "wouldn't": "would not",
    "shouldn't": "should not",
    "couldn't": "could not",
    "i'm": "i am",
    "i've": "i have",
    "i'll": "i will",
    "i'd": "i would",
    "it's": "it is",
    "that's": "that is",
    "there's": "there is",
    "let's": "let us",
}

# Fallback stopwords if NLTK stopwords corpus is not yet downloaded offline
FALLBACK_STOPWORDS = {
    "a", "about", "above", "an", "and", "any", "are", "as", "at", "be",
    "because", "been", "Being", "by", "can", "could", "did", "do", "does",
    "doing", "down", "for", "from", "had", "has", "have", "having", "he",
    "her", "here", "hers", "herself", "him", "himself", "his", "how", "i",
    "if", "in", "into", "is", "it", "its", "itself", "just", "me", "might",
    "my", "myself", "now", "of", "on", "once", "only", "or", "our", "ours",
    "ourselves", "out", "over", "ll", "re", "s", "shall", "she", "should",
    "so", "some", "such", "t", "than", "that", "the", "their", "theirs",
    "them", "themselves", "then", "there", "these", "they", "this", "those",
    "through", "to", "too", "up", "ve", "very", "was", "we", "were", "what",
    "when", "where", "which", "while", "who", "whom", "why", "will", "with",
    "would", "you", "your", "yours", "yourself", "yourselves", "please",
    "tell", "know", "want", "need", "get", "like",
}

# Words present in standard stopword lists that carry important FAQ intent
INTENT_WORDS_TO_KEEP = {
    "no",
    "not",
    "without",
    "before",
    "after",
    "under",
    "between",
    "during",
    "more",
    "most",
    "other",
    "same",
    "both",
    "against",
    "off",
    "on",
}

# Conversational filler words that add noise to FAQ similarity matching
CONVERSATIONAL_STOPWORDS = {
    "please",
    "kindly",
    "hello",
    "hi",
    "hey",
    "tell",
    "explain",
    "give",
    "show",
    "find",
    "know",
    "want",
    "much",
    "many",
    "can",
    "could",
    "would",
    "should",
    "may",
    "might",
    "shall",
}


def ensure_nltk_resources() -> None:
    """
    Verify required NLTK resources are available locally; download if missing.
    Fails gracefully if the environment has no network access.
    """
    resources = [
        ("tokenizers/punkt", "punkt"),
        ("tokenizers/punkt_tab", "punkt_tab"),
        ("corpora/stopwords", "stopwords"),
        ("corpora/wordnet", "wordnet"),
        ("corpora/omw-1.4", "omw-1.4"),
    ]
    for resource_path, package_name in resources:
        try:
            nltk.data.find(resource_path)
        except LookupError:
            try:
                nltk.data.find(f"{resource_path}.zip")
            except LookupError:
                try:
                    nltk.download(package_name, quiet=True)
                except Exception:
                    # Offline or restricted environment: fallbacks will be used
                    pass


class TextPreprocessor:
    """
    Reusable text preprocessor for FAQ indexing and user query normalization.
    """

    def __init__(self, auto_download_nltk: bool = True) -> None:
        if auto_download_nltk:
            ensure_nltk_resources()

        self.lemmatizer = WordNetLemmatizer()
        self.stop_words: Set[str] = self._load_stopwords()
        self._contraction_pattern = re.compile(
            r"\b(" + "|".join(re.escape(k) for k in CONTRACTIONS_MAP.keys()) + r")\b"
        )
        # Keep lowercase letters, digits, and whitespace
        self._non_alphanumeric_pattern = re.compile(r"[^a-z0-9\s]+")
        self._whitespace_pattern = re.compile(r"\s+")

    def _load_stopwords(self) -> Set[str]:
        """
        Load English stopwords from NLTK, retaining FAQ intent words
        and adding common conversational filler words.
        """
        try:
            base_stopwords = set(stopwords.words("english"))
        except LookupError:
            base_stopwords = set(FALLBACK_STOPWORDS)

        custom_stopwords = (base_stopwords | CONVERSATIONAL_STOPWORDS) - INTENT_WORDS_TO_KEEP
        return custom_stopwords

    def _expand_contractions(self, text: str) -> str:
        """Replace common English contractions with their expanded form."""
        return self._contraction_pattern.sub(
            lambda match: CONTRACTIONS_MAP[match.group(0)], text
        )

    def _tokenize(self, text: str) -> List[str]:
        """Tokenize cleaned text using NLTK word_tokenize with regex fallback."""
        try:
            return word_tokenize(text)
        except LookupError:
            return re.findall(r"\b[a-z0-9]+\b", text)

    def _lemmatize_token(self, token: str) -> str:
        """
        Lemmatize a token as a noun first, then as a verb if unchanged.
        Falls back to the original token if WordNet corpus is unavailable.
        """
        if len(token) <= 2 or token.isdigit():
            return token
        try:
            noun_lemma = self.lemmatizer.lemmatize(token, pos="n")
            if noun_lemma != token:
                return noun_lemma
            return self.lemmatizer.lemmatize(token, pos="v")
        except LookupError:
            return token

    def tokenize_and_clean(self, text: object) -> List[str]:
        """
        Validate, normalize, tokenize, filter stopwords, and lemmatize input text.

        Args:
            text: Raw input string (non-string or empty inputs return []).

        Returns:
            List of clean, lemmatized tokens.
        """
        if not isinstance(text, str):
            return []

        stripped = text.strip()
        if not stripped:
            return []

        # 1. Lowercase and expand contractions
        lowered = stripped.lower()
        expanded = self._expand_contractions(lowered)

        # 2. Replace hyphens and slashes with spaces to preserve compound parts
        normalized = expanded.replace("-", " ").replace("/", " ")

        # 3. Remove unnecessary punctuation and special characters
        cleaned = self._non_alphanumeric_pattern.sub(" ", normalized)
        cleaned = self._whitespace_pattern.sub(" ", cleaned).strip()

        if not cleaned:
            return []

        # 4. Tokenize
        raw_tokens = self._tokenize(cleaned)

        # 5. Remove stopwords and single-character noise (except digits)
        filtered_tokens = [
            token
            for token in raw_tokens
            if token not in self.stop_words and (len(token) > 1 or token.isdigit())
        ]

        # 6. Lemmatize tokens
        lemmatized_tokens = [
            self._lemmatize_token(token) for token in filtered_tokens
        ]

        return lemmatized_tokens

    def preprocess(self, text: object) -> str:
        """
        Return a clean, space-joined string of preprocessed tokens suitable
        for Scikit-learn TfidfVectorizer.

        Args:
            text: Raw input string.

        Returns:
            Clean preprocessed text string (or "" if input is invalid/empty).
        """
        tokens = self.tokenize_and_clean(text)
        return " ".join(tokens)


# Module-level singleton instance for convenient reuse
_default_preprocessor = None


def preprocess_text(text: object) -> str:
    """
    Convenience function to preprocess text using a shared TextPreprocessor.
    """
    global _default_preprocessor
    if _default_preprocessor is None:
        _default_preprocessor = TextPreprocessor()
    return _default_preprocessor.preprocess(text)
