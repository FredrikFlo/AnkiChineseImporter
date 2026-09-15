import os
import re
import json
import base64
import time
import requests
from dotenv import load_dotenv
from deep_translator import GoogleTranslator, MyMemoryTranslator
from gtts import gTTS
from pypinyin import pinyin, Style
from notion_client import Client

# ==========================================
# CONFIGURATION
# ==========================================

load_dotenv()

NOTION_TOKEN = os.environ["NOTION_TOKEN"]
INBOX_PAGE_ID = os.environ["INBOX_PAGE_ID"]

# Paste your separate backup/archive Notion Page IDs here
ARCHIVE_VOCAB_PAGE_ID = os.environ["ARCHIVE_VOCAB_PAGE_ID"]
ARCHIVE_SENTENCES_PAGE_ID = os.environ["ARCHIVE_SENTENCES_PAGE_ID"]

# ==========================================
# ==========================================

ANKI_URL = "http://localhost:8765"

# Deck Names
RECOGNITION_DECK = "Chinese Sentences (Recognition)"                      # recognition
PRODUCTION_DECK = "Chinese Sentences (Production)"         # production
VOCAB_DECK = "Chinese Vocab"                                # characters/words

# Note Types
RECOGNITION_MODEL = "Basic (Back -> Front)"   # your existing renamed model, untouched
FORWARD_MODEL = "Basic (Front -> Back)"       # cloned model, Front->Back

# Cache Files for Fast Local Lookups
DECOMP_CACHE_FILE = "hanzi_decomp_cache.json"
HSK_CACHE_FILE = "hsk_vocab_cache.json"

# Tone Colors (1: Red, 2: Green, 3: Blue, 4: Purple, 5: Gray)
TONE_COLORS = {
    1: "#FF4D4F",
    2: "#52C41A",
    3: "#1890FF",
    4: "#722ED1",
    5: "#8C8C8C"
}

PUNCTUATION_PATTERN = r'[ \t\r\n\.\,\!\?\,\;\:\“\”\‘\’\（\）\《\》\【\】\—\…\。\，\！\？\；\：]'

# Expanded Notion Block Support
SUPPORTED_BLOCK_TYPES = [
    "paragraph", "to_do", "bulleted_list_item", "numbered_list_item",
    "toggle", "quote", "callout", "heading_1", "heading_2", "heading_3"
]

notion = Client(auth=NOTION_TOKEN)

# ==========================================
# HELPER FUNCTIONS
# ==========================================

def strip_html_tags(text):
    """Safely removes HTML tags from string to get clean raw text."""
    return re.sub(r'<[^>]+>', '', text).strip()

TRANSLATION_CACHE_FILE = "translation_cache.json"

def translate_text(text, retries=3):
    cache = {}
    if os.path.exists(TRANSLATION_CACHE_FILE):
        with open(TRANSLATION_CACHE_FILE, "r", encoding="utf-8") as f:
            cache = json.load(f)

    if text in cache:
        return cache[text]

    for attempt in range(retries):
        try:
            result = GoogleTranslator(source='zh-CN', target='en').translate(text)
            if result:
                cache[text] = result
                with open(TRANSLATION_CACHE_FILE, "w", encoding="utf-8") as f:
                    json.dump(cache, f, ensure_ascii=False)
                return result
        except Exception as e:
            print(f"  ⚠️ Translation attempt {attempt+1} failed: {e}")
            if attempt < retries - 1:
                wait = 2 ** (attempt + 1)  # 2s, 4s, 8s...
                print(f"  ⏳ Backing off for {wait}s before retrying...")
                time.sleep(wait)

    # Google exhausted its retries — fall back to a different backend/rate-limit pool
    print(f"  🔁 Falling back to MyMemory for: {text}")
    try:
        result = MyMemoryTranslator(source='zh-CN', target='en-US').translate(text)
        if result:
            cache[text] = result
            with open(TRANSLATION_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False)
            return result
    except Exception as e:
        print(f"  ⚠️ MyMemory fallback also failed: {e}")

    print(f"  ⚠️ Translation failed after {retries} attempts for: {text}")
    return None

def strip_punctuation(text):
    """Removes all punctuation from text for clean duplicate checks."""
    return re.sub(PUNCTUATION_PATTERN, '', text)

