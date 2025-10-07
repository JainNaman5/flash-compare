from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
from bs4 import BeautifulSoup
import logging
import time
import random

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Rotate user agents to avoid detection
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
        'Accept-Encoding': 'gzip, deflate, br',
        'DNT': '1',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Cache-Control': 'max-age=0',
    }

PRICE_SELECTORS = ['.price', '.cost', '[class*="price"]', '[id*="price"]']
DESC_SELECTORS = ['.description', '.product-description', '[class*="description"]']

# Updated Amazon selectors (as of 2025)
AMAZON_SELECTORS = {
    'price': [
        '.a-price .a-offscreen',
        '#corePriceDisplay_desktop_feature_div .a-offscreen',
        '#priceblock_ourprice',
        '#priceblock_dealprice',
        '.a-price-whole',
        'span.a-color-price',
        '#price_inside_buybox',
        '.apexPriceToPay .a-offscreen'
    ],
    'title': ['#productTitle', '#title', 'h1.product-title'],
    'description': [
        '#feature-bullets',
        '#featurebullets_feature_div',
        '.a-unordered-list.a-vertical',
        '#productDescription'
    ]
}

# Updated Flipkart selectors
FLIPKART_SELECTORS = {
    'price': [
        'div[class*="Nx9bqj"]',  # Updated price class
        'div[class*="_30jeq3"]',
        'div[class*="_3I9_wc"]',
        '._30jeq3._16Jk6d',
        'div._16Jk6d'
    ],
    'title': [
        'span.VU-ZEz',
        'h1.yhB1nd',
        '.B_NuCI',
        'h1 span'
    ],
    'description': [
        'div._1mXcCf',
        'div._1AN87F',
        'ul._1xgFaf',
        'div[class*="mXcCf"]'
    ]
}

def is_valid_url(url):
    return url.startswith(('http://', 'https://'))

def extract_text(soup, selectors, truncate=200):
    for selector in selectors:
        try:
            element = soup.select_one(selector)
            if element:
                text = element.get_text(strip=True)
                return text[:truncate] + "..." if len(text) > truncate else text
        except Exception as e:
            logger.debug(f"Error with selector {selector}: {e}")
            continue
    return None

def extract_amazon_features(soup, url):
    features = {}
    
    # Extract title
    for selector in AMAZON_SELECTORS['title']:
        title = soup.select_one(selector)
        if title:
            features['Product'] = title.get_text(strip=True)
            break
    
    # Extract price - try multiple methods
    price_found = False
    for selector in AMAZON_SELECTORS['price']:
        elements = soup.select(selector)
        for el in elements:
            price_text = el.get_text(strip=True)
            if price_text and ('₹' in price_text or '$' in price_text or '£' in price_text):
                features['Price'] = price_text
                price_found = True
                break
        if price_found:
            break
    
    # If still no price, try broader search
    if not price_found:
        price_elements = soup.find_all(string=lambda text: text and ('₹' in text or '$' in text) and any(c.isdigit() for c in text))
        for elem in price_elements[:5]:
            text = elem.strip()
            if len(text) < 50 and any(c.isdigit() for c in text):
                features['Price'] = text
                break

    # Extract features/description
    feature_list = []
    for selector in AMAZON_SELECTORS['description']:
        desc = soup.select_one(selector)
        if desc:
            items = [li.get_text(strip=True) for li in desc.select('li')]
            if items:
                feature_list.extend(items)
                break
    
    if feature_list:
        features['Features'] = feature_list[:10]  # Limit to 10 features
    
    # If no features found, try to get product description
    if not feature_list:
        prod_desc = soup.find('div', {'id': 'productDescription'})
        if prod_desc:
            desc_text = prod_desc.get_text(strip=True)
            if desc_text:
                features['Description'] = desc_text[:500] + "..." if len(desc_text) > 500 else desc_text

    logger.info(f"Amazon features extracted: {list(features.keys())}")
    return features

