"""
Lightweight Language Detection — pure Python, no LLM, no external deps.

Uses Unicode character range analysis to detect the language of user input.
Edge-triggered: only runs on the first user message per session.
"""
import re
import logging

logger = logging.getLogger(__name__)


# Unicode blocks for CJK characters
CJK_UNIFIED   = range(0x4E00, 0x9FFF + 1)   # Chinese (CJK Unified)
CJK_EXT_A     = range(0x3400, 0x4DBF + 1)   # CJK Extension A
CJK_EXT_B     = range(0x20000, 0x2A6DF + 1) # CJK Extension B
HIRAGANA      = range(0x3040, 0x309F + 1)   # Japanese Hiragana
KATAKANA      = range(0x30A0, 0x30FF + 1)   # Japanese Katakana
HANGUL        = range(0xAC00, 0xD7AF + 1)   # Korean Hangul
CYRILLIC      = range(0x0400, 0x04FF + 1)   # Russian, Ukrainian, etc.
ARABIC        = range(0x0600, 0x06FF + 1)   # Arabic
THAI          = range(0x0E00, 0x0E7F + 1)   # Thai
DEVANAGARI    = range(0x0900, 0x097F + 1)   # Hindi, Sanskrit
HEBREW        = range(0x0590, 0x05FF + 1)   # Hebrew
GREEK         = range(0x0370, 0x03FF + 1)   # Greek


def _in_ranges(char: str, *ranges) -> int:
    """Count how many ranges a character falls into (max 1)."""
    cp = ord(char)
    for r in ranges:
        if cp in r:
            return 1
    return 0


def detect_language(text: str) -> str:
    """
    Detect the primary language of a text sample.

    Returns a language code string (e.g. 'zh-CN', 'ja', 'ko', 'ru', 'ar', 'en').
    Falls back to 'en' for ambiguous or short inputs.

    Examples:
        >>> detect_language("你好，今天天气真好")
        'zh-CN'
        >>> detect_language("Hello, how are you?")
        'en'
        >>> detect_language("Привет, как дела?")
        'ru'
    """
    if not text or not isinstance(text, str) or len(text.strip()) < 2:
        return "en"

    text = text.strip()

    # Count characters per script
    n = max(len(text), 1)
    cjk = sum(1 for c in text if _in_ranges(c, CJK_UNIFIED, CJK_EXT_A, CJK_EXT_B))
    hira = sum(1 for c in text if _in_ranges(c, HIRAGANA))
    kata = sum(1 for c in text if _in_ranges(c, KATAKANA))
    hangul = sum(1 for c in text if _in_ranges(c, HANGUL))
    cyrillic = sum(1 for c in text if _in_ranges(c, CYRILLIC))
    arabic = sum(1 for c in text if _in_ranges(c, ARABIC))
    thai = sum(1 for c in text if _in_ranges(c, THAI))
    devanagari = sum(1 for c in text if _in_ranges(c, DEVANAGARI))
    hebrew = sum(1 for c in text if _in_ranges(c, HEBREW))
    greek = sum(1 for c in text if _in_ranges(c, GREEK))
    latin = sum(1 for c in text if c.isascii() and c.isalpha())

    # Japanese detection: Hiragana or Katakana present
    if hira + kata > 0:
        return "ja"

    # Korean detection
    if hangul > latin and hangul > cjk:
        return "ko"

    # Chinese detection (CJK without Hiragana/Katakana)
    if cjk > latin:
        return "zh-CN"

    # Cyrillic (Russian, Ukrainian, etc.)
    if cyrillic > latin:
        return "ru"

    # Arabic
    if arabic > latin:
        return "ar"

    # Thai
    if thai > latin:
        return "th"

    # Devanagari (Hindi, etc.)
    if devanagari > latin:
        return "hi"

    # Hebrew
    if hebrew > latin:
        return "he"

    # Greek
    if greek > latin:
        return "el"

    # For European languages, use common word heuristics
    text_lower = text.lower()
    words = re.findall(r"[a-zA-Z]+", text_lower)

    if len(words) < 2:
        return "en"

    # Romance / Germanic language heuristics via stop words
    # Spanish
    spanish_stops = {"el", "la", "los", "las", "un", "una", "y", "es", "en", "por", "para", "con", "del", "que", "no", "se", "su", "al", "lo", "como", "más", "pero", "sus", "le", "ya", "este", "entre"}
    # French
    french_stops = {"le", "la", "les", "un", "une", "des", "et", "est", "en", "dans", "pour", "sur", "avec", "que", "pas", "nous", "vous", "il", "elle", "ce", "se", "du", "au", "aux", "son", "sa"}
    # German
    german_stops = {"der", "die", "das", "ein", "eine", "und", "ist", "in", "mit", "auf", "für", "von", "sich", "nicht", "den", "dem", "zu", "aus", "bei", "hat", "auch", "werden", "es", "an", "wer", "wie"}
    # Portuguese
    portuguese_stops = {"o", "a", "os", "as", "um", "uma", "e", "é", "em", "no", "na", "para", "com", "que", "não", "se", "por", "dos", "das", "mais", "mas", "ao", "sua", "seu"}
    # Italian
    italian_stops = {"il", "la", "le", "gli", "un", "una", "e", "è", "in", "con", "per", "che", "non", "si", "del", "della", "dei", "delle", "lo", "nel", "sul", "sulla", "ho", "ha"}
    # Dutch
    dutch_stops = {"de", "het", "een", "en", "is", "in", "met", "op", "voor", "van", "zich", "niet", "je", "het", "zijn", "we", "ze", "aan", "bij", "ook", "naar", "dan", "uit"}

    word_set = set(w for w in words if len(w) > 1)
    n_words = len(word_set) or 1

    scores = {
        "es": len(word_set & spanish_stops),
        "fr": len(word_set & french_stops),
        "de": len(word_set & german_stops),
        "pt": len(word_set & portuguese_stops),
        "it": len(word_set & italian_stops),
        "nl": len(word_set & dutch_stops),
    }

    best_lang = max(scores, key=scores.get)
    best_score = scores[best_lang]

    # Require at least 20% of unique words to match a language's stop words
    if best_score > 0 and (best_score / n_words) >= 0.15:
        return best_lang

    return "en"


def language_to_instruction(lang: str) -> str:
    """Convert language code to a system prompt instruction."""
    LANGUAGE_NAMES = {
        "zh-CN": "Chinese (Simplified)",
        "zh-TW": "Chinese (Traditional)",
        "ja": "Japanese",
        "ko": "Korean",
        "ru": "Russian",
        "ar": "Arabic",
        "th": "Thai",
        "hi": "Hindi",
        "he": "Hebrew",
        "el": "Greek",
        "es": "Spanish",
        "fr": "French",
        "de": "German",
        "pt": "Portuguese",
        "it": "Italian",
        "nl": "Dutch",
        "en": "English",
    }
    name = LANGUAGE_NAMES.get(lang, "English")
    if lang == "en":
        return ""
    return f"\n\n**Language**: Respond in {name}."
