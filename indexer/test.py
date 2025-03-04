import sqlite3

def count_word_occurrences(db_path, target_word):
    # Připojení k databázi
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # SQL dotaz k načtení dat
    cursor.execute("""
    SELECT                                 
            
            COALESCE(MAX(d.title_general), '') || ' ' ||
            COALESCE(MAX(d.highlights), '') || ' ' ||
            COALESCE(GROUP_CONCAT(o.title, ','), '') || ' ' ||
            COALESCE(MAX(m.name), '') AS text
               
        FROM deals d
            LEFT JOIN merchant m ON (d.merchant_id=m.id)
            LEFT JOIN options o ON (o.deal_id=d.id)
        GROUP BY d.deal_uuid

    """)
    word_count = 0

    # Projití řádků a počítání výskytů slova
    old = 0
    doc = 0
    for row in cursor.fetchall():
        # Převeďte řádek na řetězec a spočítejte výskyty slova
        column_data = row[0]  # Předpokládá se, že `my_column` je první sloupec
        word_count += column_data.lower().count(target_word.lower())  # Porovnání bez rozdílu v malých a velkých písmenech
        if word_count != old:
            doc = doc + 1
        old = word_count

    # Uzavření spojení
    cursor.close()
    conn.close()

    print (f"celkem: {old} doc: {doc}")
    return word_count

# Příklad použití
if __name__ == "__main__":
    database_path = '/Users/zphilipp/git/research/dealsdb/deals_db1.db'  # Nahraďte cestou k vaší databázi
    table_name = 'deals'               # Název tabulky
    target_word = 'massage'                  # Slovo, jehož výskyty chcete počítat

    occurrences = count_word_occurrences(database_path, target_word)
    print(f"Slovo '{target_word}' se vyskytuje {occurrences} krát.")