def extract_flipkart_features(soup, url):
    features = {}
    
    # Extract title
    for selector in FLIPKART_SELECTORS['title']:
        title = soup.select_one(selector)
        if title:
            features['Product'] = title.get_text(strip=True)
            break
    
    # Extract price
    for selector in FLIPKART_SELECTORS['price']:
        elements = soup.select(selector)
        for el in elements:
            price_text = el.get_text(strip=True)
            if price_text and '₹' in price_text:
                features['Price'] = price_text
                break
        if 'Price' in features:
            break
    
    # Broader price search if needed
    if 'Price' not in features:
        price_elements = soup.find_all(string=lambda text: text and '₹' in text and any(c.isdigit() for c in text))
        for elem in price_elements[:5]:
            text = elem.strip()
            if len(text) < 50:
                features['Price'] = text
                break

    # Extract features
    feature_list = []
    for selector in FLIPKART_SELECTORS['description']:
        desc = soup.select_one(selector)
        if desc:
            if desc.name == 'ul' or desc.find('ul'):
                ul = desc if desc.name == 'ul' else desc.find('ul')
                items = [li.get_text(strip=True) for li in ul.find_all('li')]
                if items:
                    feature_list.extend(items)
            else:
                text = desc.get_text(strip=True)
                if text:
                    features['Description'] = text[:500] + "..." if len(text) > 500 else text
            break
    
    if feature_list:
        features['Features'] = feature_list[:10]

    logger.info(f"Flipkart features extracted: {list(features.keys())}")
    return features

def scrape_features(url):
    try:
        logger.info(f"Scraping: {url}")
        
        # Add small random delay to appear more human-like
        time.sleep(random.uniform(0.5, 1.5))
        
        session = requests.Session()
        response = session.get(url, headers=get_headers(), timeout=20, allow_redirects=True)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')

        features = {}
        
        if "amazon." in url.lower():
            features = extract_amazon_features(soup, url)
            if not features.get('Product'):
                features['Product'] = 'Amazon Product'
        elif "flipkart." in url.lower():
            features = extract_flipkart_features(soup, url)
            if not features.get('Product'):
                features['Product'] = 'Flipkart Product'
        else:
            # Generic scraping
            title = soup.find('h1')
            if title:
                features['Product'] = title.get_text(strip=True)

            price = extract_text(soup, PRICE_SELECTORS)
            if price:
                features['Price'] = price

            description = extract_text(soup, DESC_SELECTORS, truncate=300)
            if not description:
                meta = soup.find('meta', attrs={'name': 'description'})
                if meta:
                    content = meta.get('content', '')
                    description = content[:300] + "..." if len(content) > 300 else content
            if description:
                features['Description'] = description

            # Try to extract feature lists
            if not features.get('Features'):
                import bs4
                for ul in soup.find_all(['ul', 'ol'])[:5]:
                    if isinstance(ul, bs4.element.Tag):
                        items = [li.get_text(strip=True) for li in ul.find_all('li')[:8]]
                        # Filter out navigation/menu items
                        filtered_items = [item for item in items if len(item) > 10 and len(item) < 200]
                        if len(filtered_items) >= 2:
                            features['Features'] = filtered_items
                            break

        if not features or len(features) == 0:
            page_title = soup.find('title')
            features = {
                'Product': page_title.get_text(strip=True) if page_title else 'Unknown Product',
                'Description': 'Could not extract detailed information. The website may be using JavaScript to load content or has anti-scraping protection.',
            }

        logger.info(f"Successfully scraped {len(features)} features from {url}")
        return features

    except requests.Timeout:
        logger.error(f"Timeout error for {url}")
        return {'error': f'Request timeout. The website took too long to respond.'}
    except requests.HTTPError as e:
        logger.error(f"HTTP error for {url}: {e}")
        if e.response.status_code == 403:
            return {'error': 'Access denied by website (403). The site is blocking automated requests.'}
        elif e.response.status_code == 503:
            return {'error': 'Service unavailable (503). The website is temporarily down or blocking requests.'}
        return {'error': f'HTTP error {e.response.status_code}: {str(e)}'}
    except requests.RequestException as e:
        logger.error(f"Request error for {url}: {e}")
        return {'error': f'Failed to fetch the page. Error: {str(e)[:100]}'}
    except Exception as e:
        logger.error(f"Scraping error for {url}: {e}")
        return {'error': f'Error processing the page. This website may require special handling.'}

