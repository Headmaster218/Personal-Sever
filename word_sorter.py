import os
from nltk.tokenize import word_tokenize
from nltk.stem import WordNetLemmatizer
from nltk import pos_tag
from nltk.corpus import wordnet
import re
import requests
from bs4 import BeautifulSoup
import json

def load_meanings():
    if os.path.exists('data/meanings.json'):
        with open('data/meanings.json', 'r', encoding='utf-8') as file:
            return json.load(file)
    else:
        return {}

def save_meanings(meanings):
    with open('data/meanings.json', 'w', encoding='utf-8') as file:
        json.dump(meanings, file, ensure_ascii=False, indent=4)

def extract_meaning_from_baidu(word):
    # 尝试从缓存中获取释义
    meanings = load_meanings()
    if word in meanings:
        return meanings[word]

    # 如果缓存中没有，查询百度
    url = f"https://www.baidu.com/s?ie=UTF-8&wd={word}"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'}
    response = requests.get(url, proxies={"http": None, "https": None}, headers=headers)
    if response.status_code == 200:
        soup = BeautifulSoup(response.content, 'html.parser')
        meanings_elements = soup.find_all('span', {'class': 'op_dict_text2'})
        if meanings_elements:
            combined_meanings = ''.join(meaning.get_text() for meaning in meanings_elements)
            filtered_meanings = re.sub(r'[^\u4e00-\u9fff;]', '', combined_meanings)
            # 将新释义存入缓存
            meanings[word] = filtered_meanings
            save_meanings(meanings)
            return filtered_meanings
    # 如果网络查询失败，返回默认释义
    meanings[word] = "未找到释义"
    save_meanings(meanings)
    return "未找到释义"

def check_and_create_file(file_path):
    # os.path.dirname gets the directory path leading up to the file
    directory = os.path.dirname(file_path)
    
    # If the directory does not exist, create it
    if not os.path.exists(directory):
        os.makedirs(directory)
    
    # Now it's safe to create the file since the directory exists
    if not os.path.isfile(file_path):
        open(file_path, 'w').close()


def load_word_set(file_path):
    check_and_create_file(file_path)
    with open(file_path, 'r', encoding='utf-8') as f:
        return set(word.strip().lower() for word in f.readlines())

def save_word(word, file_path):
    with open(file_path, 'a', encoding='utf-8') as f:
        f.write(f'\n{word}')

def get_wordnet_pos(treebank_tag):
    """ 将 NLTK 的词性标记转换为 WordNet 的词性标记 """
    if treebank_tag.startswith('J'):
        return wordnet.ADJ
    elif treebank_tag.startswith('V'):
        return wordnet.VERB
    elif treebank_tag.startswith('N'):
        return wordnet.NOUN
    elif treebank_tag.startswith('R'):
        return wordnet.ADV
    else:
        return None

def process_text(text, known_words, unknown_words):
    text = re.sub(r'\W+', ' ', text)# 替换所有非字母和数字的字符为空格
    lemmatizer = WordNetLemmatizer()
    words = word_tokenize(text.lower())
    new_words = set()

    for word, pos in pos_tag(words):
        if not word.isalpha():# 跳过包含非字母字符的词汇
            continue
        wordnet_pos = get_wordnet_pos(pos) or wordnet.NOUN  # 默认为名词
        lemma = lemmatizer.lemmatize(word, pos=wordnet_pos)

        # 仅当原始单词或其基本形式不在已知或未知词库中时，添加到新词集
        if lemma not in known_words and lemma not in unknown_words:
            new_words.add(lemma)

    return new_words

def main(known_words_file, unknown_words_file, text):
    known_words = load_word_set(known_words_file)
    unknown_words = load_word_set(unknown_words_file)

    new_words = process_text(text, known_words, unknown_words)

    for word in new_words:
        while True:
            answer = input(f'y认识 n不认识 ？查询释义 {word} : ').strip().lower()
            if answer == 'y':
                save_word(word, known_words_file)
                break
            elif answer == 'n':
                save_word(word, unknown_words_file)
                break
            elif answer == '?'or'？':
                meaning = extract_meaning_from_baidu(word)
                print(meaning)
            else:
                print("无效的输入。请输入 'y' 或 'n'。")

if __name__ == "__main__":
    KNOWN_WORDS_FILE = 'known_words.txt'  # 已知词库文件路径
    UNKNOWN_WORDS_FILE = 'unknown_words.txt'  # 未知词库文件路径

    # 确保文本文件存在
    if not os.path.isfile(KNOWN_WORDS_FILE):
        open(KNOWN_WORDS_FILE, 'w').close()
    if not os.path.isfile(UNKNOWN_WORDS_FILE):
        open(UNKNOWN_WORDS_FILE, 'w').close()

    # 读取文本并执行主函数
    text = open("passage.txt", 'r', encoding='utf-8').read()
    main(KNOWN_WORDS_FILE, UNKNOWN_WORDS_FILE, text)
