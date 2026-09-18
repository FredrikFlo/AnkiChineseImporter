# Anki Chinese Importer

Turn a Chinese characters into fully-formatted Anki flashcards for
Chinese: colored tone-marked pinyin, auto-generated audio, English
translations, HSK tags, and character decomposition — split across three
decks (Recognition, Production, Vocab). 
I use this by writing down any phrase / word i have learned recently into Notion.
This allows me to create flashcards for chinese that is relevant to me, which in turn makes it easier to learn.
I ended up making this mainly so that I had a seemless method of creating said flashcards.

## How it works

1. You jot down Chinese words or sentences (in Character form) as blocks on a Notion page.
2. Running `AnkiChineseImporter.py` pulls those lines, decides whether each one is a
   single word/character or a full sentence, and builds the appropriate card(s):
   - **Single Hanzi or lines starting with `+`** → added to the **Vocab** deck
     (with pinyin, translation, HSK tag, and a character breakdown).
   - **Everything else** → added to both the **Recognition** deck (see Chinese,
     recall the meaning) and the **Production** deck (see the English, recall
     the Chinese), each with colored pinyin and generated audio.
3. Processed lines are cleared from the Notion inbox (and optionally archived
   to separate Notion pages first).

`FixTranslations.py` is a companion script that retries any cards that failed
to get a translation on the first pass (e.g. due to a rate limit).

## Prerequisites

- [Anki](https://apps.ankiweb.net/) installed and running
- The [AnkiConnect](https://ankiweb.net/shared/info/2055492159) add-on installed
  (Tools → Add-ons → Get Add-ons → code `2055492159`, then restart Anki)
- Python 3.9+
- [Notion](https://www.notion.com/) A cloud-based notes app.
- A [Notion integration token](https://www.notion.so/my-integrations)

## Setup

### 1. Install dependencies

```bash
git clone https://github.com/FredrikFlo/AnkiChineseImporter.git/
cd AnkiChineseImport
pip install -r requirements.txt
```

### 2. Configure Notion access

1. Create Notion Pages (Anki Chinese Importer, Anki Sentences Archive, Anki Characters Archive) **Case-sensitive**
2. Create an integration at [notion.so/my-integrations](https://www.notion.so/my-integrations)
   and copy its secret Access Token.
   - Make it of type Access Token. 
4. ON all of the Notion Pages click the
   `...` menu → **Connections** → connect your integration.
5. Copy `.env.example` to `.env` and fill in the empty values:

   ```bash
   cp .env.example .env
   ```

   | Variable | Where to find it |
   |---|---|
   | `NOTION_TOKEN` | The integration Access Token from step 2 |
   | `INBOX_PAGE_ID` | The 32-character ID found in the Notion Pages' URL |
   | `ARCHIVE_VOCAB_PAGE_ID` | (Optional) - // - |
   | `ARCHIVE_SENTENCES_PAGE_ID` | (Optional) - // - |

   Leave the archive variables blank to disable archiving — items will just
   be deleted from the inbox after import instead of being copied elsewhere first.

   **Never commit your real `.env`** — it's already covered by `.gitignore`.

### 3. Set up your Anki decks and note types

The script expects these exact deck names to exist in Anki (create them if
they don't):

- `Chinese Sentences (Recognition)`
- `Chinese Sentences (Production)`
- `Chinese Vocab`

And these note types (**Case Sensitive**):

- `Basic (Back -> Front)` — used for Recognition cards. Based on Anki's
  built-in "Basic (and reversed card)" type, showing the back side first.
- `Basic (Front -> Back)` — used for Vocab and Production cards. This can
  just be a renamed copy of Anki's default "Basic" type.

If your deck or note-type names differ, edit the constants near the top of
`AnkiChineseImporter.py` (`RECOGNITION_DECK`, `PRODUCTION_DECK`, `VOCAB_DECK`,
`RECOGNITION_MODEL`, `FORWARD_MODEL`) to match.  

In order to make these notes go to Tools -> Manage Note Types and either add new cards or rename the existing cards. 
The most important thing is that there is a front and back

## Usage

Make sure Anki is open (AnkiConnect only works while Anki is running), then:

```bash
python AnkiChineseImporter.py
```

Write lines into your Notion inbox like this:

```
+ 你好
好
你叫什么名字？
```

- `+ 你好` → forced into the Vocab deck even though it's multiple characters
- `好` → single character, automatically goes to Vocab
- `你叫什么名字？` → a sentence, goes to both sentence decks

If a translation fails partway through (network hiccup, rate limit), run:

```bash
python FixTranslations.py
```

to retry just the cards marked as failed.

## Troubleshooting

**"You made too many requests to the server" on every single translation:**
This is Google's free translate endpoint (used under the hood by
`deep-translator`) rate-limiting your IP. It's usually an extended cooldown
(minutes to over an hour), not something a quick retry fixes — if it's
failing on every card, including on a second run, just wait a while before
trying again. Both scripts back off exponentially between retries (2s, 4s,
8s) to avoid making it worse, but there's no way to force Google to lift
the limit early.

## Notes

- `translation_cache.json` and `hanzi_decomp_cache.json` are created
  automatically on first run and are git-ignored — they're personal, growing
  caches, not something to check in.
- Audio is generated via Google TTS and stored directly into Anki's media
  folder through AnkiConnect, so no manual file handling is needed.
- I recommend downloading the Notion app on your phone. Then you can add characters
  and sentences throughout the day and when you get home you can run the script
  (without closing the laptop) and see all your cards in Anki.
- Everytime you add a card remember to sync in Anki so that it shows up on your phone etc.
- 