def is_only_punctuation(text):
    """Checks if a string contains only punctuation marks."""
    return len(strip_punctuation(text)) == 0

def get_colored_pinyin(text):
    """Generates HTML string with Pinyin color-coded by tone."""
    py_marked = pinyin(text, style=Style.TONE)
    py_numbered = pinyin(text, style=Style.TONE3)
    
    colored_spans = []
    for marked_item, numbered_item in zip(py_marked, py_numbered):
        m_str = marked_item[0].strip()
        n_str = numbered_item[0].strip()
        
        if re.match(r'^\W+$', m_str):
            continue

        tone_match = re.search(r'[1-5]', n_str)
        tone = int(tone_match.group(0)) if tone_match else 5
        color = TONE_COLORS.get(tone, TONE_COLORS[5])
        
        colored_spans.append(f"<span style='color: {color}; font-weight: 600;'>{m_str}</span>")
        
    return " ".join(colored_spans)

def generate_and_store_audio(chinese_text, retries=2):
    """Generates Google TTS audio file and stores it directly into Anki media."""
    clean_text = strip_punctuation(chinese_text)
    if not clean_text:
        return ""

    filename = f"zh_audio_{abs(hash(clean_text))}.mp3"
    temp_path = f"temp_{filename}"

    for attempt in range(retries):
        try:
            tts = gTTS(text=clean_text, lang='zh-CN')
            tts.save(temp_path)

            with open(temp_path, "rb") as file:
                b64_data = base64.b64encode(file.read()).decode("utf-8")

            media_payload = {
                "action": "storeMediaFile",
                "version": 6,
                "params": {"filename": filename, "data": b64_data}
            }
            requests.post(ANKI_URL, json=media_payload)

            if os.path.exists(temp_path):
                os.remove(temp_path)

            return f"[sound:{filename}]"
        except Exception:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            if attempt < retries - 1:
                time.sleep(1)

    print(f"  ⚠️ Audio generation warning for: {chinese_text}")
    return ""

def get_character_decomposition(term):
    """Returns a per-character breakdown, distinguishing sound-only vs meaning-bearing components where the data allows it."""
    if not os.path.exists(DECOMP_CACHE_FILE):
        try:
            url = "https://raw.githubusercontent.com/skishore/makemeahanzi/master/dictionary.txt"
            res = requests.get(url, timeout=30)
            if res.status_code == 200:
                decomp_map = {}
                for line in res.text.strip().split("\n"):
                    if not line: continue
                    entry = json.loads(line)
                    c = entry.get("character")
                    if c:
                        decomp_map[c] = {
                            "decomp": entry.get("decomposition"),
                            "radical": entry.get("radical"),
                            "definition": entry.get("definition"),
                            "etymology": entry.get("etymology"),
                            "pinyin": entry.get("pinyin")
                        }
                with open(DECOMP_CACHE_FILE, "w", encoding="utf-8") as f:
                    json.dump(decomp_map, f, ensure_ascii=False)
        except Exception:
            return None, None

    try:
        with open(DECOMP_CACHE_FILE, "r", encoding="utf-8") as f:
            decomp_map = json.load(f)
    except Exception:
        return None, None

    def short_meaning(char):
        entry = decomp_map.get(char)
        if entry and entry.get("definition"):
            return entry["definition"].split(",")[0].split(";")[0].strip()
        return None

    def first_pinyin(char):
        entry = decomp_map.get(char)
        if entry and entry.get("pinyin"):
            return entry["pinyin"][0]
        return None

    hanzi_chars = [c for c in term if '\u4e00' <= c <= '\u9fff']
    if not hanzi_chars:
        return None, None

    lines = []
    primary_radical = None
    for char in hanzi_chars:
        entry = decomp_map.get(char)
        if not entry:
            continue

        if primary_radical is None and entry.get("radical"):
            primary_radical = entry["radical"]

        etymology = entry.get("etymology") or {}
        etype = etymology.get("type")

        # Pictophonetic: one side carries meaning, the other is sound-only (show its pinyin instead).
        if etype == "pictophonetic" and etymology.get("semantic") and etymology.get("phonetic"):
            semantic = etymology["semantic"]
            phonetic = etymology["phonetic"]
            hint = etymology.get("hint") or short_meaning(semantic)
            semantic_part = f"{semantic} ({hint})" if hint else semantic
            phonetic_pinyin = first_pinyin(phonetic)
            phonetic_part = f"{phonetic} sound only ({phonetic_pinyin})" if phonetic_pinyin else f"{phonetic} sound only"
            lines.append(f"{char}: {semantic_part} — {phonetic_part}")
            continue

        # Ideographic / everything else: components genuinely combine to give meaning.
        decomposition = entry.get("decomp")
        components = [c for c in decomposition if '\u4e00' <= c <= '\u9fff'] if decomposition and decomposition != "？" else []

        if components:
            parts = []
            for comp in components:
                meaning = short_meaning(comp)
                parts.append(f"{comp} ({meaning})" if meaning else comp)
            lines.append(f"{char}: " + ", ".join(parts))
        else:
            radical = entry.get("radical")
            if radical and radical != char:
                meaning = short_meaning(radical)
                lines.append(f"{char}: {radical} ({meaning})" if meaning else f"{char}: {radical}")
            else:
                meaning = short_meaning(char)
                lines.append(f"{char}: {char} ({meaning})" if meaning else char)

    if not lines:
        return None, None

    return "<br>".join(lines), primary_radical

