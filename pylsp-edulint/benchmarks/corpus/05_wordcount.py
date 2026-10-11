import string

def clean(word):
    result = ""
    for c in word:
        if not c in string.punctuation:
            result += c
    return result.lower()

def count_words(text):
    counts = {}
    for w in text.split():
        w = clean(w)
        if w in counts.keys():
            counts[w] += 1
        else:
            counts[w] = 1
    return counts

text = "the quick brown fox jumps over the lazy dog. The dog barks; the fox runs!"
counts = count_words(text)
for w in sorted(counts):
    print(w, counts[w])
if len(counts) > 0:
    print("distinct:", len(counts))
else:
    pass
