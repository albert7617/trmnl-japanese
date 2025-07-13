import requests
import os
import time
from tqdm import tqdm
import sys
import json
from bs4 import BeautifulSoup
from bs4.element import Tag as bs_Tag_t

import sqlite3
from pathlib import Path
from typing import List, Dict
import hashlib

def create_combined_html(extracted_results, output_file="combined_results.html"):
    """
    Combine extracted results from multiple pages into a single HTML file.

    Args:
        extracted_results: List of results from extract_words_with_clean_meanings()
        output_file: Path to save the combined HTML file
    """
    # HTML template with basic structure
    html_template = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Jisho.org Extracted Words with Sentences</title>
    <style>
        body {{ font-family: Arial, sans-serif; line-height: 1.6; margin: 0 auto; max-width: 900px; padding: 20px; }}
        .word-entry {{ border-top: 1px solid #eee; margin-top: 30px; padding-top: 20px; }}
        .representation {{ font-size: 1.5em; margin-bottom: 10px; }}
        .meaning-wrapper {{ background: #f9f9f9; padding: 5px; border-radius: 5px; margin-bottom: 15px; }}
        .sentence {{ margin-top: 10px; padding-left: 15px; border-left: 3px solid #ddd; }}
        .japanese {{ font-size: 1.2em; }}
        .page-info {{ color: #666; font-size: 0.9em; margin-bottom: 5px; }}
    </style>
    <link rel="stylesheet" href="combined_results.css">
</head>
<body>
    <h1>Jisho.org Extracted Words with Sentences</h1>
    <p>Total words extracted: {word_count}</p>
    <div id="word-entries">
        {word_entries}
    </div>
</body>
</html>"""

    word_entries_html = []
    total_words = 0

    for page_results in extracted_results:
        for entry in page_results:
            total_words += 1
            # Create HTML for each word entry
            entry_html = f"""
            <div class="word-entry">
                <div class="representation">
                    {entry['representation']}
                </div>"""

            for wrapper in entry['meaning_wrappers']:
                entry_html += f"""
                <div class="meaning-wrapper">
                    {wrapper}
                </div>"""

            entry_html += "\n            </div>"
            word_entries_html.append(entry_html)

    # Combine all entries
    combined_html = html_template.format(
        word_count=total_words,
        word_entries="\n".join(word_entries_html)
    )

    # Save to file
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(combined_html)

    print(f"Successfully created combined HTML file: {output_file}")
    print(f"Total words included: {total_words}")

def extract_words_with_sentences(soup):
    """
    Extract words with sentences from jisho.org HTML soup.

    Args:
        soup: BeautifulSoup object of jisho.org word search page

    Returns:
        List of dictionaries containing:
        - representation: raw HTML of concept_light-representation
        - meaning_wrappers: list of raw HTML divs of meaning-wrapper
                           that contain at least one sentence
    """
    results = []

    # Find all word entries
    word_entries = soup.find_all('div', class_='concept_light')

    for entry in word_entries:
        # Get the word representation
        representation = entry.find('div', class_='concept_light-representation')
        if not representation:
            continue

        # Find all meaning wrappers that contain sentences
        meaning_wrappers = []
        for wrapper in entry.find_all('div', class_='meaning-wrapper'):
            if not wrapper.find('div', class_='sentence'):
                continue


            # Create a copy to modify
            wrapper_copy = BeautifulSoup(str(wrapper), 'html.parser').find('div')

            if not isinstance(wrapper_copy, bs_Tag_t):
                print("wrapper_copy", type(wrapper_copy))
                continue

            # Remove definition dividers if they exist
            for divider in wrapper_copy.find_all('span', class_='meaning-definition-section_divider'):
                divider.decompose()

            # Remove zero-width space spans
            for zwsp in wrapper_copy.find_all('span', string='\u200b'):
                zwsp.decompose()

            # Remove supplemental_info spans
            for supplemental_info in wrapper_copy.find_all('span', class_='supplemental_info'):
                supplemental_info.decompose()

            # Remove newlines while preserving HTML structure
            wrapper_html = str(wrapper_copy).replace('\n', '')
            meaning_wrappers.append(wrapper_html)


        # Only include entries that have meaning wrappers with sentences
        if meaning_wrappers:
            representation_html = str(representation).replace('\n', '')
            results.append({
                'representation': representation_html,
                'meaning_wrappers': meaning_wrappers
            })

    return results

def iterate_jisho_html_files(directory='jisho_pages'):
    """
    Generator function that opens each HTML file in the directory and yields BeautifulSoup objects

    Usage:
    for soup, filename in iterate_jisho_html_files():
        # Your processing code here
        print(f"Processing {filename}")
        print(soup.title)
    """
    # Get all HTML files in the directory, sorted numerically
    files = sorted(
        [f for f in os.listdir(directory) if f.endswith('.html')],
        key=lambda x: int(x.split('_')[1].split('.')[0])
    )

    for filename in files:
        filepath = os.path.join(directory, filename)
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                soup = BeautifulSoup(f.read(), 'html.parser')
                yield soup, filename
        except Exception as e:
            print(f"Error processing {filename}: {e}")
            continue

def store_extracted_results(results: List[List[Dict]], db_path: str = "jisho_words.db"):
    """
    Store extracted results in persistent SQLite database with HTML preview.

    Args:
        results: List of page results from extract_words_with_clean_meanings()
        output_dir: Directory to store output files

    Creates:
        - SQLite database (jisho_words.db) with full structured data
        - HTML preview (preview.html) for quick browsing
        - Checksum file for data integrity verification
    """

    # Flatten the list of page results
    all_entries = [entry for page in results for entry in page]

    with sqlite3.connect(db_path) as conn:
        c = conn.cursor()

        # Create tables with improved schema
        c.execute("""
        CREATE TABLE IF NOT EXISTS words (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            representation_html TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")

        c.execute("""
        CREATE TABLE IF NOT EXISTS meaning_wrappers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            word_id INTEGER NOT NULL,
            wrapper_html TEXT NOT NULL,
            FOREIGN KEY(word_id) REFERENCES words(id) ON DELETE CASCADE
        )""")

        # Create index for faster queries
        c.execute("""
        CREATE INDEX IF NOT EXISTS idx_word_id ON meaning_wrappers(word_id)
        """)

        # Insert data in transaction
        conn.execute("BEGIN TRANSACTION")
        try:
            for entry in all_entries:
                c.execute(
                    "INSERT INTO words (representation_html) VALUES (?)",
                    (entry['representation'],)
                )
                word_id = c.lastrowid

                for wrapper in entry['meaning_wrappers']:
                    c.execute(
                        "INSERT INTO meaning_wrappers (word_id, wrapper_html) VALUES (?, ?)",
                        (word_id, wrapper)
                    )
            conn.commit()
        except:
            conn.rollback()
            raise

    print(f"Stored {len(all_entries)} words in SQLite database: {db_path}")


def download_jisho_pages(base_url, end_page):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }

    # Create directory to store pages
    os.makedirs('jisho_pages', exist_ok=True)

    for page in tqdm(range(1, end_page+1)):  # pages 1 to 90
        url = base_url + str(page)
        filename = f"jisho_pages/page_{page}.html"

        # Skip if file already exists
        if os.path.exists(filename):
            continue

        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()  # Raise an error for bad status codes

            # Save raw HTML
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(response.text)

            # Be polite - don't overload their servers
            time.sleep(2)  # Increased delay to be more conservative

        except requests.exceptions.RequestException as e:
            print(f"Error downloading page {page}: {e}")
            continue

    print("Download completed. Pages saved in 'jisho_pages' directory")

if __name__ == "__main__":
    download_jisho_pages("https://jisho.org/search/%23jlpt-n1%20%23words?page=", 172)
    results = []
    for soup, filename in iterate_jisho_html_files():
        print(f"--- Processing {filename} ---")
        results.append(extract_words_with_sentences(soup))

    create_combined_html(results)
    store_extracted_results(results)