def get_hsk_level(word):
    """Checks HSK level for tagging."""
    if not os.path.exists(HSK_CACHE_FILE):
        try:
            url = "https://raw.githubusercontent.com/elias213/hsk-json/master/hsk.json"
            res = requests.get(url, timeout=5)
            if res.status_code == 200:
                with open(HSK_CACHE_FILE, "w", encoding="utf-8") as f:
                    f.write(res.text)
        except Exception:
            return None

    try:
        with open(HSK_CACHE_FILE, "r", encoding="utf-8") as f:
            hsk_data = json.load(f)
            for item in hsk_data:
                if item.get("hanzi") == word or item.get("simplified") == word:
                    level = item.get("level") or item.get("hsk")
                    return f"HSK{level}" if level else None
    except Exception:
        pass
    return None

def send_to_anki(deck, front_text, back_text, tags=None, model=RECOGNITION_MODEL):
    payload = {
        "action": "addNote",
        "version": 6,
        "params": {
            "note": {
                "deckName": deck,
                "modelName": model,
                "fields": {"Front": front_text, "Back": back_text},
                "tags": tags or ["auto_generated"]
            }
        }
    }
    try:
        res = requests.post(ANKI_URL, json=payload).json()
        if not res.get("error"):
            clean_display = strip_html_tags(front_text)
            print(f"  ✅ Added to [{deck}]: {clean_display}")
            return True
        else:
            print(f"  ❌ Anki Error [{deck}]: {res.get('error')}")
            return False
    except Exception as e:
        print(f"  ⚠️ Make sure Anki Desktop is open! Error: {e}")
        return False

def get_deck_terms(deck_name):
    """Extracts Chinese terms (from Front, or bolded Back) for notes in ONE specific deck."""
    query = f'deck:"{deck_name}"'
    payload = {"action": "findNotes", "version": 6, "params": {"query": query}}
    try:
        res = requests.post(ANKI_URL, json=payload).json()
        note_ids = res.get("result", [])
        if not note_ids:
            return set()

        info_res = requests.post(ANKI_URL, json={"action": "notesInfo", "version": 6, "params": {"notes": note_ids}}).json()
        terms = set()
        for note in info_res.get("result", []):
            f_html = note.get("fields", {}).get("Front", {}).get("value", "")
            b_html = note.get("fields", {}).get("Back", {}).get("value", "")

            f_clean = strip_punctuation(strip_html_tags(f_html)).lower()
            if f_clean:
                terms.add(f_clean)

            b_bold_match = re.search(r'<b>(.*?)</b>', b_html)
            if b_bold_match:
                b_term = strip_punctuation(strip_html_tags(b_bold_match.group(1))).lower()
                if b_term:
                    terms.add(b_term)
        return terms
    except Exception:
        return set()

# ==========================================
# CARD CREATION LOGIC
# ==========================================

