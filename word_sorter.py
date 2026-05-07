import json
import os
import re
import sqlite3

import requests
from nltk import pos_tag
from nltk.corpus import wordnet
from nltk.stem import WordNetLemmatizer
from nltk.tokenize import word_tokenize


MEANINGS_CACHE_PATH = os.path.join('data', 'meanings.json')
ECDICT_DB_PATH = os.path.join('data', 'ecdict.db')


def load_meanings():
    if os.path.exists(MEANINGS_CACHE_PATH):
        with open(MEANINGS_CACHE_PATH, 'r', encoding='utf-8') as file:
            return json.load(file)
    return {}


def save_meanings(meanings):
    directory = os.path.dirname(MEANINGS_CACHE_PATH)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(MEANINGS_CACHE_PATH, 'w', encoding='utf-8') as file:
        json.dump(meanings, file, ensure_ascii=False, indent=4)


def format_ecdict_entry(entry):
    parts = []
    phonetic = entry.get('phonetic')
    translation = entry.get('translation')
    definition = entry.get('definition')

    if phonetic:
        parts.append(f"[{phonetic}]")
    if translation:
        parts.append(translation.strip())
    if definition:
        parts.append(definition.strip())

    return '\n'.join(parts) if parts else None


def extract_meaning_from_ecdict(word):
    if not os.path.exists(ECDICT_DB_PATH):
        print(f"Warning: {ECDICT_DB_PATH} 不存在，跳过本地词典查询")
        return None

    try:
        with sqlite3.connect(ECDICT_DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT word, phonetic, definition, translation
                FROM stardict
                WHERE word = ? COLLATE NOCASE
                LIMIT 1
                """,
                (word,),
            )
            row = cursor.fetchone()
    except sqlite3.Error as e:
        print(f"Warning: 查询 ECDICT 失败：{e}")
        return None

    if not row:
        return None
    return format_ecdict_entry(dict(row))


def extract_meaning_from_dictionary_api(word):
    url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{word}"
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as e:
        print(f"Warning: dictionaryapi.dev 查询失败：{e}")
        return None

    if not isinstance(data, list) or not data:
        return None

    entry = data[0]
    parts = []

    for phonetic in entry.get('phonetics') or []:
        text = phonetic.get('text')
        if text:
            parts.append(text)
            break

    for meaning in entry.get('meanings') or []:
        part_of_speech = meaning.get('partOfSpeech')
        definitions = meaning.get('definitions') or []
        if not definitions:
            continue

        first_definition = definitions[0]
        definition = first_definition.get('definition')
        example = first_definition.get('example')
        if definition:
            prefix = f"{part_of_speech}. " if part_of_speech else ""
            parts.append(prefix + definition)
        if example:
            parts.append(f"例句: {example}")
        if len(parts) >= 4:
            break

    return '\n'.join(parts) if parts else None


def extract_meaning(word):
    word = word.strip().lower()
    if not word:
        return "未找到释义"

    meanings = load_meanings()
    if word in meanings:
        return meanings[word]

    meaning = extract_meaning_from_ecdict(word)
    if not meaning:
        meaning = extract_meaning_from_dictionary_api(word)
    if not meaning:
        meaning = "未找到释义"

    meanings[word] = meaning
    save_meanings(meanings)
    return meaning


def extract_meaning_from_baidu(word):
    return extract_meaning(word)


def extract_meaning_from_kmf(word):
    return extract_meaning(word)


def check_and_create_file(file_path):
    directory = os.path.dirname(file_path)
    if directory and not os.path.exists(directory):
        os.makedirs(directory)
    if not os.path.isfile(file_path):
        open(file_path, 'w', encoding='utf-8').close()


def load_word_set(file_path):
    check_and_create_file(file_path)
    with open(file_path, 'r', encoding='utf-8') as f:
        return set(word.strip().lower() for word in f.readlines())


def save_word(word, file_path):
    with open(file_path, 'a', encoding='utf-8') as f:
        f.write(f'\n{word}')


def get_wordnet_pos(treebank_tag):
    if treebank_tag.startswith('J'):
        return wordnet.ADJ
    if treebank_tag.startswith('V'):
        return wordnet.VERB
    if treebank_tag.startswith('N'):
        return wordnet.NOUN
    if treebank_tag.startswith('R'):
        return wordnet.ADV
    return None


def process_text(text, known_words, unknown_words):
    text = re.sub(r'\W+', ' ', text)
    lemmatizer = WordNetLemmatizer()
    words = word_tokenize(text.lower())
    new_words = set()

    for word, pos in pos_tag(words):
        if not word.isalpha():
            continue
        wordnet_pos = get_wordnet_pos(pos) or wordnet.NOUN
        lemma = lemmatizer.lemmatize(word, pos=wordnet_pos)

        if lemma not in known_words and lemma not in unknown_words:
            new_words.add(lemma)

    return new_words


def main(known_words_file, unknown_words_file, text):
    known_words = load_word_set(known_words_file)
    unknown_words = load_word_set(unknown_words_file)
    new_words = process_text(text, known_words, unknown_words)

    for word in new_words:
        while True:
            answer = input(f"y认识 n不认识 ?查询释义 {word}: ").strip().lower()
            if answer == 'y':
                save_word(word, known_words_file)
                break
            if answer == 'n':
                save_word(word, unknown_words_file)
                break
            if answer in ('?', '？'):
                print(extract_meaning(word))
                continue
            print("无效的输入。请输入 'y'、'n' 或 '?'。")


if __name__ == "__main__":
    known_words_file = 'known_words.txt'
    unknown_words_file = 'unknown_words.txt'
    text = open("passage.txt", 'r', encoding='utf-8').read()
    main(known_words_file, unknown_words_file, text)