def normalize_features(raw_data):
    """Normalize scraped data into consistent format"""
    return {
        'Product': raw_data.get('Product') or raw_data.get('Title') or 'Unnamed Product',
        'Description': raw_data.get('Description') or 'No description available',
        'Features': (
            raw_data.get('Features') if isinstance(raw_data.get('Features'), list)
            else [raw_data.get('Features')] if raw_data.get('Features')
            else ['No detailed features available']
        ),
        'Price': raw_data.get('Price') or 'Price not found'
    }

@app.route('/compare', methods=['POST'])
def compare():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Missing JSON payload'}), 400

    url1, url2 = data.get('url1'), data.get('url2')
    if not (url1 and url2):
        return jsonify({'error': 'Both URLs are required'}), 400
    if not (is_valid_url(url1) and is_valid_url(url2)):
        return jsonify({'error': 'URLs must start with http:// or https://'}), 400

    logger.info(f"Comparing: {url1} vs {url2}")
    
    result1 = scrape_features(url1)
    result2 = scrape_features(url2)

    # Check for errors
    errors = {}
    if 'error' in result1:
        errors['url1'] = result1['error']
    if 'error' in result2:
        errors['url2'] = result2['error']
    if errors:
        return jsonify({'error': errors}), 400

    return jsonify({
        'data1': normalize_features(result1),
        'data2': normalize_features(result2)
    })

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({'status': 'healthy', 'message': 'API is running'})

@app.route('/', methods=['GET'])
def home():
    return jsonify({
        'name': 'Universal Feature Comparator API',
        'version': '1.2.0',
        'endpoints': {
            '/compare': 'POST - Compare features from two URLs',
            '/health': 'GET - Health check'
        },
        'note': 'Some websites (Amazon, Flipkart) use anti-bot protection and may not always work.'
    })

# if __name__ == '__main__':
#     print("=" * 50)
#     print("Starting Flask server...")
#     print("API available at: http://127.0.0.1:5000/")
#     print("Health check: http://127.0.0.1:5000/health")
#     print("=" * 50)
#     app.run(debug=True, host='0.0.0.0', port=5000)



# from flask import Flask, request, jsonify
# from flask_cors import CORS
# import requests
# from bs4 import BeautifulSoup
# import logging
# import time
# import random
# import json # <-- ADDED FOR JSON-LD PARSING

# app = Flask(__name__)
# # Allow all origins for local testing
# CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

# logging.basicConfig(level=logging.INFO)
# logger = logging.getLogger(__name__)

# # Rotate user agents to avoid detection
# USER_AGENTS = [
#     'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
#     'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
#     'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
#     'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15',
# ]

# def get_headers():
#     """Returns a dictionary with rotating headers."""
#     return {
#         'User-Agent': random.choice(USER_AGENTS),
#         'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
#         'Accept-Language': 'en-US,en;q=0.9',
#         'DNT': '1',
#         'Connection': 'keep-alive',
#         'Upgrade-Insecure-Requests': '1',
#     }

# PRICE_SELECTORS = ['.price', '.cost', '[class*="price"]', '[id*="price"]']
# DESC_SELECTORS = ['.description', '.product-description', '[class*="description"]']

# # Updated Amazon selectors (as of 2025)
# AMAZON_SELECTORS = {
#     'price': [
#         '.a-price .a-offscreen',
#         '#corePriceDisplay_desktop_feature_div .a-offscreen',
#         '.apexPriceToPay .a-offscreen'
#     ],
#     'title': ['#productTitle'],
#     'description': ['#feature-bullets', '#productDescription']
# }

