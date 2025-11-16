from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
from bs4 import BeautifulSoup
import logging
import time
import random
import re
import json

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15',
]

def get_headers():
    return {
        'User-Agent': random.choice(USER_AGENTS),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Connection': 'keep-alive'
    }


# AMAZON SELECTORS
AMAZON_SELECTORS = {
    'title': ['#productTitle'],
    'price': [
        '.a-price .a-offscreen',
        '#corePriceDisplay_desktop_feature_div .a-offscreen',
        '#priceblock_ourprice',
        '#priceblock_dealprice',
        '.apexPriceToPay .a-offscreen',
        '.a-price-whole'
    ],
    'description': [
        '#feature-bullets',
        '#featurebullets_feature_div',
        '.a-unordered-list.a-vertical',
        '#productDescription'
    ]
}

# FLIPKART SELECTORS
FLIPKART_SELECTORS = {
    'title': ['h1.yhB1nd', '.B_NuCI', 'span.VU-ZEz'],
    'price': ['div._30jeq3', 'div[class*="Nx9bqj"]', 'div._16Jk6d'],
    'description': ['div._1mXcCf', 'ul._1xgFaf']
}

# ---------------------------
# AMAZON SCRAPER
# ---------------------------
def extract_amazon_features(soup):
    features = {}

    # TITLE
    title = soup.select_one("#productTitle")
    if title:
        features["Product"] = title.get_text(strip=True)

    # 1) JSON-LD structured description
    if "Description" not in features:
        for script in soup.find_all("script", {"type": "application/ld+json"}):
            try:
                data = json.loads(script.string)

                if isinstance(data, dict) and data.get("@type") == "Product":
                    if data.get("description"):
                        features["Description"] = data["description"].strip()

                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get("@type") == "Product":
                            if item.get("description"):
                                features["Description"] = item["description"].strip()
                            break
            except:
                pass

    # 2) A+ CONTENT (MOST IMPORTANT)
    if "Description" not in features:
        aplus_blocks = soup.select(
            "#aplus, #aplus_feature_div, #aplus_content, .aplus, .aplus-module, .aplus-v2"
        )

        collected = []
        for block in aplus_blocks:
            parts = block.find_all(["p", "span", "li"])
            for p in parts:
                text = p.get_text(" ", strip=True)
                if len(text) > 40:
                    collected.append(text)

        if collected:
            features["Description"] = " ".join(collected)[:600]

    # 3) Old description block
    if "Description" not in features:
        desc = soup.find("div", id="productDescription")
        if desc:
            txt = desc.get_text(" ", strip=True)
            if len(txt) > 20:
                features["Description"] = txt[:600]

    if "Description" not in features:
        features["Description"] = "Description not available"

    # PRICE
    for selector in AMAZON_SELECTORS['price']:
        for tag in soup.select(selector):
            price = tag.get_text(strip=True)
            if any(c in price for c in ["₹", "$", "£"]):
                features["Price"] = price
                break
        if "Price" in features:
            break

    if "Price" not in features:
        features["Price"] = "Price not found"

    # FEATURES
    feature_list = []
    for selector in AMAZON_SELECTORS['description']:
        block = soup.select_one(selector)
        if block:
            items = [li.get_text(" ", strip=True) for li in block.select("li")]
            feature_list.extend(items)
            break

    # Add A+ details as additional features
    for li in soup.select("#aplus li, .aplus li, .aplus-module li, .aplus-v2 li"):
        text = li.get_text(" ", strip=True)
        if len(text) > 10:
            feature_list.append(text)

    if feature_list:
        features["Features"] = feature_list[:10]
    else:
        features["Features"] = ["No detailed features available"]

    return features


