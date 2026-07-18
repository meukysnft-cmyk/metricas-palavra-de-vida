import json
import os
import re
import time
import urllib.request
import urllib.error
from urllib.parse import urlparse
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HTML_FILE = os.path.join(BASE_DIR, 'index.html')
COOKIES_FILE = os.path.join(BASE_DIR, 'cookies.json')
CONFIG_FILE = os.path.join(BASE_DIR, 'config.json')
POSTS_FILE = os.path.join(BASE_DIR, 'posts.json')

app = Flask(__name__)
CORS(app)

logged_in_user = ''


def load_cookies():
    if os.path.exists(COOKIES_FILE):
        with open(COOKIES_FILE, 'r') as f:
            return json.load(f)
    return None


def save_cookies(cookies, username):
    global logged_in_user
    data = {'username': username, 'cookies': cookies}
    with open(COOKIES_FILE, 'w') as f:
        json.dump(data, f)
    logged_in_user = username


def clear_cookies():
    global logged_in_user
    logged_in_user = ''
    if os.path.exists(COOKIES_FILE):
        os.remove(COOKIES_FILE)


def check_login_status():
    global logged_in_user
    data = load_cookies()
    if data and data.get('username'):
        logged_in_user = data['username']


def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {}


def save_config(access_token, ig_account_id):
    config = {
        'access_token': access_token,
        'ig_account_id': ig_account_id,
    }
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f)
    return config


def clear_config():
    if os.path.exists(CONFIG_FILE):
        os.remove(CONFIG_FILE)


def load_posts():
    if os.path.exists(POSTS_FILE):
        with open(POSTS_FILE, 'r') as f:
            return json.load(f)
    return []


def save_posts(posts):
    with open(POSTS_FILE, 'w') as f:
        json.dump(posts, f)


def add_post(post):
    posts = load_posts()
    if not post.get('id'):
        import hashlib
        post['id'] = hashlib.md5((post.get('url', '') + str(time.time())).encode()).hexdigest()[:12]
    if not post.get('timestamp'):
        post['timestamp'] = time.strftime('%Y-%m-%dT%H:%M:%SZ')
    posts.insert(0, post)
    save_posts(posts)
    return posts, post


def delete_post_by_id(post_id):
    posts = load_posts()
    posts = [p for p in posts if p.get('id') != post_id]
    save_posts(posts)
    return posts


def graph_api_fetch(media_id, fields):
    config = load_config()
    token = config.get('access_token', '')
    if not token:
        return None

    from urllib.parse import quote
    safe_token = quote(token, safe='')

    url = f'https://graph.instagram.com/v21.0/{media_id}?fields={fields}&access_token={safe_token}'
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'InstaAnalyzer/1.0'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            if 'error' not in data:
                print(f"[graph_api] OK: {data.get('id', media_id)}")
                return data
            print(f"[graph_api] Erro: {data.get('error', {}).get('message', '')}")
            return None
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        print(f"[graph_api] HTTP {e.code}: {body[:300]}")
        return None
    except Exception as e:
        print(f"[graph_api] Error: {e}")
        return None


def graph_api_list_user_media(ig_user_id, shortcode, token):
    from urllib.parse import quote
    safe_token = quote(token, safe='')

    url = f'https://graph.instagram.com/v21.0/{ig_user_id}/media?fields=id,shortcode&limit=100&access_token={safe_token}'
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'InstaAnalyzer/1.0'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            if 'error' in data:
                print(f"[graph_api] List error: {data['error'].get('message', '')}")
                return None

            for item in data.get('data', []):
                if item.get('shortcode') == shortcode:
                    print(f"[graph_api] Encontrou media_id={item['id']} para shortcode={shortcode}")
                    return item['id']

            after = data.get('paging', {}).get('cursors', {}).get('after')
            while after:
                url2 = f'https://graph.instagram.com/v21.0/{ig_user_id}/media?fields=id,shortcode&limit=100&after={after}&access_token={safe_token}'
                req2 = urllib.request.Request(url2, headers={'User-Agent': 'InstaAnalyzer/1.0'})
                with urllib.request.urlopen(req2, timeout=15) as resp2:
                    data2 = json.loads(resp2.read().decode('utf-8'))
                    if 'error' in data2:
                        break
                    for item in data2.get('data', []):
                        if item.get('shortcode') == shortcode:
                            print(f"[graph_api] Encontrou media_id={item['id']} (page 2+)")
                            return item['id']
                    after = data2.get('paging', {}).get('cursors', {}).get('after')

            print(f"[graph_api] Shortcode {shortcode} nao encontrado nas medias do usuario")
            return None
    except Exception as e:
        print(f"[graph_api] List error: {e}")
        return None


