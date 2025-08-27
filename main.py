import sqlite3
import hashlib
import zlib
import json
import base64
from datetime import datetime, timedelta
import os
from typing import List, Dict

import traceback
import sys
import os
import json
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
import logging
import requests
import base64
from pprint import pprint


from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.exceptions import RequestValidationError
from starlette.responses import FileResponse, PlainTextResponse, JSONResponse

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logging.basicConfig(level = logging.INFO)

DB_PATH = os.path.join("data", "jisho_words.db")
TRNML_HISTORY_PATH = os.path.join("data", "trmnl.json")

def get_daily_meaning_wrappers(date_str: str = "") -> List[Dict]:
    """
    Get four random meaning wrappers with their words, seeded by date.

    Args:
        db_path: Path to SQLite database
        date_str: Date string in YYYY-MM-DD format (defaults to today)

    Returns:
        List of four entries with meaning wrappers and their words:
        [{
            'meaning_wrapper': html_str,
            'representation': html_str,
            'word_id': int
        }, ...]
    """
    # Use current date if none provided
    if date_str == "":
        date_str = datetime.now().strftime("%Y-%m-%d")

    # Connect to database
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    try:
        # Create consistent numeric seed from date string
        date_seed = int(hashlib.sha256(date_str.encode()).hexdigest(), 16) % 2**31

        # Query to get four random meaning wrappers with their words
        query = """
        WITH daily_words AS (
            SELECT DISTINCT word_id
            FROM meaning_wrappers
            ORDER BY SUBSTR(word_id * ?, 1, 15)
            LIMIT 4
        ),
        selected_wrappers AS (
            SELECT 
                mw.id,
                mw.wrapper_html,
                mw.word_id,
                w.representation_html,
                ROW_NUMBER() OVER (PARTITION BY mw.word_id ORDER BY SUBSTR(mw.id * ?, 1, 15)) as rn
            FROM meaning_wrappers mw
            JOIN words w ON mw.word_id = w.id
            JOIN daily_words dw ON mw.word_id = dw.word_id
        )
        SELECT 
            wrapper_html as meaning_wrapper,
            representation_html as representation,
            word_id
        FROM selected_wrappers
        WHERE rn = 1  -- Take just one wrapper per word
        ORDER BY word_id
        """

        cursor = conn.cursor()
        cursor.execute(query, (date_seed, date_seed))
        rows = cursor.fetchall()

        return [dict(row) for row in rows]

    finally:
        conn.close()

def compress_text(text):
    """
    Compresses a text string (including non-ASCII characters) and returns a compressed string.

    Args:
        text (str): The input text to compress

    Returns:
        str: The compressed text as a base64-encoded string
    """
    # Convert text to bytes (UTF-8 encoding handles all Unicode characters)
    text_bytes = text.encode('utf-8')

    # Compress the bytes using zlib
    compressed_bytes = zlib.compress(text_bytes, level=zlib.Z_BEST_COMPRESSION)

    # Encode the compressed bytes as base64 for safe string representation
    compressed_text = base64.b64encode(compressed_bytes).decode('ascii')

    return compressed_text

def get_4_daily_words() -> List[str]:
    combined = []
    words = get_daily_meaning_wrappers()
    for i, word in enumerate(words, 1):
        rawHTML = word["representation"] + word["meaning_wrapper"]
        combined.append(rawHTML)
    return combined

def generate_payload_to_trmnl():
    payload = {}
    words = get_4_daily_words()
    rawJSON = json.dumps(words)
    compressedJSON = compress_text(rawJSON)

    payload['merge_variables'] = { "compressed": compressedJSON }
    # print(len(json.dumps(payload)))
    # print(payload)
    return payload

def send_to_trmnl():
    trnml_stat= {}
    today_str = datetime.now().strftime("%Y-%m-%d")

    try:
        TRMNL_API_KEY = os.environ['TRMNL_PLUGIN_API_KEY']
    except KeyError:
        logger.error("[send_to_trmnl] TRMNL_PLUGIN_API_KEY not set in environment variables.")
        return

    if TRMNL_API_KEY is None:
        return

    try:
        with open(TRNML_HISTORY_PATH, 'r') as file:
            trnml_stat = json.load(file)
    except FileNotFoundError:
        pass
    except json.JSONDecodeError:
        logger.error(f"[send_to_trmnl] invalid JSON file '{TRNML_HISTORY_PATH}'")
    except Exception as e:
        logger.error(f"[send_to_trmnl] {traceback.format_exc()}")

    if "last_datatime" in trnml_stat:
        if trnml_stat["last_datatime"] == today_str:
            logger.info("[send_to_trmnl] PASS")
            return

    payload = generate_payload_to_trmnl()

    url = "https://usetrmnl.com/api/custom_plugins/" + TRMNL_API_KEY
    response = requests.post(url, json=payload)
    logger.info(response)
    if response.status_code == 200:
        with open(TRNML_HISTORY_PATH, "w") as fp:
            json.dump({
                "last_datatime": today_str,
            }, fp, indent=2)
    else:
        logger.error(response.text)

async def updater():
    while True:
        try:
            send_to_trmnl()
        except Exception as e:
            logger.error(f"[updater] {traceback.format_exc()}")
        await asyncio.sleep(3600)

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(updater())
    yield  # Application runs here
    task.cancel()

app = FastAPI(lifespan=lifespan)

@app.middleware("http")
async def strip_path_prefix(request: Request, call_next):
    prefix = "/japanese"
    prefix_len = len(prefix)
    if request.url.path.startswith(prefix):
        request.scope["path"] = request.scope["path"][prefix_len:]

    response = await call_next(request)
    return response

# Disable detailed validation errors in production
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"detail": "Invalid request parameters"},  # Generic error
    )

@app.get("/favicon.ico")
async def favicon():
    return FileResponse("www/favicon.png", media_type="image/x-icon")


@app.get("/")
@app.get("/index.html")
async def static_file(request: Request):
    path = request.url.path
    if path == '/':
        path = '/index.html'

    return FileResponse(f'www{path}')


@app.get("/api/words")
async def get_daily_words():
    return JSONResponse(generate_payload_to_trmnl())

if __name__ == '__main__':
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    import uvicorn
    uvicorn.run("main:app",
                port=80,
                host='0.0.0.0',
                reload=True,
                log_level='debug',
                workers=1)