# # Updated Flipkart selectors
# FLIPKART_SELECTORS = {
#     'price': [
#         'div[class*="Nx9bqj"]',  # Updated price class
#         'div[class*="_30jeq3"]'
#     ],
#     'title': [
#         'h1.yhB1nd',
#         '.B_NuCI'
#     ],
#     'description': [
#         'div._1mXcCf',
#         'ul._1xgFaf'
#     ]
# }

# def is_valid_url(url):
#     """Checks if a URL starts with http or https."""
#     return url.startswith(('http://', 'https://'))

# def extract_text(soup, selectors, truncate=200):
#     """Generic extraction function using CSS selectors."""
#     for selector in selectors:
#         try:
#             element = soup.select_one(selector)
#             if element:
#                 text = element.get_text(strip=True)
#                 return text[:truncate] + "..." if len(text) > truncate else text
#         except Exception:
#             continue
#     return None

# def extract_from_json_ld(soup):
#     """Extracts product features from JSON-LD schema markup for better reliability."""
#     features = {}
    
#     for script in soup.find_all('script', {'type': 'application/ld+json'}):
#         try:
#             data = json.loads(script.string)
            
#             # Handle list or single object structure
#             if isinstance(data, list):
#                 product_data = next((item for item in data if item.get('@type') == 'Product'), None)
#             else:
#                 product_data = data if data.get('@type') == 'Product' else None
                
#             if product_data:
#                 # Extract Product Name
#                 if 'name' in product_data:
#                     features['Product'] = product_data['name']
                
#                 # Extract Price from 'offers'
#                 if 'offers' in product_data:
#                     offers = product_data['offers']
#                     offer = offers[0] if isinstance(offers, list) else offers
                        
#                     price = str(offer.get('price', ''))
#                     currency = offer.get('priceCurrency', '')
#                     if price and currency:
#                         features['Price'] = f"{currency} {price}"

#                 # Extract Description
#                 if 'description' in product_data:
#                     features['Description'] = product_data['description']
                
#                 # Prioritize JSON-LD if we found core data
#                 if features.get('Product') and features.get('Price'):
#                     return features 
                
#         except json.JSONDecodeError:
#             logger.debug("Skipping invalid JSON-LD script.")
#             continue
#         except Exception as e:
#             logger.error(f"Error processing JSON-LD: {e}")
#             continue
            
#     return features


# def extract_amazon_features(soup, current_features):
#     """Extracts Amazon specific features, prioritizing existing data."""
#     features = current_features.copy()
    
#     # Extract title
#     if 'Product' not in features:
#         for selector in AMAZON_SELECTORS['title']:
#             title = soup.select_one(selector)
#             if title:
#                 features['Product'] = title.get_text(strip=True)
#                 break
    
#     # Extract price
#     if 'Price' not in features:
#         price_found = False
#         for selector in AMAZON_SELECTORS['price']:
#             elements = soup.select(selector)
#             for el in elements:
#                 price_text = el.get_text(strip=True)
#                 if price_text and ('₹' in price_text or '$' in price_text or '£' in price_text):
#                     features['Price'] = price_text
#                     price_found = True
#                     break
#             if price_found:
#                 break
    
#     # Extract features/description list
#     feature_list = []
#     for selector in AMAZON_SELECTORS['description']:
#         desc = soup.select_one(selector)
#         if desc:
#             items = [li.get_text(strip=True) for li in desc.select('li')]
#             if items:
#                 feature_list.extend(items)
#                 break
    
#     if feature_list:
#         features['Features'] = feature_list[:10]
    
#     # If no list features, try for a general description
#     if 'Description' not in features:
#         prod_desc = soup.find('div', {'id': 'productDescription'})
#         if prod_desc:
#             desc_text = prod_desc.get_text(strip=True)
#             if desc_text:
#                 features['Description'] = desc_text[:500] + "..." if len(desc_text) > 500 else desc_text

