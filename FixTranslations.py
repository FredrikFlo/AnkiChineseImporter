import os
import re
import json
import time
import requests
from deep_translator import GoogleTranslator, MyMemoryTranslator

ANKI_URL = "http://localhost:8765"
VOCAB_DECK = "Chinese Vocab"
SENTENCE_DECKS = ["Chinese Sentences (Recognition)", "Chinese Sentences (Production)"]
TRANSLATION_CACHE_FILE = "translation_cache.json"

VOCAB_FAILURE_MARKER = "[Translation Unavailable]"
SENTENCE_FAILURE_PREFIX = "Translate: "

PUNCTUATION_PATTERN = r'[ \t\r\n\.\,\!\?\,\;\:\“\”\‘\’\（\）\《\》\【\】\—\…\。\，\！\？\；\：]'


def strip_html_tags(text):
    return re.sub(r'<[^>]+>', '', text).strip()


def strip_punctuation(text):
    return re.sub(PUNCTUATION_PATTERN, '', text)


def load_cache():
    if os.path.exists(TRANSLATION_CACHE_FILE):
        with open(TRANSLATION_CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_cache(cache):
    with open(TRANSLATION_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)


def translate_text(text, cache, retries=3):
    if text in cache:
        return cache[text]

    for attempt in range(retries):
        try:
            result = GoogleTranslator(source='zh-CN', target='en').translate(text)
            if result:
                cache[text] = result
                save_cache(cache)
                return result
        except Exception as e:
            print(f"  ⚠️ Attempt {attempt+1} failed: {e}")
            if attempt < retries - 1:
                wait = 2 ** (attempt + 1)  # 2s, 4s, 8s...
                print(f"  ⏳ Backing off for {wait}s before retrying...")
                time.sleep(wait)

    print(f"  🔁 Falling back to MyMemory for: {text}")
    try:
        result = MyMemoryTranslator(source='zh-CN', target='en-US').translate(text)
        if result:
            cache[text] = result
            save_cache(cache)
            return result
    except Exception as e:
        print(f"  ⚠️ MyMemory fallback also failed: {e}")

    return None


def get_deck_notes(deck_name):
    query = f'deck:"{deck_name}"'
    payload = {"action": "findNotes", "version": 6, "params": {"query": query}}
    res = requests.post(ANKI_URL, json=payload).json()
    note_ids = res.get("result", [])
    if not note_ids:
        return []

    info_res = requests.post(ANKI_URL, json={"action": "notesInfo", "version": 6, "params": {"notes": note_ids}}).json()
    return info_res.get("result", [])


def update_note_field(note_id, field_name, new_value):
    payload = {
        "action": "updateNoteFields",
        "version": 6,
        "params": {
            "note": {
                "id": note_id,
                "fields": {field_name: new_value}
            }
        }
    }
    res = requests.post(ANKI_URL, json=payload).json()
    return not res.get("error")


def fix_vocab_deck(cache):
    print(f"🔍 Checking [{VOCAB_DECK}] for missing translations...")
    notes = get_deck_notes(VOCAB_DECK)
    broken = [n for n in notes if VOCAB_FAILURE_MARKER in n["fields"]["Back"]["value"]]

    if not broken:
        print("  ✨ Nothing to fix here.\n")
        return

    print(f"  Found {len(broken)} card(s).\n")
    for note in broken:
        note_id = note["noteId"]
        front_html = note["fields"]["Front"]["value"]
        back_html = note["fields"]["Back"]["value"]

        clean_term = strip_punctuation(strip_html_tags(front_html))
        if not clean_term:
            continue

        print(f"  📌 Retrying: {clean_term}")
        new_translation = translate_text(clean_term, cache)

        if new_translation:
            new_back_html = back_html.replace(VOCAB_FAILURE_MARKER, new_translation)
            success = update_note_field(note_id, "Back", new_back_html)
            print(f"    ✅ Fixed -> {new_translation}" if success else "    ❌ Anki update failed")
        else:
            print("    ⚠️ Still no translation available")

        time.sleep(1.5)
    print()


def fix_sentences_deck(cache, deck_name):
    print(f"🔍 Checking [{deck_name}] for missing translations...")
    notes = get_deck_notes(deck_name)
    broken = [n for n in notes if strip_html_tags(n["fields"]["Front"]["value"]).startswith(SENTENCE_FAILURE_PREFIX)]

    if not broken:
        print("  ✨ Nothing to fix here.\n")
        return

    print(f"  Found {len(broken)} card(s).\n")
    for note in broken:
        note_id = note["noteId"]
        front_text = strip_html_tags(note["fields"]["Front"]["value"])
        sentence = front_text[len(SENTENCE_FAILURE_PREFIX):].strip()
        if not sentence:
            continue

        print(f"  📌 Retrying: {sentence}")
        new_translation = translate_text(sentence, cache)

        if new_translation:
            new_front_html = f"<div style='font-size: 20px; font-weight: 500;'>{new_translation}</div>"
            success = update_note_field(note_id, "Front", new_front_html)
            print(f"    ✅ Fixed -> {new_translation}" if success else "    ❌ Anki update failed")
        else:
            print("    ⚠️ Still no translation available")

        time.sleep(1.5)
    print()


if __name__ == "__main__":
    cache = load_cache()
    fix_vocab_deck(cache)
    for deck in SENTENCE_DECKS:
        fix_sentences_deck(cache, deck)
    print("✨ Done! Hit 'Sync' in Anki.")