@app.route('/')
def index():
    return send_file(HTML_FILE)


@app.route('/api/status')
def status():
    check_login_status()
    config = load_config()
    return jsonify({
        'logged_in': logged_in_user != '',
        'username': logged_in_user,
        'api_configured': bool(config.get('access_token') and config.get('ig_account_id')),
    })


@app.route('/api/config')
def api_config():
    config = load_config()
    token = config.get('access_token', '')
    return jsonify({
        'configured': bool(token and config.get('ig_account_id')),
        'ig_account_id': config.get('ig_account_id', ''),
        'has_token': bool(token),
        'token_preview': token[:10] + '...' if len(token) > 10 else token,
    })


@app.route('/api/setup', methods=['POST'])
def api_setup():
    data = request.get_json()
    action = data.get('action', 'save')

    if action == 'clear':
        clear_config()
        return jsonify({'ok': True, 'configured': False})

    access_token = data.get('access_token', '').strip()
    ig_account_id = data.get('ig_account_id', '').strip()

    if not access_token or not ig_account_id:
        return jsonify({'error': 'Access Token e IG Account ID sao obrigatorios'}), 400

    from urllib.parse import quote
    safe_token = quote(access_token, safe='')
    test_url = f'https://graph.instagram.com/v21.0/me?access_token={safe_token}'
    try:
        req = urllib.request.Request(test_url, headers={'User-Agent': 'InstaAnalyzer/1.0'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            test_data = json.loads(resp.read().decode('utf-8'))
            if 'error' in test_data:
                return jsonify({'error': f'Token invalido: {test_data["error"].get("message", "")}'}), 400
            print(f"[setup] Token validado: {test_data.get('name', test_data.get('id', 'OK'))}")
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        return jsonify({'error': f'Token invalido: {body[:200]}'}), 400
    except Exception as e:
        return jsonify({'error': f'Erro ao validar token: {str(e)}'}), 400

    save_config(access_token, ig_account_id)
    print(f"[setup] API configurada: ig_account_id={ig_account_id}")
    return jsonify({'ok': True, 'configured': True, 'ig_account_id': ig_account_id})


@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    if not username or not password:
        return jsonify({'error': 'Username e password sao obrigatorios'}), 400

    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=True)
    ctx = browser.new_context(
        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        viewport={'width': 1280, 'height': 900},
        locale='en-US',
    )
    page = ctx.new_page()
    try:
        page.goto('https://www.instagram.com/accounts/login/', wait_until='domcontentloaded', timeout=30000)
        time.sleep(3)

        user_input = page.query_selector('input[name="email"], input[name="username"]')
        pass_input = page.query_selector('input[name="pass"], input[name="password"]')
        if not user_input or not pass_input:
            return jsonify({'error': 'Nao foi possivel encontrar os campos de login'}), 400

        user_input.fill(username)
        time.sleep(0.3)
        pass_input.fill(password)
        time.sleep(0.3)
        pass_input.press('Enter')

        time.sleep(8)

        page.screenshot(path=os.path.join(BASE_DIR, 'debug_login.png'))
        print(f"[login] URL apos login: {page.url}")

        has_session = any(c['name'] == 'sessionid' for c in ctx.cookies())
        url_ok = 'login' not in page.url

        if not has_session and not url_ok:
            return jsonify({'error': 'Login falhou. O Instagram pode estar pedindo verificacao. Tente novamente.'}), 400

        cookies = ctx.cookies()
        save_cookies(cookies, username)
        print(f"[login] Logado como @{username}")
        return jsonify({'ok': True, 'username': username})
    except Exception as e:
        return jsonify({'error': f'Falha no login: {str(e)}'}), 400
    finally:
        browser.close()
        pw.stop()


@app.route('/api/logout', methods=['POST'])
def logout():
    clear_cookies()
    return jsonify({'ok': True})


@app.route('/api/posts', methods=['GET'])
def get_posts():
    return jsonify(load_posts())


@app.route('/api/posts', methods=['POST'])
def create_post():
    post = request.get_json()
    if not post or not post.get('url'):
        return jsonify({'error': 'Post invalido'}), 400
    posts, saved = add_post(post)
    return jsonify(saved)


@app.route('/api/posts/<post_id>', methods=['DELETE'])
def remove_post(post_id):
    posts = delete_post_by_id(post_id)
    return jsonify({'ok': True, 'count': len(posts)})


@app.route('/api/posts/clear', methods=['POST'])
def clear_posts():
    save_posts([])
    return jsonify({'ok': True})


@app.route('/api/posts/refresh', methods=['POST'])
def refresh_posts():
    posts = load_posts()
    if not posts:
        return jsonify({'ok': True, 'updated': 0, 'errors': 0})

    ok = 0
    fail = 0
    for i, post in enumerate(posts):
        try:
            result = scrape_instagram(post['url'])
            posts[i]['likes'] = result.get('likes')
            posts[i]['comments'] = result.get('comments')
            posts[i]['views'] = result.get('views')
            posts[i]['views_unavailable'] = result.get('views_unavailable', False)
            posts[i]['saves'] = result.get('saves')
            posts[i]['shares'] = result.get('shares')
            posts[i]['reach'] = result.get('reach')
            posts[i]['caption'] = result.get('caption', '')
            posts[i]['hashtags'] = result.get('hashtags', [])
            posts[i]['source'] = result.get('source', 'scraping')
            posts[i]['thumbnailUrl'] = result.get('thumbnailUrl', '')
            posts[i]['updatedAt'] = time.strftime('%Y-%m-%dT%H:%M:%SZ')
            ok += 1
        except Exception as e:
            print(f"[refresh] Error refreshing {post.get('url', '?')}: {e}")
            fail += 1

    save_posts(posts)
    return jsonify({'ok': True, 'updated': ok, 'errors': fail})


@app.route('/api/analyze', methods=['POST'])
def analyze():
    data = request.get_json()
    url = data.get('url', '').strip()
    if not url or 'instagram.com' not in url:
        return jsonify({'error': 'URL invalida'}), 400
    try:
        result = scrape_instagram(url)
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def scrape_instagram(url):
    post_id = ''
    is_reel = '/reel/' in url
    try:
        parts = [x for x in urlparse(url).path.split('/') if x]
        post_id = parts[-1] if parts else ''
    except:
        pass

    result = {
        'url': url,
        'postId': post_id,
        'type': 'Reels' if is_reel else 'Post',
        'author': '',
        'title': '',
        'caption': '',
        'thumbnailUrl': '',
        'likes': None,
        'comments': None,
        'views': None,
        'views_unavailable': False,
        'saves': None,
        'shares': None,
        'reach': None,
        'source': 'scraping',
        'hashtags': [],
    }

    captured_data = []

    def handle_response(response):
        try:
            ct = response.headers.get('content-type', '')
            if 'json' in ct or 'javascript' in ct:
                body = response.text()
                if any(k in body for k in ['video_view_count', 'play_count', 'edge_media_preview_like', 'like_count']):
                    captured_data.append(body)
        except:
            pass

    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=True)
    ctx = browser.new_context(
        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        viewport={'width': 1280, 'height': 900},
        locale='en-US',
    )

    cookies_data = load_cookies()
    if cookies_data and cookies_data.get('cookies'):
        ctx.add_cookies(cookies_data['cookies'])

    page = ctx.new_page()
    page.on('response', handle_response)

    page.goto(url, wait_until='domcontentloaded', timeout=30000)
    time.sleep(8)

    try:
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(2)
    except:
        pass

    html = page.content()

    def meta(prop, name=None):
        for pattern in [
            rf'<meta\s+property="{prop}"\s+content="([^"]*)"',
            rf'<meta\s+content="([^"]*)"\s+property="{prop}"',
        ]:
            m = re.findall(pattern, html)
            if m:
                return m[0]
        if name:
            for pattern in [
                rf'<meta\s+name="{name}"\s+content="([^"]*)"',
                rf'<meta\s+content="([^"]*)"\s+name="{name}"',
            ]:
                m = re.findall(pattern, html)
                if m:
                    return m[0]
        return ''

    result['title'] = meta('og:title')
    result['thumbnailUrl'] = meta('og:image') or meta('og:video')
    og_desc = meta('og:description')
    meta_desc = meta('og:description', name='description')

    desc_text = og_desc or meta_desc
    result['caption'] = desc_text

    m_likes = re.search(r'([\d,.]+[KkMm]?)\s+likes?', desc_text, re.IGNORECASE)
    if m_likes:
        result['likes'] = parse_count(m_likes.group(1))

    m_comments = re.search(r'([\d,.]+[KkMm]?)\s+comments?', desc_text, re.IGNORECASE)
    if m_comments:
        result['comments'] = parse_count(m_comments.group(1))

    if og_desc:
        after_dash = re.split(r'\s*[-:]\s*', og_desc, maxsplit=1)
        if len(after_dash) == 2:
            m_user = re.match(r'([\w.]+)\s+on\s+', after_dash[1])
            if m_user:
                result['author'] = m_user.group(1)

    if not result['author']:
        m_author_ld = re.search(r'"([^"]+) on Instagram', meta('og:title'))
        if m_author_ld:
            result['author'] = m_author_ld.group(1)

    all_text = desc_text
    try:
        all_text = page.inner_text('body')
    except:
        pass

    if not result['likes']:
        m = re.search(r'([\d,.]+[KkMm]?)\s+(?:likes?|curti)', all_text, re.IGNORECASE)
        if m:
            result['likes'] = parse_count(m.group(1))

    if not result['comments']:
        m = re.search(r'([\d,.]+[KkMm]?)\s+(?:comments?|coment)', all_text, re.IGNORECASE)
        if m:
            result['comments'] = parse_count(m.group(1))

    if not result['views']:
        m = re.search(r'([\d,.]+[KkMm]?)\s+(?:views?|visualiza)', all_text, re.IGNORECASE)
        if m:
            result['views'] = parse_count(m.group(1))

    if not result['views']:
        try:
            spans = page.query_selector_all('span')
            for span in spans:
                txt = span.inner_text().strip().lower()
                if 'view' in txt or 'visualiza' in txt or 'reproduc' in txt:
                    nums = re.findall(r'([\d,.]+[KkMm]?)', txt)
                    if nums:
                        result['views'] = parse_count(nums[0])
                        break
        except:
            pass

    embedded = re.search(r'"like_count"\s*:\s*\d+', html)
    if embedded:
        for kw in ['like_count', 'comment_count', 'view_count', 'video_view_count', 'play_count']:
            ms = re.findall(rf'"{kw}"\s*:\s*(\d+)', html)
            if ms:
                val = int(ms[0])
                if kw == 'like_count' and (result['likes'] is None or result['likes'] == 0):
                    result['likes'] = val
                elif kw == 'comment_count' and (result['comments'] is None or result['comments'] == 0):
                    result['comments'] = val
                elif kw in ('view_count', 'video_view_count', 'play_count') and result['views'] is None:
                    result['views'] = val

    if result['views'] is None:
        view_null = re.search(r'"view_count"\s*:\s*null', html)
        if view_null:
            result['views_unavailable'] = True

    for raw in captured_data:
        if result['views'] is None:
            m = re.search(r'"video_view_count":\s*(\d+)', raw)
            if m:
                result['views'] = int(m.group(1))
        if result['views'] is None:
            m = re.search(r'"play_count":\s*(\d+)', raw)
            if m:
                result['views'] = int(m.group(1))
        if result['likes'] is None:
            m = re.search(r'"like_count":\s*(\d+)', raw)
            if m:
                result['likes'] = int(m.group(1))
        if result['comments'] is None:
            m = re.search(r'"comment_count":\s*(\d+)', raw)
            if m:
                result['comments'] = int(m.group(1))

    if not result['hashtags'] and desc_text:
        result['hashtags'] = list(dict.fromkeys(re.findall(r'#[\w\u00C0-\u017F]+', desc_text)))

    browser.close()
    pw.stop()

    config = load_config()
    if config.get('access_token') and config.get('ig_account_id'):
        media_id = extract_media_id_from_url(html)
        api_result = fetch_graph_api_data(media_id, config['access_token'], config['ig_account_id'], shortcode=post_id)
        if api_result:
            result['source'] = 'graph_api'
            result['views_unavailable'] = False
            for key in ['likes', 'comments', 'views', 'saves', 'shares', 'reach']:
                if api_result.get(key) is not None:
                    result[key] = api_result[key]
            if api_result.get('author'):
                result['author'] = api_result['author']
            if api_result.get('thumbnailUrl') and not result['thumbnailUrl']:
                result['thumbnailUrl'] = api_result['thumbnailUrl']
            if api_result.get('caption') and not result['caption']:
                result['caption'] = api_result['caption']
            if api_result.get('hashtags'):
                result['hashtags'] = api_result['hashtags']
            if api_result.get('type'):
                result['type'] = api_result['type']
            print(f"[analyze] Graph API: @{result['author']}: {result['likes']} likes, {result['comments']} comments, {result['views']} views, {result['saves']} saves, {result['shares']} shares, {result['reach']} reach")
        else:
            print("[analyze] Graph API configurada mas nao conseguiu extrair media_id do HTML")
    else:
        print(f"[analyze] Scraping: @{result['author']}: {result['likes']} likes, {result['comments']} comments, {result['views']} views")

    return result


