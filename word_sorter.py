import json
import os
import re
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta

import requests
from nltk import pos_tag
from nltk.corpus import wordnet
from nltk.stem import WordNetLemmatizer
from nltk.tokenize import word_tokenize


MEANINGS_CACHE_PATH = os.path.join('data', 'meanings.json')
ECDICT_DB_PATH = os.path.join('data', 'ecdict.db')
PERIOD_OPTIONS = [
    ('day', '一天'),
    ('week', '一周'),
    ('month', '一月'),
    ('half_year', '半年'),
    ('year', '一年'),
    ('all', '从头到现在'),
]
PERIOD_DAYS = {
    'day': 1,
    'week': 7,
    'month': 30,
    'half_year': 183,
    'year': 365,
}


def get_user_word_paths(user_name):
    base_path = os.path.join('.', 'data', 'user word', user_name)
    return {
        'base': base_path,
        'known': os.path.join(base_path, 'known_words.txt'),
        'unknown': os.path.join(base_path, 'unknown_words.txt'),
        'events': os.path.join(base_path, 'word_events.jsonl'),
    }


def get_period_options():
    return [{'value': value, 'label': label} for value, label in PERIOD_OPTIONS]


def get_period_days(period):
    return PERIOD_DAYS.get(period)


def parse_anchor_date(anchor_date=None):
    if anchor_date:
        try:
            return datetime.strptime(anchor_date, '%Y-%m-%d').date()
        except (TypeError, ValueError):
            pass
    return datetime.now().date()


def get_period_range(period, anchor_date=None):
    anchor = parse_anchor_date(anchor_date)
    if period == 'day':
        return anchor, anchor
    if period == 'week':
        start = anchor - timedelta(days=anchor.weekday())
        return start, start + timedelta(days=6)
    if period == 'month':
        start = anchor.replace(day=1)
        if start.month == 12:
            end = start.replace(year=start.year + 1, month=1, day=1) - timedelta(days=1)
        else:
            end = start.replace(month=start.month + 1, day=1) - timedelta(days=1)
        return start, end
    if period == 'half_year':
        if anchor.month <= 6:
            return anchor.replace(month=1, day=1), anchor.replace(month=6, day=30)
        return anchor.replace(month=7, day=1), anchor.replace(month=12, day=31)
    if period == 'year':
        return anchor.replace(month=1, day=1), anchor.replace(month=12, day=31)
    return None, None


def format_period_range(period, anchor_date=None):
    start, end = get_period_range(period, anchor_date)
    if not start or not end:
        return '全部记录'
    if start == end:
        return start.strftime('%Y-%m-%d')
    return f"{start.strftime('%Y-%m-%d')} 至 {end.strftime('%Y-%m-%d')}"


