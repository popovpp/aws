# lambda_function.py
import os
import hashlib
import time
import logging
from datetime import datetime
import boto3
import requests
from bs4 import BeautifulSoup
from pymongo import MongoClient
from botocore.exceptions import ClientError

LOG = logging.getLogger()
LOG.setLevel(logging.INFO)

# Environment variables / Parameter Store keys
SSM_MONGO_PARAM = os.environ.get("SSM_MONGO_PARAM", "/popow/mongo_uri")
SSM_TELEGRAM_PARAM = os.environ.get("SSM_TELEGRAM_PARAM", "/popow/telegram_token")
TELEGRAM_CHAT_ID_PARAM = os.environ.get("SSM_TELEGRAM_CHAT_ID_PARAM", "/popow/telegram_chat_id")
S3_BUCKET = os.environ.get("S3_BUCKET", "popow-lyrics-bucket")
AUTHOR_PAGE = os.environ.get("AUTHOR_PAGE", "http://samlib.ru/editors/p/popow_p_p/")

# clients
ssm = boto3.client("ssm")
s3 = boto3.client("s3")

def get_ssm_param(name):
    resp = ssm.get_parameter(Name=name, WithDecryption=True)
    return resp['Parameter']['Value']

def make_id_from_url(url):
    # deterministic id from url
    return hashlib.sha1(url.encode('utf-8')).hexdigest()

def fetch_page(url):
    LOG.info("Fetching %s", url)
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    return resp.text

def parse_author_index(html):
    soup = BeautifulSoup(html, "html.parser")
    # This site is old-style. We must find links to works.
    # Try to find all <a> tags under main content; filter hrefs containing the author's folder.
    links = []
    for a in soup.find_all("a", href=True):
        href = a['href']
        # Convert relative to absolute if needed
        if href.startswith("http://") or href.startswith("https://"):
            url = href
        else:
            url = requests.compat.urljoin(AUTHOR_PAGE, href)
        title = a.get_text(strip=True)
        if title:
            # Heuristic: skip navigation links that are not works (skip if link text is like "editors" etc.)
            # Keep links that look like title lines (not images)
            links.append((title, url))
    # deduplicate preserving order
    seen = set()
    out = []
    for title, url in links:
        if url not in seen:
            out.append({"title": title, "url": url})
            seen.add(url)
    return out

def extract_text_from_work(html):
    soup = BeautifulSoup(html, "html.parser")
    # Heuristic extraction: many samlib pages have text in <div> or directly in body between <p>.
    # We'll gather significant <p> text.
    paragraphs = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
    if not paragraphs:
        # fallback: body text
        text = soup.get_text("\n", strip=True)
    else:
        text = "\n\n".join(paragraphs)
    # Optional: basic cleanup
    text = text.replace("\xa0", " ")
    return text.strip()

def save_txt_to_s3(text, s3_key):
    s3.put_object(Bucket=S3_BUCKET, Key=s3_key, Body=text.encode("utf-8"))
    # return a public or presigned URL depending on bucket policy
    return s3_key

def post_to_telegram(token, chat_id, message):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode":"HTML"}
    resp = requests.post(url, data=payload, timeout=15)
    resp.raise_for_status()
    return resp.json()

def lambda_handler(event, context):
    # load secrets
    mongo_uri = get_ssm_param(SSM_MONGO_PARAM)
    telegram_token = get_ssm_param(SSM_TELEGRAM_PARAM)
    chat_id = get_ssm_param(TELEGRAM_CHAT_ID_PARAM)

    # connect mongo
    mongo = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
    db = mongo.get_database()  # default from URI
    coll = db["works"]

    # fetch index
    idx_html = fetch_page(AUTHOR_PAGE)
    works = parse_author_index(idx_html)
    LOG.info("Found %d candidate links", len(works))

    new_count = 0
    for item in works:
        title = item["title"]
        url = item["url"]
        source_id = make_id_from_url(url)
        if coll.find_one({"source_id": source_id}):
            LOG.info("Already have %s", title)
            continue

        # fetch work page
        try:
            html = fetch_page(url)
            text = extract_text_from_work(html)
            if not text or len(text) < 20:
                LOG.warning("Empty or very short text for %s (%s)", title, url)
                continue
            # prepare s3 key
            safe_title = "".join(c if c.isalnum() else "_" for c in title)[:100]
            timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
            s3_key = f"popow/{safe_title}_{timestamp}.txt"

            save_txt_to_s3(text, s3_key)
            excerpt = text[:500]

            doc = {
                "source": "samlib",
                "author": "Popow P. P.",
                "title": title,
                "url": url,
                "source_id": source_id,
                "s3_key": s3_key,
                "excerpt": excerpt,
                "scraped_at": datetime.utcnow(),
                "published": False
            }
            coll.insert_one(doc)
            new_count += 1

            # Publish to Telegram: send excerpt + link to S3 (if bucket public or generate presigned link)
            # If bucket is private, generate presigned URL:
            presigned = s3.generate_presigned_url('get_object', Params={'Bucket': S3_BUCKET, 'Key': s3_key}, ExpiresIn=86400)
            message = f"<b>{title}</b>\n\n{excerpt[:800]}...\n\nЧитать: {presigned}"
            post_to_telegram(telegram_token, chat_id, message)

            # update doc as published
            coll.update_one({"source_id": source_id}, {"$set": {"published": True, "published_at": datetime.utcnow()}})
            LOG.info("Processed and published %s", title)
        except Exception as e:
            LOG.exception("Error processing %s: %s", url, e)
            continue

    return {"status": "done", "new": new_count}