def extract_media_id_from_url(html):
    shortcode_match = re.search(r'"shortcode"\s*:\s*"([A-Za-z0-9_-]+)"', html)
    if shortcode_match:
        return shortcode_match.group(1)

    patterns = [
        r'"media_id"\s*:\s*"?(\d+)"?',
        r'"id"\s*:\s*"?(\d{15,})"?',
    ]
    for pattern in patterns:
        m = re.search(pattern, html)
        if m:
            return m.group(1)

    return None


def fetch_graph_api_data(media_id, access_token, ig_account_id, shortcode=''):
    graph_id = graph_api_list_user_media(ig_account_id, shortcode, access_token)

    if not graph_id:
        graph_id = media_id
        print(f"[graph_api] Usando media_id direto: {graph_id}")

    fields = 'id,shortcode,caption,media_type,media_product_type,media_url,thumbnail_url,permalink,timestamp,username,like_count,comments_count'
    data = graph_api_fetch(graph_id, fields)
    if not data or 'error' in data:
        print(f"[graph_api] Erro ao buscar media {graph_id}: {data}")
        return None

    result = {
        'likes': data.get('like_count'),
        'comments': data.get('comments_count'),
        'views': None,
        'saves': None,
        'shares': None,
        'author': data.get('username', ''),
        'thumbnailUrl': data.get('thumbnail_url', ''),
        'caption': data.get('caption', ''),
        'type': 'Reels' if data.get('media_product_type') == 'REELS' else (data.get('media_type', 'POST')),
        'reach': None,
        'hashtags': [],
    }

    if result['caption']:
        result['hashtags'] = list(dict.fromkeys(re.findall(r'#[\w\u00C0-\u017F]+', result['caption'])))

    try:
        from urllib.parse import quote
        safe_token = quote(access_token, safe='')
        insights_url = f'https://graph.instagram.com/v21.0/{graph_id}/insights?metric=views,reach&access_token={safe_token}'
        req = urllib.request.Request(insights_url, headers={'User-Agent': 'InstaAnalyzer/1.0'})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                insights = json.loads(resp.read().decode('utf-8'))
                if 'error' not in insights:
                    for item in insights.get('data', []):
                        name = item.get('name', '')
                        val = item.get('values', [{}])[0].get('value')
                        print(f"[graph_api] Insight: {name}={val}")
                        if name == 'reach':
                            result['reach'] = val
                        elif name == 'views' and result['views'] is None:
                            result['views'] = val
                else:
                    print(f"[graph_api] Insights error: {insights}")
        except urllib.error.HTTPError as e:
            body = e.read().decode('utf-8', errors='replace')
            print(f"[graph_api] Insights HTTP {e.code}: {body[:300]}")
    except Exception as e:
        print(f"[graph_api] Insights indisponiveis: {e}")

    return result


def parse_count(text):
    text = text.strip().replace(',', '')
    try:
        t = text.lower()
        if t.endswith('k'):
            return int(float(t[:-1]) * 1000)
        if t.endswith('m'):
            return int(float(t[:-1]) * 1000000)
        return int(float(t))
    except:
        return None


if __name__ == '__main__':
    check_login_status()
    config = load_config()
    status_parts = []
    if logged_in_user:
        status_parts.append(f"logado como @{logged_in_user}")
    if config.get('access_token') and config.get('ig_account_id'):
        status_parts.append("Graph API ativa")
    status_str = f" ({', '.join(status_parts)})" if status_parts else ""
    port = int(os.environ.get('PORT', 5000))
    print(f"Metricas Palavra de Vida{status_str} - http://0.0.0.0:{port}")
    app.run(host='0.0.0.0', port=port, debug=False)