#     return features

# def extract_flipkart_features(soup, current_features):
#     """Extracts Flipkart specific features, prioritizing existing data."""
#     features = current_features.copy()
    
#     # Extract title
#     if 'Product' not in features:
#         for selector in FLIPKART_SELECTORS['title']:
#             title = soup.select_one(selector)
#             if title:
#                 features['Product'] = title.get_text(strip=True)
#                 break
    
#     # Extract price
#     if 'Price' not in features:
#         for selector in FLIPKART_SELECTORS['price']:
#             elements = soup.select(selector)
#             for el in elements:
#                 price_text = el.get_text(strip=True)
#                 if price_text and '₹' in price_text:
#                     features['Price'] = price_text
#                     break
#             if 'Price' in features:
#                 break
    
#     # Extract features/description
#     feature_list = []
#     for selector in FLIPKART_SELECTORS['description']:
#         desc = soup.select_one(selector)
#         if desc:
#             if desc.name == 'ul' or desc.find('ul'):
#                 ul = desc if desc.name == 'ul' else desc.find('ul')
#                 items = [li.get_text(strip=True) for li in ul.find_all('li')]
#                 if items:
#                     feature_list.extend(items)
            
#             if 'Description' not in features:
#                 # Try general description if list extraction failed or was incomplete
#                 text = desc.get_text(strip=True)
#                 if text:
#                     features['Description'] = text[:500] + "..." if len(text) > 500 else text
            
#             break
    
#     if feature_list:
#         features['Features'] = feature_list[:10]

#     return features

# def scrape_features(url):
#     """Performs the HTTP request and runs scraping routines (JSON-LD first, then CSS)."""
#     try:
#         logger.info(f"Scraping: {url}")
        
#         # Add small random delay to appear more human-like
#         time.sleep(random.uniform(0.5, 1.5))
        
#         session = requests.Session()
#         response = session.get(url, headers=get_headers(), timeout=20, allow_redirects=True)
#         response.raise_for_status()
        
#         soup = BeautifulSoup(response.content, 'html.parser')

#         features = {}
        
#         # 1. Attempt to extract features from structured JSON-LD data
#         features = extract_from_json_ld(soup)
        
#         # 2. Fallback to site-specific or generic CSS selectors
#         if "amazon." in url.lower():
#             features = extract_amazon_features(soup, features)
#             if not features.get('Product'): features['Product'] = 'Amazon Product'
            
#         elif "flipkart." in url.lower():
#             features = extract_flipkart_features(soup, features)
#             if not features.get('Product'): features['Product'] = 'Flipkart Product'
            
#         else:
#             # Generic scraping (only run if JSON-LD or previous steps failed)
#             if not features.get('Product'):
#                 title = soup.find('h1')
#                 if title:
#                     features['Product'] = title.get_text(strip=True)

#             if not features.get('Price'):
#                 price = extract_text(soup, PRICE_SELECTORS)
#                 if price:
#                     features['Price'] = price

#             if not features.get('Description'):
#                 description = extract_text(soup, DESC_SELECTORS, truncate=300)
#                 if not description:
#                     meta = soup.find('meta', attrs={'name': 'description'})
#                     if meta:
#                         content = meta.get('content', '')
#                         description = content[:300] + "..." if len(content) > 300 else content
#                 if description:
#                     features['Description'] = description

#             # Try to extract feature lists (generic)
#             if not features.get('Features'):
#                 import bs4
#                 for ul in soup.find_all(['ul', 'ol'])[:5]:
#                     if isinstance(ul, bs4.element.Tag):
#                         items = [li.get_text(strip=True) for li in ul.find_all('li')[:8]]
#                         filtered_items = [item for item in items if len(item) > 10 and len(item) < 200]
#                         if len(filtered_items) >= 2:
#                             features['Features'] = filtered_items
#                             break

