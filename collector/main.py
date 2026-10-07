"""Собирает медицинские новости Казахстана, фильтрует по рубрикам и публикует RSS в docs/."""
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from xml.sax.saxutils import escape

import warnings

import feedparser
import requests
import yaml
from bs4 import BeautifulSoup, MarkupResemblesLocatorWarning

warnings.filterwarnings("ignore", category=MarkupResemblesLocatorWarning)

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"
STATE = ROOT / "data" / "items.json"
OUT = ROOT / "docs"
KEEP_DAYS = 30
FEED_SIZE = 200
UA = "Mozilla/5.0 (compatible; med-news-kz/1.0; +https://github.com/sagynrus/med-news-kz)"


def compile_words(words):
    """'анализатор*' -> regex по границе слова; * = любое окончание."""
    parts = []
    for w in words:
        p = re.escape(w).replace(r"\*", r"\w*").replace(r"\ ", r"\s+")
        parts.append(p)
    return re.compile(r"(?<!\w)(?:" + "|".join(parts) + r")(?!\w)", re.IGNORECASE)


def clean(text):
    return re.sub(r"\s+", " ", BeautifulSoup(text or "", "html.parser").get_text(" ")).strip()


def fetch_rss(src):
    r = requests.get(src["url"], headers={"User-Agent": UA}, timeout=30)
    r.raise_for_status()
    feed = feedparser.parse(r.content)
    for e in feed.entries:
        ts = e.get("published_parsed") or e.get("updated_parsed")
        date = datetime(*ts[:6], tzinfo=timezone.utc) if ts else datetime.now(timezone.utc)
        yield {
            "title": clean(e.get("title")),
            "summary": clean(e.get("summary") or e.get("description"))[:600],
            "link": e.get("link"),
            "date": date,
        }