# ---------------------------
# FLIPKART SCRAPER
# ---------------------------
def extract_flipkart_features(soup):
    features = {}

    # -----------------------
    # TITLE
    # -----------------------
    title_tags = [
        "h1.yhB1nd", ".B_NuCI", "span.VU-ZEz"
    ]
    for sel in title_tags:
        tag = soup.select_one(sel)
        if tag:
            features["Product"] = tag.get_text(strip=True)
            break

    # -----------------------
    # PRICE
    # -----------------------
    price_tags = [
        "div._30jeq3", 
        "div[class*='Nx9bqj']", 
        "div._16Jk6d"
    ]
    for sel in price_tags:
        for el in soup.select(sel):
            txt = el.get_text(strip=True)
            if "₹" in txt:
                features["Price"] = txt
                break
        if "Price" in features:
            break

    if "Price" not in features:
        features["Price"] = "Price not found"

    # -----------------------
    # DESCRIPTION & FEATURES
    # -----------------------
    desc_candidates = []

    # 1) TV HIGHLIGHTS (ul bullets)
    bullets = soup.select("div._2418kt ul li")
    for li in bullets:
        text = li.get_text(" ", strip=True)
        if len(text) > 10:
            desc_candidates.append(text)

    # 2) Highlights section (short description)
    highlight_block = soup.select_one("div._2c7YLP")
    if highlight_block:
        for li in highlight_block.find_all("li"):
            text = li.get_text(" ", strip=True)
            if len(text) > 10:
                desc_candidates.append(text)

    # 3) Long text description paragraphs
    long_desc_blocks = soup.select("div._1mHr1S p, div._3nMrqj p")
    for p in long_desc_blocks:
        text = p.get_text(" ", strip=True)
        if len(text) > 40:
            desc_candidates.append(text)

    # 4) Specifications table
    for row in soup.select("table._14cfVK tr"):
        cols = row.find_all("td")
        if len(cols) == 2:
            key = cols[0].get_text(strip=True)
            val = cols[1].get_text(strip=True)
            desc_candidates.append(f"{key}: {val}")

    # -----------------------
    # APPLY DESCRIPTION
    # -----------------------
    if desc_candidates:
        features["Description"] = " ".join(desc_candidates)[:800]
    else:
        features["Description"] = "Description not available"

    # -----------------------
    # FEATURES LIST (Top 10)
    # -----------------------
    if desc_candidates:
        features["Features"] = desc_candidates[:10]
    else:
        features["Features"] = ["No detailed features available"]

    return features



# ---------------------------
# GENERIC SCRAPER
# ---------------------------
def extract_generic_features(soup):
    features = {}

    title = soup.find("h1") or soup.find("title")
    features["Product"] = title.get_text(strip=True) if title else "Unknown Product"

    text = soup.get_text()
    m = re.search(r"(₹|\$|£|Rs\.?)\s?[\d,]+", text)
    features["Price"] = m.group(0) if m else "Price not found"

    meta = soup.find("meta", attrs={"name": "description"})
    features["Description"] = meta["content"][:400] if meta else "Description not available"

    features["Features"] = ["No detailed features available"]
    return features


# ---------------------------
# MAIN SCRAPER
# ---------------------------
def scrape_features(url):
    try:
        time.sleep(random.uniform(0.5, 1.3))
        r = requests.get(url, headers=get_headers(), timeout=20)
        r.raise_for_status()

        soup = BeautifulSoup(r.content, "html.parser")
        url_l = url.lower()

        if "amazon." in url_l:
            return extract_amazon_features(soup)

        if "flipkart." in url_l:
            return extract_flipkart_features(soup)

        return extract_generic_features(soup)

    except Exception as e:
        return {"error": f"Failed to scrape: {str(e)}"}


# ---------------------------
# NORMALIZE DATA
# ---------------------------
def normalize_features(raw):
    return {
        "Product": raw.get("Product", "Unnamed Product"),
        "Price": raw.get("Price", "Price not found"),
        "Description": raw.get("Description", "Description not available"),
        "Features": raw.get("Features", ["No detailed features available"])
    }


# ---------------------------
# API ROUTES
# ---------------------------
@app.route('/compare', methods=['POST'])
def compare():
    data = request.get_json()
    url1, url2 = data.get("url1"), data.get("url2")

    r1 = scrape_features(url1)
    r2 = scrape_features(url2)

    if "error" in r1 or "error" in r2:
        return jsonify({"error": {"url1": r1.get("error"), "url2": r2.get("error")}}), 400

    return jsonify({
        "data1": normalize_features(r1),
        "data2": normalize_features(r2)
    })


@app.route("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    print("Server running on http://127.0.0.1:5000/")
    app.run(debug=True, host="0.0.0.0", port=5000)