#         # 3. Final Check (if everything failed)
#         if not features.get('Product'):
#             page_title = soup.find('title')
#             features = {
#                 'Product': page_title.get_text(strip=True) if page_title else 'Unknown Product',
#                 'Description': 'Could not extract detailed information. The website may be using JavaScript to load content, has anti-scraping protection, or requires a headless browser.',
#             }

#         logger.info(f"Successfully scraped {len(features)} features from {url}")
#         return features

#     except requests.Timeout:
#         logger.error(f"Timeout error for {url}")
#         return {'error': f'Request timeout. The website took too long to respond.'}
#     except requests.HTTPError as e:
#         logger.error(f"HTTP error for {url}: {e}")
#         if e.response.status_code == 403:
#             return {'error': 'Access denied by website (403). The site is blocking automated requests (anti-bot protection).'}
#         elif e.response.status_code == 503:
#             return {'error': 'Service unavailable (503). The website is temporarily down or blocking requests.'}
#         return {'error': f'HTTP error {e.response.status_code}: {str(e)}'}
#     except requests.RequestException as e:
#         logger.error(f"Request error for {url}: {e}")
#         return {'error': f'Failed to fetch the page. Error: {str(e)[:100]}. Check server internet connection.'}
#     except Exception as e:
#         logger.error(f"Scraping error for {url}: {e}")
#         return {'error': f'Unexpected error processing the page. Error: {str(e)}'}

# def normalize_features(raw_data):
#     """Normalize scraped data into consistent format"""
#     return {
#         'Product': raw_data.get('Product') or raw_data.get('Title') or 'Unnamed Product',
#         'Description': raw_data.get('Description') or 'No description available',
#         'Features': (
#             raw_data.get('Features') if isinstance(raw_data.get('Features'), list)
#             else [raw_data.get('Features')] if raw_data.get('Features')
#             else ['No detailed features available']
#         ),
#         'Price': raw_data.get('Price') or 'Price not found'
#     }

# @app.route('/compare', methods=['POST'])
# def compare():
#     data = request.get_json()
#     if not data:
#         return jsonify({'error': 'Missing JSON payload'}), 400

#     url1, url2 = data.get('url1'), data.get('url2')
#     if not (url1 and url2):
#         return jsonify({'error': 'Both URLs are required'}), 400
#     if not (is_valid_url(url1) and is_valid_url(url2)):
#         return jsonify({'error': 'URLs must start with http:// or https://'}), 400

#     logger.info(f"Comparing: {url1} vs {url2}")
    
#     result1 = scrape_features(url1)
#     result2 = scrape_features(url2)

#     # Check for errors
#     errors = {}
#     if 'error' in result1:
#         errors['url1'] = result1['error']
#     if 'error' in result2:
#         errors['url2'] = result2['error']
#     if errors:
#         # 400 status is appropriate for external scraping failure
#         return jsonify({'error': errors}), 400 

#     return jsonify({
#         'data1': normalize_features(result1),
#         'data2': normalize_features(result2)
#     })

# @app.route('/health', methods=['GET'])
# def health_check():
#     """Simple health check endpoint."""
#     return jsonify({'status': 'healthy', 'message': 'API is running'})

# @app.route('/', methods=['GET'])
# def home():
#     """Root endpoint providing API information."""
#     return jsonify({
#         'name': 'Universal Feature Comparator API',
#         'version': '1.3.0 (JSON-LD Enhanced)',
#         'endpoints': {
#             '/compare': 'POST - Compare features from two URLs',
#             '/health': 'GET - Health check'
#         },
#         'note': 'This version prioritizes structured metadata (JSON-LD) for better reliability against bot defenses. Some aggressive sites (Amazon/Flipkart) may still fail due to advanced detection or required JavaScript rendering.'
#     })

# if __name__ == '__main__':
#     print("=" * 50)
#     print("Starting Flask server...")
#     print("API available at: http://127.0.0.1:5000/")
#     print("Health check: http://127.0.0.1:5000/health")
#     print("=" * 50)
#     app.run(debug=True, host='0.0.0.0', port=5000)
