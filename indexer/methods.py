import re

words_to_remove = [
    "about", "above", "across", "after", "against", "along", "among", "around", 
    "before", "behind", "below", "beneath", "beside", "between", "beyond", "by",
    "during", "for", "from", "in", "inside", "into", "near", "of", "off", "on",
    "out", "outside", "over", "through", "throughout", "toward", "under",
    "until", "within", "without", "and", "but", "or", "for", "nor",
    "so", "yet", "although", "because", "as", "since", "unless", "while", "when",
    "where", "after", "before", "the", "a", "b", "c", "d", "e", "f", "g", "h",
    "i", "j", "k", "l", "m", "n", "o", "p", "q", "r", "s", "t", "u",
    "v", "w", "x", "y", "z", "aa", "aaa", "aaaa", #, "to", "up", "with", "at",
]
words_pattern = r'\b(' + '|'.join(map(re.escape, words_to_remove)) + r')\b'


def clean_text(text):
    text = remove_chinese_characters(text).lower()
    cleaned_text = re.sub(words_pattern, '', text, flags=re.IGNORECASE)
    cleaned_text = re.sub(r'(?<!\w)[,;](?!\w)', ' ', cleaned_text)  # replace commas and semicolons not between words with space
    cleaned_text = re.sub(r'(?<=\w),(?=\w)', ' ', cleaned_text)  # replace commas between words with space
    cleaned_text = re.sub(r'(?<!\w)[-](?!\w)', ' ', cleaned_text)  # replace hyphens not between words with space
    cleaned_text = re.sub(r"[();.,=+\-/&'!]", "", cleaned_text)  # special characters
    cleaned_text = re.sub(r'\b\d\b', '', cleaned_text)  # remove single digit numbers
    
    #words = cleaned_text.split()
    #singularized_words = [singularize(word) for word in words]
    #cleaned_text = ' '.join(singularized_words)

    return re.sub(r'\s+', ' ', cleaned_text).strip()

def remove_chinese_characters(text):
    # Regular expression pattern to match Chinese characters
    patt = r'[\u4e00-\u9fff]+'
    # Substitute Chinese characters with an empty string
    cleaned_text = re.sub(patt, '', text)
    return cleaned_text