def create_vocab_card(term):
    clean_term = strip_punctuation(term)
    if not clean_term: return False

    colored_py = get_colored_pinyin(clean_term)
    eng_meaning = translate_text(clean_term) or "[Translation Unavailable]"
    time.sleep(1.5)  # delay to avoid hitting translation API too quickly
    audio_tag = generate_and_store_audio(clean_term)
    decomp_info, primary_radical = get_character_decomposition(clean_term)
    hsk_tag = get_hsk_level(clean_term)

    front = f"<div style='font-size: 40px; text-align: center; margin-bottom: 10px;'>{clean_term}</div>"
    
    back_parts = [
        f"<div style='font-size: 22px; margin-bottom: 8px;'>{colored_py}</div>",
        f"<b>Meaning:</b> {eng_meaning}"
    ]
    if decomp_info:
        back_parts.append(f"<div style='margin-top: 6px; font-size: 0.9em; color: #444;'>{decomp_info}</div>")
    if audio_tag:
        back_parts.append(f"<br>{audio_tag}")

    back = "<br>".join(back_parts)
    
    tags = ["character" if len(clean_term) == 1 else "word"]
    if hsk_tag:
        tags.append(hsk_tag)
    if primary_radical:
        tags.append(f"radical_{primary_radical}")

    return send_to_anki(VOCAB_DECK, front, back, tags=tags, model=FORWARD_MODEL)

def prepare_sentence_assets(sentence):
    """Computes shared pinyin/translation/audio once for both sentence decks."""
    colored_py = get_colored_pinyin(sentence)
    eng_meaning = translate_text(sentence)
    time.sleep(1.5)  # delay to avoid hitting translation API too quickly
    audio_tag = generate_and_store_audio(sentence)
    return colored_py, eng_meaning, audio_tag

def create_sentence_card(sentence, colored_py, eng_meaning, audio_tag, recognition_terms, runtime_fronts):
    # Handle missing translation or identical translation collisions
    if not eng_meaning:
        front_text = f"Translate: {sentence}"
    else:
        norm_eng = strip_punctuation(eng_meaning).lower()
        if norm_eng in recognition_terms or norm_eng in runtime_fronts:
            # Differentiate by appending Chinese sentence to ensure Front field uniqueness
            front_text = f"{eng_meaning} <span style='font-size: 14px; color: #888;'>({sentence})</span>"
        else:
            front_text = eng_meaning

    front = f"<div style='font-size: 20px; font-weight: 500;'>{front_text}</div>"
    
    back = f"<div style='font-size: 26px; margin-bottom: 8px;'><b>{sentence}</b></div>" \
           f"<div>{colored_py}</div><br>{audio_tag}"
    
    success = send_to_anki(RECOGNITION_DECK, front, back, tags=["sentence"], model=RECOGNITION_MODEL)
    if success:
        runtime_fronts.add(strip_punctuation(front_text).lower())
    return success

def create_production_card(sentence, colored_py, eng_meaning, audio_tag, runtime_prod_counts):
    front_text = eng_meaning if eng_meaning else f"Translate: {sentence}"

    norm_key = strip_punctuation(front_text).lower()
    count = runtime_prod_counts.get(norm_key, 0)
    if count > 0:
        front_text = f"{front_text} ({count + 1})"
    runtime_prod_counts[norm_key] = count + 1

    front = f"<div style='font-size: 20px; font-weight: 500;'>{front_text}</div>"
    back = f"<div style='font-size: 26px; margin-bottom: 8px;'><b>{sentence}</b></div>" \
           f"<div>{colored_py}</div><br>{audio_tag}"

    return send_to_anki(PRODUCTION_DECK, front, back, tags=["sentence", "production"], model=FORWARD_MODEL)

# ==========================================
# NOTION SYNC & ARCHIVE EXECUTION
# ==========================================

def fetch_notion_lines():
    blocks = notion.blocks.children.list(block_id=INBOX_PAGE_ID)
    lines, block_ids = [], []
    for block in blocks.get("results", []):
        block_type = block.get("type")
        if block_type in SUPPORTED_BLOCK_TYPES:
            text_objs = block[block_type].get("rich_text", [])
            if text_objs:
                text = text_objs[0].get("plain_text", "").strip()
                if text:
                    lines.append(text)
                    block_ids.append(block["id"])
    return lines, block_ids