def parse_event_date(event):
    date_text = event.get('date')
    if not date_text:
        timestamp = event.get('timestamp', '')
        date_text = timestamp[:10]
    try:
        return datetime.strptime(date_text, '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return None


def filter_events_by_period(events, period, anchor_date=None):
    start_date, end_date = get_period_range(period, anchor_date)
    if not start_date or not end_date:
        return events

    return [
        event for event in events
        if start_date <= (parse_event_date(event) or datetime.min.date()) <= end_date
    ]


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
        print(f"Warning: {ECDICT_DB_PATH} not found, skipping local dictionary lookup.")
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
        print(f"Warning: ECDICT lookup failed: {e}")
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
        print(f"Warning: dictionaryapi.dev lookup failed: {e}")
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
            parts.append(f"Example: {example}")
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
        os.makedirs(directory, exist_ok=True)
    if not os.path.isfile(file_path):
        open(file_path, 'w', encoding='utf-8').close()


def load_word_set(file_path):
    check_and_create_file(file_path)
    with open(file_path, 'r', encoding='utf-8') as f:
        return set(word.strip().lower() for word in f.readlines() if word.strip())


def save_word(word, file_path):
    word = word.strip().lower()
    if not word:
        return

    words = load_word_set(file_path)
    if word in words:
        return

    with open(file_path, 'a', encoding='utf-8') as f:
        f.write(f'{word}\n')


def record_word_result(user_name, word, recognized):
    word = word.strip().lower()
    if not word:
        return

    paths = get_user_word_paths(user_name)
    check_and_create_file(paths['events'])
    now = datetime.now()
    record = {
        'word': word,
        'recognized': bool(recognized),
        'result': 'known' if recognized else 'unknown',
        'date': now.strftime('%Y-%m-%d'),
        'timestamp': now.isoformat(timespec='seconds'),
    }
    with open(paths['events'], 'a', encoding='utf-8') as f:
        f.write(json.dumps(record, ensure_ascii=False) + '\n')


def load_word_events(user_name):
    paths = get_user_word_paths(user_name)
    if not os.path.exists(paths['events']):
        return []

    events = []
    with open(paths['events'], 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def get_word_status_from_events(events):
    status_by_word = {}
    for event in events:
        word = (event.get('word') or '').strip().lower()
        if not word:
            continue
        status_by_word[word] = bool(event.get('recognized'))
    return status_by_word


def get_word_list(user_name, period='all', anchor_date=None):
    paths = get_user_word_paths(user_name)
    if period == 'all':
        known_words = sorted(load_word_set(paths['known']))
        unknown_words = sorted(load_word_set(paths['unknown']))
    else:
        events = filter_events_by_period(load_word_events(user_name), period, anchor_date)
        status_by_word = get_word_status_from_events(events)
        known_words = sorted(word for word, recognized in status_by_word.items() if recognized)
        unknown_words = sorted(word for word, recognized in status_by_word.items() if not recognized)

    return {
        'known_words': known_words,
        'unknown_words': unknown_words,
    }


def build_daily_stats(events, period='all', anchor_date=None):
    daily = defaultdict(lambda: {'known': 0, 'unknown': 0, 'total': 0})
    start, end = get_period_range(period, anchor_date)
    if start and end:
        days = (end - start).days + 1
        for offset in range(days):
            date = (start + timedelta(days=offset)).strftime('%Y-%m-%d')
            daily[date]['date'] = date

    for event in events:
        event_date = parse_event_date(event)
        if not event_date:
            continue
        key = event_date.strftime('%Y-%m-%d')
        bucket = daily[key]
        bucket['date'] = key
        if event.get('recognized'):
            bucket['known'] += 1
        else:
            bucket['unknown'] += 1
        bucket['total'] += 1
    return [daily[date] for date in sorted(daily)]


def build_empty_daily_stats(period, anchor_date=None):
    start, end = get_period_range(period, anchor_date)
    if not start or not end:
        return []
    days = (end - start).days + 1
    date_labels = [(start + timedelta(days=offset)).strftime('%Y-%m-%d') for offset in range(days)]
    return [{'date': date, 'known': 0, 'unknown': 0, 'total': 0} for date in date_labels]


def get_word_stats(user_name, period='week', anchor_date=None):
    anchor = parse_anchor_date(anchor_date).strftime('%Y-%m-%d')
    all_events = load_word_events(user_name)
    events = filter_events_by_period(all_events, period, anchor)
    word_list = get_word_list(user_name, period, anchor)
    daily = build_daily_stats(events, period, anchor)
    if not daily:
        daily = build_empty_daily_stats(period, anchor)

    unique_words = {event.get('word') for event in events if event.get('word')}
    return {
        'known_count': len(word_list['known_words']),
        'unknown_count': len(word_list['unknown_words']),
        'unique_count': len(unique_words),
        'event_count': len(events),
        'daily': daily,
        'period': period,
        'anchor_date': anchor,
        'range_label': format_period_range(period, anchor),
        'period_options': get_period_options(),
        **word_list,
    }


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