def fetch_telegram(src):
    url = f"https://t.me/s/{src['channel']}"
    r = requests.get(url, headers={"User-Agent": UA}, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    posts = soup.select("div.tgme_widget_message[data-post]")
    if not posts:
        raise RuntimeError("нет открытой ленты постов")
    for post in posts:
        body = post.select_one(".tgme_widget_message_text")
        if not body:
            continue
        text = clean(str(body))
        t = post.select_one("time[datetime]")
        date = datetime.fromisoformat(t["datetime"]) if t else datetime.now(timezone.utc)
        first = re.split(r"(?<=[.!?])\s|\n", body.get_text("\n").strip(), maxsplit=1)[0].strip()
        title = first if 10 <= len(first) <= 200 else text[:140].rsplit(" ", 1)[0] + "…"
        yield {
            "title": title,
            "summary": text[:600],
            "link": f"https://t.me/{post['data-post']}",
            "date": date.astimezone(timezone.utc),
        }


def fetch_html(src):
    """Страница-список новостей без RSS: берём ссылки, подходящие под link_pattern.

    Дату публикации со страницы не разбираем: ставим время, когда новость впервые увидели.
    """
    from urllib.parse import urljoin

    r = requests.get(src["url"], headers={"User-Agent": UA}, timeout=30)
    r.raise_for_status()
    r.encoding = r.apparent_encoding or r.encoding
    soup = BeautifulSoup(r.text, "html.parser")
    rx = re.compile(src["link_pattern"])
    titles = {}
    for a in soup.find_all("a", href=True):
        link = urljoin(src["url"], a["href"]).split("#")[0]
        if not rx.search(link):
            continue
        text = clean(a.get_text(" ")) or clean(a.get("title"))
        if len(text) < 15:  # «Подробнее» и картинки: берём текст карточки вокруг ссылки
            block = a.parent
            for _ in range(3):
                if block is None or len(clean(block.get_text(" "))) >= 15:
                    break
                block = block.parent
            text = clean(block.get_text(" "))[:200] if block is not None else text
            text = re.sub(r"\s*(Подробнее|Читать далее|Толығырақ)\.?$", "", text, flags=re.I)
        if len(text) > len(titles.get(link, "")):
            titles[link] = text
    found = [(link, t) for link, t in titles.items() if len(t) >= 15]
    if not found:
        sample = [a["href"] for a in soup.find_all("a", href=True)][:40]
        raise RuntimeError(
            f"на странице не найдено ссылок на новости (HTTP {r.status_code}, {len(r.text)} симв., "
            f"ссылки на странице: {sample}" + ("" if sample else f", текст: {r.text[:500]!r}") + ")"
        )
    now = datetime.now(timezone.utc)
    for link, title in found[: src.get("limit", 15)]:
        yield {"title": title[:200], "summary": title, "link": link, "date": now}


def fetch_next_json(src):
    """Сайт на Next.js без ссылок в HTML: новости лежат JSON-ом внутри страницы.

    Ищем объекты с полями titleRu / slug / shortTextRu / createdAt.
    """
    r = requests.get(src["url"], headers={"User-Agent": UA}, timeout=60)
    r.raise_for_status()
    raw = r.content.decode("utf-8", "replace").replace('\\"', '"')
    rx = re.compile(r'"titleRu":"([^"]*)".{0,600}?"slug":"([^"]+)".{0,400}?"shortTextRu":"([^"]*)"', re.S)
    seen, items = set(), []
    for m in rx.finditer(raw):
        slug = m.group(2)
        if slug in seen:
            continue
        seen.add(slug)
        d = re.search(r'"createdAt":"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)', raw[m.end():m.end() + 20000])
        date = (datetime.strptime(d.group(1), "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
                if d else datetime.now(timezone.utc))
        items.append({"title": clean(m.group(1)), "summary": clean(m.group(3))[:600],
                      "link": src["link_template"].format(slug=slug), "date": date})
    if not items:
        raise RuntimeError(f"новости в данных страницы не найдены ({len(raw)} симв.)")
    return items[: src.get("limit", 15)]


def fetch_probe_js(src):  # ПРОБА (временно)
    page = requests.get(src["url"], headers={"User-Agent": UA}, timeout=30).text
    js_path = re.search(r'src="(/assets/[^"]+\.js)"', page).group(1)
    base = re.match(r"https?://[^/]+", src["url"]).group(0)
    js = requests.get(base + js_path, headers={"User-Agent": UA}, timeout=30).text
    urls = sorted(set(re.findall(r"https?://[\w.-]+(?:/[\w./-]*)?", js)))
    apis = sorted(set(re.findall(r"[\"'`](/?(?:api|v\d)[\w./${}-]*)", js)))
    news = sorted(set(m[:120] for m in re.findall(r".{60}news.{60}", js)))[:25]
    raise RuntimeError(f"JS {len(js)} симв.; URL: {urls[:60]}; API: {apis[:80]}; NEWS: {news}")


class SkipSource(Exception):
    """Источник не настроен: пропускаем без ошибки."""


def fetch_instagram(src):
    """Посты публичного бизнес-аккаунта через Business Discovery (Instagram Graph API).

    Нужны секреты IG_USER_ID (ваш бизнес-аккаунт) и IG_TOKEN (токен страницы Facebook).
    """
    user_id, token = os.environ.get("IG_USER_ID"), os.environ.get("IG_TOKEN")
    if not user_id or not token:
        raise SkipSource("не заданы секреты IG_USER_ID и IG_TOKEN")
    version = os.environ.get("IG_API_VERSION", "v26.0")
    fields = (f"business_discovery.username({src['username']})"
              "{media.limit(15){caption,permalink,timestamp}}")
    r = requests.get(f"https://graph.facebook.com/{version}/{user_id}",
                     params={"fields": fields, "access_token": token}, timeout=30)
    if r.status_code != 200:
        try:
            msg = r.json()["error"]["message"]
        except (ValueError, KeyError):
            msg = r.text[:200]
        raise RuntimeError(f"HTTP {r.status_code}: {msg}")
    for m in r.json()["business_discovery"]["media"]["data"]:
        caption = clean(m.get("caption"))
        if not caption:
            continue
        first = re.split(r"(?<=[.!?])\s|\n", (m.get("caption") or "").strip(), maxsplit=1)[0].strip()
        title = first if 10 <= len(first) <= 200 else caption[:140].rsplit(" ", 1)[0] + "…"
        yield {
            "title": title,
            "summary": caption[:600],
            "link": m["permalink"],
            "date": datetime.strptime(m["timestamp"], "%Y-%m-%dT%H:%M:%S%z").astimezone(timezone.utc),
        }


FETCHERS = {"rss": fetch_rss, "telegram": fetch_telegram, "html": fetch_html,
            "next_json": fetch_next_json, "instagram": fetch_instagram, "probe_js": fetch_probe_js}


def norm_title(t):
    return re.sub(r"[^\w]+", " ", t.lower()).strip()[:120]


def title_words(t):
    """Значимые слова заголовка; первые 6 букв, чтобы «закупки» и «закупок» совпадали."""
    return frozenset(w[:6] for w in re.findall(r"\w+", t.lower()) if len(w) >= 4 and not w.isdigit())


def is_similar(words, seen):
    """Та же новость другими словами: заголовки совпадают на 80% слов,
    или короткий заголовок (от 5 слов) почти целиком (85%) входит в длинный, как при обрезке."""
    if len(words) < 4:
        return False
    for other in seen:
        if len(other) < 4:
            continue
        common = len(words & other)
        if common / len(words | other) >= 0.8:
            return True
        shorter = min(len(words), len(other))
        if shorter >= 5 and common / shorter >= 0.85:
            return True
    return False


def classify(item, src, kw):
    text = f"{item['title']} {item['summary']}"
    if kw["exclude"].search(item["title"]):
        return []
    if not src.get("medical") and not kw["context"].search(text):
        return []
    rubrics = [key for key, rx in kw["rubrics"].items() if rx.search(text)]
    if not rubrics and src.get("default_rubric"):
        rubrics = [src["default_rubric"]]
    return rubrics


def rss_xml(title, desc, items, self_url):
    now = format_datetime(datetime.now(timezone.utc))
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom"><channel>',
        f"<title>{escape(title)}</title>",
        "<link>https://github.com/sagynrus/med-news-kz</link>",
        f"<description>{escape(desc)}</description>",
        "<language>ru</language>",
        f"<lastBuildDate>{now}</lastBuildDate>",
        f'<atom:link href="{escape(self_url)}" rel="self" type="application/rss+xml"/>',
    ]
    for it in items:
        cats = "".join(f"<category>{escape(c)}</category>" for c in it["rubric_titles"])
        desc_html = f"<p><b>{escape(it['source'])}</b> · {escape(', '.join(it['rubric_titles']))}</p><p>{escape(it['summary'])}</p>"
        out.append(
            "<item>"
            f"<title>{escape(it['title'])}</title>"
            f"<link>{escape(it['link'])}</link>"
            f'<guid isPermaLink="false">{it["id"]}</guid>'
            f"<pubDate>{format_datetime(datetime.fromisoformat(it['date']))}</pubDate>"
            f"<source url=\"{escape(it['link'])}\">{escape(it['source'])}</source>"
            f"{cats}"
            f"<description>{escape(desc_html)}</description>"
            "</item>"
        )
    out.append("</channel></rss>")
    return "\n".join(out)


def news_json(rubrics, items):
    """Данные для страницы-просмотрщика: новости с оценкой важности.

    Важность = вес самой важной рубрики + по баллу за каждое найденное ключевое слово (до 5,
    разные формы одного слова считаются один раз) + балл за каждую дополнительную рубрику.
    Веса рубрик: weight в config/keywords.yaml.
    """
    patterns = {w: compile_words([w]) for r in rubrics.values() for w in r["words"]}
    out = []
    for it in items:
        text = f"{it['title']} {it['summary']}"
        words = sorted({m.group(0).lower() for rx in patterns.values() if (m := rx.search(text))})
        weights = [rubrics[r].get("weight", 1) for r in it["rubrics"] if r in rubrics] or [1]
        score = max(weights) + min(len(words), 5) + len(weights) - 1
        out.append({**{k: it[k] for k in ("id", "title", "summary", "link", "source", "rubrics", "date")},
                    "score": score, "words": words})
    return json.dumps({
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "rubrics": {k: {"title": r["title"], "weight": r.get("weight", 1)} for k, r in rubrics.items()},
        "items": out,
    }, ensure_ascii=False, separators=(",", ":"))


def main():
    sources = yaml.safe_load((CONFIG / "sources.yaml").read_text(encoding="utf-8"))["sources"]
    kwc = yaml.safe_load((CONFIG / "keywords.yaml").read_text(encoding="utf-8"))
    kw = {
        "context": compile_words(kwc["medical_context"]),
        "exclude": compile_words(kwc["exclude"]),
        "rubrics": {k: compile_words(v["words"]) for k, v in kwc["rubrics"].items()},
    }
    titles = {k: v["title"] for k, v in kwc["rubrics"].items()}

    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else []
    seen_links = {it["link"] for it in state}
    seen_titles = {norm_title(it["title"]) for it in state}
    seen_words = [title_words(it["title"]) for it in state]
    cutoff = datetime.now(timezone.utc) - timedelta(days=KEEP_DAYS)

    report, added = [], 0
    for src in sources:
        try:
            raw = list(FETCHERS[src["type"]](src))
        except SkipSource as e:
            report.append(f"пропуск  {src['name']}: {e}")
            continue
        except Exception as e:  # noqa: BLE001 — один сломанный источник не должен останавливать ленту
            report.append(f"ОШИБКА  {src['name']}: {e}")
            continue
        kept = 0
        for item in raw:
            if not item["link"] or item["date"] < cutoff:
                continue
            nt = norm_title(item["title"])
            words = title_words(item["title"])
            if item["link"] in seen_links or nt in seen_titles or is_similar(words, seen_words):
                continue
            rubrics = classify(item, src, kw)
            if not rubrics:
                continue
            seen_links.add(item["link"])
            seen_titles.add(nt)
            seen_words.append(words)
            state.append({
                "id": hashlib.sha1(item["link"].encode()).hexdigest()[:16],
                "title": item["title"],
                "summary": item["summary"],
                "link": item["link"],
                "date": item["date"].isoformat(),
                "source": src["name"],
                "rubrics": rubrics,
                "rubric_titles": [titles[r] for r in rubrics],
            })
            kept += 1
        added += kept
        report.append(f"ok      {src['name']}: получено {len(raw)}, отобрано {kept}")

    state = [it for it in state if datetime.fromisoformat(it["date"]) >= cutoff]
    state.sort(key=lambda it: it["date"], reverse=True)
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")

    base = "https://sagynrus.github.io/med-news-kz/"
    OUT.mkdir(exist_ok=True)
    (OUT / "feed.xml").write_text(
        rss_xml("Медновости РК: все рубрики", "Медицина, оборудование, закупки и приказы МЗ РК",
                state[:FEED_SIZE], base + "feed.xml"), encoding="utf-8")
    for key, title in titles.items():
        items = [it for it in state if key in it["rubrics"]][:FEED_SIZE]
        (OUT / f"{key}.xml").write_text(
            rss_xml(f"Медновости РК: {title}", title, items, base + f"{key}.xml"), encoding="utf-8")
    (OUT / "news.json").write_text(news_json(kwc["rubrics"], state), encoding="utf-8")
    (OUT / "index.html").write_text((ROOT / "collector" / "viewer.html").read_text(encoding="utf-8"),
                                    encoding="utf-8")

    print("\n".join(report))
    print(f"Новых: {added}, всего в базе: {len(state)}")
    if not any(line.startswith("ok") for line in report):
        sys.exit(1)


if __name__ == "__main__":
    main()