def archive_to_notion(page_id, items_to_archive, category_label):
    if not page_id or "YOUR_" in page_id or not items_to_archive:
        if "YOUR_" in page_id:
            print(f"ℹ️ Set ARCHIVE_{category_label.upper()}_PAGE_ID in the script to enable {category_label} backup.")
        return

    children_blocks = []
    for item in items_to_archive:
        children_blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{
                    "type": "text",
                    "text": {"content": item}
                }]
            }
        })

    try:
        for i in range(0, len(children_blocks), 100):
            batch = children_blocks[i:i+100]
            notion.blocks.children.append(block_id=page_id, children=batch)
        print(f"📦 Successfully backed up {len(items_to_archive)} {category_label} to Notion Archive Page!")
    except Exception as e:
        print(f"⚠️ Could not archive {category_label} to Notion: {e}")

def clear_notion_blocks(block_ids):
    for b_id in block_ids:
        try:
            notion.blocks.delete(block_id=b_id)
        except Exception:
            pass

if __name__ == "__main__":
    print("📥 Fetching items from Notion inbox...")
    try:
        lines, block_ids = fetch_notion_lines()
        
        if not lines:
            print("✨ Notion inbox is empty!")
        else:
            print("🔍 Fetching existing Anki cards per deck...")
            vocab_terms = get_deck_terms(VOCAB_DECK)
            recognition_terms = get_deck_terms(RECOGNITION_DECK)
            production_terms = get_deck_terms(PRODUCTION_DECK)
            runtime_fronts = set()
            runtime_prod_counts = {}

            processed_blocks = []
            archived_vocab = []
            archived_sentences = []

            for raw_line, b_id in zip(lines, block_ids):
                if is_only_punctuation(raw_line):
                    processed_blocks.append(b_id)
                    continue

                is_explicit_word = raw_line.startswith("+")
                clean_line = raw_line.lstrip("+ ").strip()
                normalized_text = strip_punctuation(clean_line).lower()
                
                if not clean_line or not normalized_text:
                    processed_blocks.append(b_id)
                    continue

                # Rule 1: '+' prefix OR single Hanzi -> Vocab Deck
                if is_explicit_word or len(strip_punctuation(clean_line)) == 1:
                    if normalized_text in vocab_terms:
                        print(f"⏭️ Skipping duplicate (Vocab): {clean_line}")
                        processed_blocks.append(b_id)
                        continue

                    print(f"📌 Adding Word/Character: {clean_line}")
                    success = create_vocab_card(clean_line)
                    if success:
                        vocab_terms.add(normalized_text)
                        archived_vocab.append(clean_line)

                # Rule 2: Everything else -> Sentence Decks (Recognition + Production, checked independently)
                else:
                    needs_recognition = normalized_text not in recognition_terms
                    needs_production = normalized_text not in production_terms

                    if not needs_recognition and not needs_production:
                        print(f"⏭️ Skipping duplicate (already in both decks): {clean_line}")
                        processed_blocks.append(b_id)
                        continue

                    colored_py, eng_meaning, audio_tag = prepare_sentence_assets(clean_line)
                    added_recog = False
                    added_prod = False

                    if needs_recognition:
                        print(f"📝 Adding Sentence (Recognition): {clean_line}")
                        added_recog = create_sentence_card(clean_line, colored_py, eng_meaning, audio_tag, recognition_terms, runtime_fronts)
                        if added_recog:
                            recognition_terms.add(normalized_text)
                    else:
                        print(f"⏭️ Already in Recognition, skipping that deck: {clean_line}")

                    if needs_production:
                        print(f"📝 Adding Sentence (Production): {clean_line}")
                        added_prod = create_production_card(clean_line, colored_py, eng_meaning, audio_tag, runtime_prod_counts)
                        if added_prod:
                            production_terms.add(normalized_text)
                    else:
                        print(f"⏭️ Already in Production, skipping that deck: {clean_line}")

                    if added_recog or added_prod:
                        archived_sentences.append(clean_line)

                processed_blocks.append(b_id)

            if archived_vocab:
                print("\n📦 Backing up words/characters to Notion archive...")
                archive_to_notion(ARCHIVE_VOCAB_PAGE_ID, archived_vocab, "vocab")

            if archived_sentences:
                print("\n📦 Backing up sentences to Notion archive...")
                archive_to_notion(ARCHIVE_SENTENCES_PAGE_ID, archived_sentences, "sentences")

            print("\n🧹 Clearing Notion inbox...")
            clear_notion_blocks(processed_blocks)
            print("✨ Done! Hit 'Sync' in Anki.")
            
    except Exception as e:
        print(f"❌ Error: {e}")