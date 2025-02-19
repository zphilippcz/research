const natural = require('natural');
const synonyms = require('synonyms');
const nlp = require('compromise');

const tokenizer = new natural.WordTokenizer();
const text = "masage spa NY, oil change in michigan, oli change in New York";
const tokens = tokenizer.tokenize(text);

function getSynonyms(word) {
    const syns = synonyms(word);
    return syns ? Object.values(syns).flat() : [];
}

let doc = nlp(text);
let localities = doc.topics().out('array');

const result = {
    query: text,
    localities: localities,
    tokens: tokens,
    synonyms: tokens.map(token => ({ word: token, synonyms: getSynonyms(token) }))
};

console.log(JSON.stringify(result, null, 4));

