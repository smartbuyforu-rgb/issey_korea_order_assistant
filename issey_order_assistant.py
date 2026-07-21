from __future__ import annotations

import argparse
import asyncio
import csv
import html
import json
import math
import os
import re
import subprocess
import sys
import time
import urllib.request
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from deep_translator import GoogleTranslator
except ImportError:
    GoogleTranslator = None
from urllib.parse import parse_qsl, quote, urlencode, urljoin, urlparse, urlunparse

try:
    from playwright.async_api import BrowserContext, Page, async_playwright
except ImportError:
    print("Playwright가 설치되지 않았습니다. 먼저 01_INSTALL.bat을 실행하세요.")
    raise

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
PRIVATE_DIR = ROOT / "private"
PROFILE_DIR = PRIVATE_DIR / "browser_profile"
DATA_DIR = ROOT / "data"
EXCHANGE_RATE_JSON = DATA_DIR / "exchange_rate.json"
TRANSLATION_CACHE = PRIVATE_DIR / "translation_cache.json"
CATALOG_JSON = DATA_DIR / "catalog.json"
CATALOG_JS = DATA_DIR / "catalog.js"
INDEX_HTML = ROOT / "index.html"
DETAIL_HTML = ROOT / "detail.html"
ORDER_HTML = ROOT / "order.html"
DEBUG_HTML = PRIVATE_DIR / "debug_collection.html"
DEBUG_SCREENSHOT = PRIVATE_DIR / "debug_collection.png"
DEBUG_INFO = PRIVATE_DIR / "debug_info.json"
KST = timezone(timedelta(hours=9))
LOGIN_REQUIRED_TEXTS = (
    "商品を閲覧するにはログインが必要です",
    "로그인이 필요",
    "login is required",
)


class CatalogError(RuntimeError):
    pass


@dataclass
class Settings:
    site_base_url: str
    landing_url: str
    product_json_urls: list[str]
    collection_urls: list[str]
    site_title: str
    refresh_minutes: int
    browser_channel: str
    headless_collect: bool
    max_pages: int
    page_limit: int
    request_delay_seconds: float
    product_delay_seconds: float
    detail_refresh_hours: int
    max_new_detail_pages_per_run: int
    git_branch: str
    github_pages_base_url: str
    quote_url: str
    translate_enabled: bool
    translate_descriptions: bool
    max_new_translations_per_run: int
    google_sheet_csv_url: str
    manual_jpy_krw: float
    fx_markup_percent: float
    fixed_fee_krw: int
    price_round_unit: int
    price_round_mode: str


def load_settings() -> Settings:
    if not CONFIG_PATH.exists():
        raise CatalogError(f"설정 파일이 없습니다: {CONFIG_PATH}")
    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    pricing = data.get("pricing") or {}
    translation = data.get("translation") or {}
    return Settings(
        site_base_url=str(data.get("site_base_url", "https://www.isseymiyake.com")).rstrip("/"),
        landing_url=str(data.get("landing_url", "https://www.isseymiyake.com/collections/special-price")).strip(),
        product_json_urls=[str(x).strip() for x in (data.get("product_json_urls") or []) if str(x).strip()],
        collection_urls=[str(x).strip() for x in (data.get("collection_urls") or []) if str(x).strip()],
        site_title=str(data.get("site_title", "ISSEY MIYAKE KOREA CATALOG")).strip(),
        refresh_minutes=max(5, int(data.get("refresh_minutes", 15))),
        browser_channel=str(data.get("browser_channel", "chrome")).strip(),
        headless_collect=bool(data.get("headless_collect", True)),
        max_pages=max(1, int(data.get("max_pages", 20))),
        page_limit=max(1, int(data.get("page_limit", 250))),
        request_delay_seconds=max(0.1, float(data.get("request_delay_seconds", 0.5))),
        product_delay_seconds=max(0.1, float(data.get("product_delay_seconds", 0.3))),
        detail_refresh_hours=max(1, int(data.get("detail_refresh_hours", 168))),
        max_new_detail_pages_per_run=max(0, int(data.get("max_new_detail_pages_per_run", 25))),
        git_branch=str(data.get("git_branch", "main")).strip() or "main",
        github_pages_base_url=str(data.get("github_pages_base_url", "")).strip(),
        quote_url=str(data.get("quote_url", "https://blog.naver.com/pilkyu01/224353040280")).strip(),
        translate_enabled=bool(translation.get("enabled", True)),
        translate_descriptions=bool(translation.get("translate_descriptions", False)),
        max_new_translations_per_run=max(0, int(translation.get("max_new_translations_per_run", 30))),
        google_sheet_csv_url=str(pricing.get("google_sheet_csv_url", "")).strip(),
        manual_jpy_krw=float(pricing.get("manual_jpy_krw", 9.30)),
        fx_markup_percent=float(pricing.get("markup_percent", 4.0)),
        fixed_fee_krw=int(pricing.get("fixed_fee_krw", 25000)),
        price_round_unit=max(1, int(pricing.get("round_unit", 1000))),
        price_round_mode=str(pricing.get("round_mode", "ceil")).strip().lower(),
    )


def log(message: str) -> None:
    now = datetime.now(KST).strftime("%H:%M:%S")
    print(f"[{now}] {message}", flush=True)


def ensure_dirs() -> None:
    PRIVATE_DIR.mkdir(parents=True, exist_ok=True)
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)


async def launch_context(playwright: Any, settings: Settings, *, headless: bool) -> BrowserContext:
    kwargs: dict[str, Any] = {
        "user_data_dir": str(PROFILE_DIR),
        "headless": headless,
        "viewport": {"width": 1440, "height": 1000},
        "locale": "ja-JP",
        "timezone_id": "Asia/Tokyo",
        "args": ["--disable-blink-features=AutomationControlled"],
    }
    channel = settings.browser_channel or ""
    if channel:
        try:
            return await playwright.chromium.launch_persistent_context(channel=channel, **kwargs)
        except Exception as exc:
            log(f"설정된 브라우저 채널({channel}) 실행 실패. Playwright Chromium으로 재시도: {exc}")
    return await playwright.chromium.launch_persistent_context(**kwargs)


async def get_page(context: BrowserContext) -> Page:
    pages = context.pages
    return pages[0] if pages else await context.new_page()


async def goto_landing(page: Page, settings: Settings) -> None:
    await page.goto(settings.landing_url, wait_until="domcontentloaded", timeout=90_000)
    await page.wait_for_timeout(2500)


async def body_text(page: Page) -> str:
    try:
        return await page.locator("body").inner_text(timeout=10_000)
    except Exception:
        return ""


async def save_debug(page: Page, extra: dict[str, Any] | None = None) -> None:
    ensure_dirs()
    try:
        DEBUG_HTML.write_text(await page.content(), encoding="utf-8")
    except Exception:
        pass
    try:
        await page.screenshot(path=str(DEBUG_SCREENSHOT), full_page=True)
    except Exception:
        pass
    info = {
        "saved_at": datetime.now(KST).isoformat(),
        "url": page.url,
        "title": await page.title(),
        "extra": extra or {},
    }
    DEBUG_INFO.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")


async def fetch_same_origin_json(page: Page, url: str) -> tuple[int, str, Any | None]:
    result = await page.evaluate(
        """
        async (url) => {
          try {
            const response = await fetch(url, {
              method: 'GET',
              credentials: 'include',
              cache: 'no-store',
              headers: {'Accept': 'application/json,text/plain,*/*'}
            });
            const text = await response.text();
            return {status: response.status, text};
          } catch (error) {
            return {status: 0, text: String(error)};
          }
        }
        """,
        url,
    )
    status = int(result.get("status", 0))
    text = str(result.get("text", ""))
    parsed = None
    if text:
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
    return status, text, parsed


def with_query(url: str, **params: Any) -> str:
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.update({k: str(v) for k, v in params.items()})
    return urlunparse(parsed._replace(query=urlencode(query)))


async def fetch_products_from_endpoint(
    page: Page,
    endpoint: str,
    settings: Settings,
) -> list[dict[str, Any]]:
    products: list[dict[str, Any]] = []
    for page_number in range(1, settings.max_pages + 1):
        url = with_query(
            endpoint,
            limit=settings.page_limit,
            page=page_number,
            _ts=int(time.time()),
        )
        status, text, parsed = await fetch_same_origin_json(page, url)
        if status != 200 or not isinstance(parsed, dict):
            log(f"products.json 응답 실패: endpoint={endpoint}, page={page_number}, status={status}")
            if page_number == 1:
                snippet = text[:300].replace("\n", " ")
                log(f"응답 일부: {snippet}")
            break
        page_products = parsed.get("products")
        if not isinstance(page_products, list) or not page_products:
            break
        for item in page_products:
            if not isinstance(item, dict):
                continue
            copied = dict(item)
            copied["_source_endpoint"] = endpoint
            products.append(copied)
        log(f"{endpoint} page={page_number}: {len(page_products)}개")
        if len(page_products) < settings.page_limit:
            break
        await asyncio.sleep(settings.request_delay_seconds)
    return products


async def fetch_all_product_json(page: Page, settings: Settings) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    endpoints = settings.product_json_urls or [settings.site_base_url + "/products.json"]
    for endpoint in endpoints:
        batch = await fetch_products_from_endpoint(page, endpoint, settings)
        for item in batch:
            key = str(item.get("id") or item.get("handle") or "")
            if not key:
                continue
            source = str(item.get("_source_endpoint") or endpoint)
            if key not in merged:
                item["_source_endpoints"] = [source]
                merged[key] = item
            else:
                sources = merged[key].setdefault("_source_endpoints", [])
                if source not in sources:
                    sources.append(source)
                # Prefer the richer copy while keeping accumulated source flags.
                if len(json.dumps(item, ensure_ascii=False)) > len(json.dumps(merged[key], ensure_ascii=False)):
                    old_sources = list(sources)
                    item["_source_endpoints"] = old_sources
                    merged[key] = item
        await asyncio.sleep(settings.request_delay_seconds)
    return list(merged.values())


async def extract_product_links_from_collection(
    page: Page,
    collection_url: str,
    settings: Settings,
) -> list[str]:
    links: list[str] = []
    seen: set[str] = set()
    await page.goto(collection_url, wait_until="domcontentloaded", timeout=90_000)
    await page.wait_for_timeout(1600)
    text = await body_text(page)
    total_hint = None
    match = re.search(r"/\s*([0-9,]+)\s*件", text)
    if match:
        total_hint = int(match.group(1).replace(",", ""))
    estimated_pages = min(settings.max_pages, max(1, ((total_hint or 48) + 47) // 48))
    for number in range(1, estimated_pages + 1):
        url = with_query(collection_url, page=number)
        await page.goto(url, wait_until="domcontentloaded", timeout=90_000)
        await page.wait_for_timeout(1600)
        hrefs = await page.locator('a[href*="/products/"]').evaluate_all(
            "els => els.map(e => e.href).filter(Boolean)"
        )
        for href in hrefs:
            clean = str(href).split("?")[0].split("#")[0]
            if "/products/" not in clean or clean in seen:
                continue
            seen.add(clean)
            links.append(clean)
        await asyncio.sleep(settings.request_delay_seconds)
    log(f"DOM 링크 수집: {collection_url} → {len(links)}개")
    return links


async def discover_collection_urls(page: Page, settings: Settings) -> list[str]:
    discovered: list[str] = []
    seen: set[str] = set()
    try:
        await page.goto(settings.site_base_url, wait_until="domcontentloaded", timeout=90_000)
        await page.wait_for_timeout(1800)
        hrefs = await page.locator('a[href*="/collections/"]').evaluate_all(
            "els => els.map(e => e.href).filter(Boolean)"
        )
        for href in hrefs:
            clean = str(href).split("?")[0].split("#")[0].rstrip("/")
            if "/collections/" not in clean or clean in seen:
                continue
            tail = clean.split("/collections/", 1)[1]
            if not tail or "/" in tail or tail in {"all"}:
                continue
            seen.add(clean)
            discovered.append(clean)
            if len(discovered) >= 60:
                break
    except Exception as exc:
        log(f"컬렉션 자동 발견 실패: {type(exc).__name__}: {exc}")
    log(f"컬렉션 자동 발견: {len(discovered)}개")
    return discovered


async def extract_all_product_links(page: Page, settings: Settings) -> list[str]:
    seen: set[str] = set()
    links: list[str] = []
    collections: list[str] = []
    for url in [*settings.collection_urls, *(await discover_collection_urls(page, settings))]:
        if url not in collections:
            collections.append(url)
    for collection_url in collections:
        for link in await extract_product_links_from_collection(page, collection_url, settings):
            if link not in seen:
                seen.add(link)
                links.append(link)
    return links


async def fetch_product_from_link(page: Page, product_url: str) -> dict[str, Any] | None:
    parsed = urlparse(product_url)
    handle = parsed.path.rstrip("/").split("/")[-1]
    if not handle:
        return None
    candidates = [
        urljoin(product_url, f"/products/{handle}.js"),
        urljoin(product_url, f"/products/{handle}.json"),
    ]
    for candidate in candidates:
        status, _, parsed_data = await fetch_same_origin_json(page, candidate)
        if status != 200 or not isinstance(parsed_data, dict):
            continue
        if isinstance(parsed_data.get("product"), dict):
            product = dict(parsed_data["product"])
            product["_price_minor_units"] = candidate.endswith(".js")
            return product
        if parsed_data.get("handle") or parsed_data.get("title"):
            product = dict(parsed_data)
            product["_price_minor_units"] = candidate.endswith(".js")
            return product
    return None


async def fetch_products_from_links(page: Page, links: list[str], settings: Settings) -> list[dict[str, Any]]:
    products: list[dict[str, Any]] = []
    for index, link in enumerate(links, start=1):
        item = await fetch_product_from_link(page, link)
        if item:
            products.append(item)
        if index == 1 or index % 20 == 0 or index == len(links):
            log(f"상품 상세 수집 {index}/{len(links)} (성공 {len(products)})")
        await asyncio.sleep(settings.product_delay_seconds)
    return products


async def fetch_size_chart_from_page(
    page: Page,
    product_url: str,
) -> tuple[dict[str, Any] | None, bool]:
    """Read the product-specific サイズチャート from the authenticated product page.

    Returns (chart, checked). checked=False means the page could not be inspected and
    should be retried later. checked=True with chart=None means the page loaded but no
    product size chart was present.
    """
    try:
        await page.goto(product_url, wait_until="domcontentloaded", timeout=90_000)
        await page.wait_for_timeout(1400)
        text = await body_text(page)
        if any(message.lower() in text.lower() for message in LOGIN_REQUIRED_TEXTS):
            return None, False

        result = await page.evaluate(
            r"""
            () => {
              const clean = value => String(value || '')
                .replace(/\u00a0/g, ' ')
                .replace(/[\t\r\n ]+/g, ' ')
                .trim();
              const isChartTitle = text => {
                const t = clean(text);
                return t === 'サイズチャート' || /^size chart$/i.test(t);
              };
              const all = Array.from(document.querySelectorAll('body *'));
              const headings = all.filter(el => {
                const text = clean(el.textContent);
                if (!isChartTitle(text)) return false;
                return !Array.from(el.children).some(child => isChartTitle(child.textContent));
              });
              if (!headings.length) return {found: false};

              const parseTable = table => {
                const rawRows = Array.from(table.querySelectorAll('tr')).map(tr =>
                  Array.from(tr.querySelectorAll(':scope > th, :scope > td')).map(cell => clean(cell.textContent))
                ).filter(row => row.some(Boolean));
                if (!rawRows.length) return null;

                let headers = [];
                let rows = rawRows;
                const firstTr = table.querySelector('tr');
                const firstHasTh = !!(firstTr && firstTr.querySelector('th'));
                const firstLooksHeader = rawRows[0].some(value => /サイズ|size|cm|mm|inch|着丈|身幅|総丈|股下|横幅|高さ|重さ|ウエスト|バスト|ヒップ|袖丈|裄丈/i.test(value));
                if (firstHasTh || firstLooksHeader) {
                  headers = rawRows[0];
                  rows = rawRows.slice(1);
                }
                const width = Math.max(headers.length, ...rows.map(row => row.length));
                if (width < 2) return null;
                if (!headers.length) headers = Array.from({length: width}, (_, i) => i === 0 ? 'サイズ' : `項目 ${i}`);
                headers = headers.concat(Array(Math.max(0, width - headers.length)).fill('')).slice(0, width);
                rows = rows.map(row => row.concat(Array(Math.max(0, width - row.length)).fill('')).slice(0, width));
                return {headers, rows};
              };

              const scoreTable = (heading, table) => {
                if (!table) return -1;
                const parsed = parseTable(table);
                if (!parsed) return -1;
                const text = clean(table.textContent);
                let score = 0;
                if (/サイズ|size/i.test(text)) score += 8;
                if (/cm|mm|inch|着丈|身幅|総丈|股下|横幅|高さ|重さ|ウエスト|袖丈|裄丈/i.test(text)) score += 6;
                const position = heading.compareDocumentPosition(table);
                if (position & Node.DOCUMENT_POSITION_FOLLOWING) score += 3;
                let ancestor = heading.parentElement;
                for (let depth = 0; ancestor && depth < 8; depth++, ancestor = ancestor.parentElement) {
                  if (ancestor.contains(table)) score += Math.max(0, 6 - depth);
                }
                return score;
              };

              let best = null;
              for (const heading of headings) {
                const candidates = new Set();
                let ancestor = heading;
                for (let depth = 0; ancestor && depth < 8; depth++, ancestor = ancestor.parentElement) {
                  ancestor.querySelectorAll('table').forEach(table => candidates.add(table));
                }
                let sibling = heading.nextElementSibling;
                for (let i = 0; sibling && i < 10; i++, sibling = sibling.nextElementSibling) {
                  if (sibling.matches && sibling.matches('table')) candidates.add(sibling);
                  sibling.querySelectorAll && sibling.querySelectorAll('table').forEach(table => candidates.add(table));
                }
                const following = document.evaluate('following::table[1]', heading, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
                if (following) candidates.add(following);
                for (const table of candidates) {
                  const parsed = parseTable(table);
                  if (!parsed) continue;
                  const score = scoreTable(heading, table);
                  if (!best || score > best.score) best = {score, parsed, heading, table};
                }
              }

              if (best && best.score >= 5) {
                const noteCandidates = [];
                let node = best.table.nextElementSibling;
                for (let i = 0; node && i < 5; i++, node = node.nextElementSibling) {
                  const t = clean(node.textContent);
                  if (!t) continue;
                  if (/^(商品情報|商品の取り扱い|注意事項|Product Information|Product Care|Notes?)$/i.test(t)) break;
                  if (t.length <= 180 && /モデル|身長|着用|model|height/i.test(t)) noteCandidates.push(t);
                }
                return {
                  found: true,
                  headers: best.parsed.headers,
                  rows: best.parsed.rows,
                  note: noteCandidates[0] || ''
                };
              }

              // Fallback for layouts made entirely from div/grid elements.
              const heading = headings[0];
              const ordered = all;
              const start = ordered.indexOf(heading);
              const lines = [];
              const stopTitles = /^(商品情報|商品の取り扱い|注意事項|Product Information|Product Care|Notes?)$/i;
              for (let i = start + 1; i < ordered.length && lines.length < 30; i++) {
                const el = ordered[i];
                if (el.children.length) continue;
                const t = clean(el.textContent);
                if (!t) continue;
                if (stopTitles.test(t)) break;
                if (t.length <= 120 && !lines.includes(t)) lines.push(t);
              }
              const useful = lines.filter(t => /サイズ|cm|mm|約|\d/.test(t));
              if (useful.length >= 2) return {found: true, text_lines: useful};
              return {found: false};
            }
            """
        )
        if not isinstance(result, dict):
            return None, True
        if not result.get("found"):
            return None, True

        headers = [str(value).strip() for value in (result.get("headers") or [])]
        rows: list[list[str]] = []
        for raw_row in result.get("rows") or []:
            if not isinstance(raw_row, list):
                continue
            row = [str(value).strip() for value in raw_row]
            if any(row):
                rows.append(row)
        text_lines = [str(value).strip() for value in (result.get("text_lines") or []) if str(value).strip()]
        chart: dict[str, Any] = {
            "title": "サイズチャート",
            "headers": headers,
            "rows": rows,
            "text_lines": text_lines,
            "note": str(result.get("note") or "").strip(),
        }
        if not rows and not text_lines:
            return None, True
        return chart, True
    except Exception as exc:
        log(f"サイズチャート 조회 실패: {product_url} ({type(exc).__name__}: {exc})")
        return None, False


def image_url(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return str(value.get("src") or value.get("url") or "")
    return ""


def normalize_money(value: Any, *, minor_units: bool = False) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    try:
        number = float(str(value).replace(",", "").strip())
    except ValueError:
        return None
    # Shopify product.js exposes integer minor units. products.json normally exposes decimal strings.
    if minor_units:
        return int(round(number / 100))
    return int(round(number))


def normalize_product(raw: dict[str, Any], settings: Settings) -> dict[str, Any]:
    handle = str(raw.get("handle") or "").strip()
    product_url = urljoin(settings.site_base_url + "/", f"products/{handle}") if handle else ""

    images_raw = raw.get("images") or []
    images: list[str] = []
    for item in images_raw:
        src = image_url(item)
        if not src:
            continue
        absolute = urljoin(settings.site_base_url + "/", src)
        if absolute not in images:
            images.append(absolute)

    featured = image_url(raw.get("featured_image")) or image_url(raw.get("image"))
    if featured:
        featured = urljoin(settings.site_base_url + "/", featured)
        if featured not in images:
            images.insert(0, featured)
    elif images:
        featured = images[0]

    minor_units = bool(raw.get("_price_minor_units"))
    variants_out: list[dict[str, Any]] = []
    for variant in raw.get("variants") or []:
        available = variant.get("available") is True
        title = str(variant.get("title") or "옵션")
        if title == "Default Title":
            title = "기본 옵션"
        variants_out.append(
            {
                "id": str(variant.get("id") or ""),
                "title": title,
                "sku": str(variant.get("sku") or ""),
                "available": available,
                "price": normalize_money(variant.get("price"), minor_units=minor_units),
                "compare_at_price": normalize_money(variant.get("compare_at_price"), minor_units=minor_units),
                "option1": variant.get("option1"),
                "option2": variant.get("option2"),
                "option3": variant.get("option3"),
            }
        )

    tags = raw.get("tags") or []
    if isinstance(tags, str):
        tags = [part.strip() for part in tags.split(",") if part.strip()]

    options_raw = raw.get("options") or []
    options: list[dict[str, Any]] = []
    for index, option in enumerate(options_raw, start=1):
        if isinstance(option, dict):
            name = str(option.get("name") or f"Option {index}")
            values = option.get("values") or []
        else:
            name = str(option or f"Option {index}")
            values = []
        options.append({"name": name, "values": [str(value) for value in values]})

    description_html = str(raw.get("body_html") or raw.get("description") or "").strip()

    return {
        "id": str(raw.get("id") or handle),
        "handle": handle,
        "title": str(raw.get("title") or "상품명 없음"),
        "vendor": str(raw.get("vendor") or "ISSEY MIYAKE"),
        "product_type": str(raw.get("product_type") or raw.get("type") or ""),
        "url": product_url,
        "image": featured,
        "images": images,
        "description_html": description_html,
        "options": options,
        "tags": tags,
        "published_at": str(raw.get("published_at") or ""),
        "updated_at": str(raw.get("updated_at") or ""),
        "variants": variants_out,
        "available": any(v["available"] for v in variants_out),
        "size_chart": raw.get("size_chart") if isinstance(raw.get("size_chart"), dict) else None,
        "size_chart_checked": bool(raw.get("size_chart_checked", False)),
        "special_price": any("special-price" in str(x) for x in (raw.get("_source_endpoints") or [raw.get("_source_endpoint") or ""])),
        "source_endpoints": raw.get("_source_endpoints") or ([raw.get("_source_endpoint")] if raw.get("_source_endpoint") else []),
    }



def load_json_file(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json_file(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _parse_rate_from_csv(text: str) -> float | None:
    for row in csv.reader(text.splitlines()):
        for cell in row:
            cleaned = str(cell).strip().replace(",", "")
            try:
                value = float(cleaned)
            except ValueError:
                continue
            if 0.1 <= value <= 100:
                return value
    return None


def get_exchange_rate(settings: Settings) -> dict[str, Any]:
    now = datetime.now(KST)
    cached = load_json_file(EXCHANGE_RATE_JSON, {})
    url = settings.google_sheet_csv_url
    if url:
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(request, timeout=20) as response:
                text = response.read().decode("utf-8-sig", errors="replace")
            rate = _parse_rate_from_csv(text)
            if rate is None:
                raise ValueError("CSV에서 JPY/KRW 숫자를 찾지 못했습니다.")
            payload = {
                "rate": rate,
                "pair": "JPY/KRW",
                "source": "Google Sheets / GOOGLEFINANCE",
                "updated_at": now.strftime("%Y-%m-%d %H:%M:%S KST"),
                "is_fallback": False,
            }
            save_json_file(EXCHANGE_RATE_JSON, payload)
            return payload
        except Exception as exc:
            log(f"Google Sheets 환율 조회 실패: {type(exc).__name__}: {exc}")
            if isinstance(cached, dict) and cached.get("rate"):
                cached = dict(cached)
                cached["is_fallback"] = True
                cached["fallback_reason"] = "Google Sheets 조회 실패로 마지막 정상 환율 사용"
                return cached
    payload = {
        "rate": settings.manual_jpy_krw,
        "pair": "JPY/KRW",
        "source": "config.json 수동 환율",
        "updated_at": now.strftime("%Y-%m-%d %H:%M:%S KST"),
        "is_fallback": True,
    }
    save_json_file(EXCHANGE_RATE_JSON, payload)
    return payload


def calculate_krw(price_jpy: int | None, rate: float, settings: Settings) -> int | None:
    if price_jpy is None:
        return None
    raw = float(price_jpy) * float(rate) * (1.0 + settings.fx_markup_percent / 100.0) + settings.fixed_fee_krw
    unit = max(1, settings.price_round_unit)
    if settings.price_round_mode == "floor":
        return int(math.floor(raw / unit) * unit)
    if settings.price_round_mode == "round":
        return int(round(raw / unit) * unit)
    return int(math.ceil(raw / unit) * unit)


def plain_text_from_html(value: str) -> str:
    if not value:
        return ""
    text = re.sub(r"<\s*br\s*/?>", "\n", value, flags=re.I)
    text = re.sub(r"</\s*(p|div|li|h[1-6])\s*>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def _translation_key(kind: str, value: str) -> str:
    return kind + ":" + value.strip()


def translate_text_cached(
    value: str,
    *,
    kind: str,
    cache: dict[str, str],
    settings: Settings,
    budget: list[int],
) -> str:
    value = value.strip()
    if not value:
        return ""
    key = _translation_key(kind, value)
    if key in cache:
        return cache[key]
    if not settings.translate_enabled or GoogleTranslator is None or budget[0] <= 0:
        return value
    try:
        # GoogleTranslator has practical text-length limits. Translate paragraph chunks.
        chunks: list[str] = []
        current = ""
        for line in value.splitlines() or [value]:
            candidate = (current + "\n" + line).strip() if current else line
            if len(candidate) > 3000 and current:
                chunks.append(current)
                current = line
            else:
                current = candidate
        if current:
            chunks.append(current)
        translator = GoogleTranslator(source="auto", target="ko")
        translated = "\n".join(str(translator.translate(chunk) or chunk) for chunk in chunks)
        cache[key] = translated
        budget[0] -= 1
        return translated
    except Exception as exc:
        log(f"번역 실패({kind}): {type(exc).__name__}: {exc}")
        return value


def localize_and_price_products(
    products: list[dict[str, Any]],
    exchange_rate: dict[str, Any],
    settings: Settings,
) -> list[dict[str, Any]]:
    cache = load_json_file(TRANSLATION_CACHE, {})
    if not isinstance(cache, dict):
        cache = {}
    budget = [settings.max_new_translations_per_run]
    rate = float(exchange_rate.get("rate") or settings.manual_jpy_krw)
    for product in products:
        title_ja = str(product.get("title") or "")
        product["title_ja"] = title_ja
        product["title_ko"] = translate_text_cached(
            title_ja, kind="title", cache=cache, settings=settings, budget=budget
        )
        description_ja = plain_text_from_html(str(product.get("description_html") or ""))
        product["description_ja"] = description_ja
        if settings.translate_descriptions:
            product["description_ko"] = translate_text_cached(
                description_ja, kind="description", cache=cache, settings=settings, budget=budget
            )
        else:
            product["description_ko"] = description_ja
        for variant in product.get("variants") or []:
            variant["price_krw"] = calculate_krw(variant.get("price"), rate, settings)
            variant["compare_at_price_krw"] = calculate_krw(variant.get("compare_at_price"), rate, settings)
        prices = [v.get("price") for v in product.get("variants") or [] if isinstance(v.get("price"), int)]
        krw_prices = [v.get("price_krw") for v in product.get("variants") or [] if isinstance(v.get("price_krw"), int)]
        product["price_jpy"] = min(prices) if prices else None
        product["price_krw"] = min(krw_prices) if krw_prices else None
    save_json_file(TRANSLATION_CACHE, cache)
    log(f"한국어/가격 처리 완료: 신규 번역 {settings.max_new_translations_per_run - budget[0]}개")
    return products

def write_catalog_files(payload: dict[str, Any]) -> None:
    """Write JSON plus a script-tag-friendly copy for file:// and GitHub Pages."""
    json_text = json.dumps(payload, ensure_ascii=False, indent=2)
    CATALOG_JSON.write_text(json_text, encoding="utf-8")
    compact = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    compact = compact.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    CATALOG_JS.write_text(
        "window.__ISSEY_CATALOG__=" + compact + ";\n",
        encoding="utf-8",
    )


def load_previous_products() -> dict[str, dict[str, Any]]:
    if not CATALOG_JSON.exists():
        return {}
    try:
        payload = json.loads(CATALOG_JSON.read_text(encoding="utf-8"))
    except Exception:
        return {}
    result: dict[str, dict[str, Any]] = {}
    for product in payload.get("products") or []:
        if not isinstance(product, dict):
            continue
        key = str(product.get("handle") or product.get("id") or "")
        if key:
            result[key] = product
    return result


def merge_cached_detail(product: dict[str, Any], cached: dict[str, Any] | None) -> dict[str, Any]:
    if not cached:
        return product
    for field in ("description_html", "images", "image", "options", "product_type", "tags", "size_chart"):
        if not product.get(field) and cached.get(field):
            product[field] = cached[field]
    return product


async def enrich_product_details(
    page: Page,
    products: list[dict[str, Any]],
    settings: Settings,
) -> list[dict[str, Any]]:
    previous = load_previous_products()
    enriched: list[dict[str, Any]] = []
    fetched = 0
    chart_checked = 0
    chart_found = 0
    detail_budget = settings.max_new_detail_pages_per_run
    for index, product in enumerate(products, start=1):
        key = str(product.get("handle") or product.get("id") or "")
        cached = previous.get(key)
        product = merge_cached_detail(product, cached)
        if cached and cached.get("size_chart_checked"):
            product["size_chart_checked"] = True
        needs_fetch = not product.get("description_html") or len(product.get("images") or []) < 2
        if needs_fetch and product.get("url") and detail_budget > 0:
            detail_raw = await fetch_product_from_link(page, str(product["url"]))
            if detail_raw:
                detail = normalize_product(detail_raw, settings)
                for field in ("description_html", "images", "image", "options", "product_type", "tags"):
                    if detail.get(field):
                        product[field] = detail[field]
                if detail.get("variants"):
                    product["variants"] = detail["variants"]
                    product["available"] = detail["available"]
                fetched += 1
            detail_budget -= 1
            await asyncio.sleep(settings.product_delay_seconds)

        # サイズチャート is part of the rendered product page, not Shopify product JSON.
        # It is static product data, so collect it once and reuse the cached result.
        if not product.get("size_chart_checked") and product.get("url") and detail_budget > 0:
            chart, checked = await fetch_size_chart_from_page(page, str(product["url"]))
            if checked:
                product["size_chart_checked"] = True
                chart_checked += 1
            if chart:
                product["size_chart"] = chart
                chart_found += 1
            detail_budget -= 1
            await asyncio.sleep(settings.product_delay_seconds)
        elif product.get("size_chart"):
            chart_found += 1

        enriched.append(product)
        if index == 1 or index % 10 == 0 or index == len(products):
            log(
                f"상세정보 보강 {index}/{len(products)} "
                f"(상품 API {fetched}, サイズチャート 보유 {chart_found}, 신규 확인 {chart_checked}, 남은 상세예산 {detail_budget})"
            )
    return enriched


def product_sort_key(product: dict[str, Any]) -> tuple[Any, ...]:
    return (
        not product.get("available", False),
        product.get("vendor", ""),
        product.get("title", ""),
    )


def yen(value: int | None) -> str:
    return "-" if value is None else f"¥{value:,}"


def product_prices(product: dict[str, Any]) -> tuple[int | None, int | None]:
    variants = product.get("variants") or []
    prices = [v.get("price") for v in variants if isinstance(v.get("price"), int)]
    compares = [v.get("compare_at_price") for v in variants if isinstance(v.get("compare_at_price"), int)]
    return (min(prices) if prices else None, min(compares) if compares else None)


def esc(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def build_variant_html(product: dict[str, Any]) -> str:
    variants = product.get("variants") or []
    if not variants:
        return '<div class="empty-variant">옵션 정보 없음</div>'
    rows = []
    for variant in variants:
        available = bool(variant.get("available"))
        row_class = "variant in-stock" if available else "variant out-stock"
        status = "재고 있음" if available else "품절"
        sku = esc(variant.get("sku"))
        sku_html = f'<div class="sku">{sku}</div>' if sku else ""
        price = variant.get("price")
        price_html = f'<span class="variant-price">{esc(yen(price))}</span>' if price is not None else ""
        rows.append(
            f'<div class="{row_class}"><div><div class="variant-name">{esc(variant.get("title"))}</div>{sku_html}</div>'
            f'<div class="variant-right">{price_html}<span class="variant-status">{status}</span></div></div>'
        )
    return "".join(rows)


def build_dashboard(payload: dict[str, Any], settings: Settings) -> str:
    products = sorted(payload.get("products") or [], key=product_sort_key)
    total_products = len(products)
    available_products = sum(1 for p in products if p.get("available"))
    total_variants = sum(len(p.get("variants") or []) for p in products)
    available_variants = sum(
        1 for p in products for v in (p.get("variants") or []) if v.get("available")
    )
    brand_counts = Counter(str(p.get("vendor") or "UNKNOWN") for p in products)
    brand_buttons = [
        f'<button class="brand-button active" data-brand="ALL">전체 <span>{total_products}</span></button>'
    ]
    for brand in sorted(brand_counts):
        brand_buttons.append(
            f'<button class="brand-button" data-brand="{esc(brand)}">{esc(brand)} <span>{brand_counts[brand]}</span></button>'
        )
    cards = []
    for product in products:
        price, compare = product_prices(product)
        compare_html = ""
        if compare is not None and compare != price:
            compare_html = f'<span class="compact-compare">{esc(yen(compare))}</span>'
        image = esc(product.get("image"))
        image_html = (
            f'<img src="{image}" loading="lazy" alt="{esc(product.get("title"))}">'
            if image
            else '<div class="no-image">NO IMAGE</div>'
        )
        variants = product.get("variants") or []
        in_count = sum(1 for v in variants if v.get("available"))
        status_class = "available" if product.get("available") else "soldout"
        status_text = "재고 있음" if product.get("available") else "전체 품절"
        tag_text = ", ".join(str(t) for t in (product.get("tags") or [])[:8])
        updated = esc(product.get("updated_at"))
        local_detail_url = "detail.html?handle=" + quote(str(product.get("handle") or ""), safe="")
        share_actions = (
            f'<div class="action-pair"><button class="button copy-product-link" type="button" data-link="{esc(local_detail_url)}">상품 링크 복사</button>'
            f'<a class="button quote" href="https://blog.naver.com/pilkyu01/224353040280" target="_blank" rel="noopener">견적 문의</a></div>'
        )
        cards.append(
            f'''<article class="card" data-brand="{esc(product.get("vendor"))}" data-available="{str(bool(product.get("available"))).lower()}" data-search="{esc((str(product.get("vendor"))+' '+str(product.get("title"))+' '+tag_text).lower())}">
<a class="image-link" href="{esc(local_detail_url)}"><div class="image-wrap">{image_html}</div></a>
<button class="compact-head" type="button" aria-expanded="false">
<span class="vendor">{esc(product.get("vendor"))}</span><span class="title">{esc(product.get("title"))}</span>
<span class="compact-price">{esc(yen(price))}</span>{compare_html}
<span class="mini-row"><span class="status {status_class}">{status_text}</span><span class="stock-count">{in_count}/{len(variants)}</span></span>
</button>
<div class="detail"><div class="stock-box"><div class="stock-title">옵션별 재고</div>{build_variant_html(product)}</div>
<div class="date">updated: {updated or '-'}</div><div class="tags">{esc(tag_text)}</div><a class="button" href="{esc(local_detail_url)}">사진·설명 상세 보기</a>{share_actions}</div>
</article>'''
        )
    generated_at = esc(payload.get("generated_at") or "-")
    refresh_seconds = settings.refresh_minutes * 60
    brand_json = json.dumps(dict(brand_counts), ensure_ascii=False).replace("</", "<\\/")
    return f'''<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="{refresh_seconds}"><title>{esc(settings.site_title)}</title>
<style>
*{{box-sizing:border-box}}body{{margin:0;font-family:Arial,"Noto Sans KR",sans-serif;background:#f5f5f3;color:#222}}header{{position:sticky;top:0;z-index:20;background:rgba(255,255,255,.97);border-bottom:1px solid #ddd;padding:9px 8px;backdrop-filter:blur(8px)}}h1{{margin:0 0 7px;font-size:18px;text-align:center;letter-spacing:.02em}}.summary{{display:flex;gap:5px;overflow-x:auto;font-size:11px;color:#444;padding-bottom:3px}}.summary span{{background:#fff;border:1px solid #ddd;border-radius:999px;padding:4px 7px;white-space:nowrap}}.toolbar{{display:flex;gap:6px;align-items:center;justify-content:center;margin-top:8px;flex-wrap:wrap}}.search{{width:min(100%,330px);border:1px solid #ccc;background:#fff;border-radius:999px;padding:8px 12px;font-size:12px}}.brand-toggle,.filter-toggle{{border:1px solid #ccc;background:#fff;border-radius:999px;padding:7px 10px;font-weight:bold;cursor:pointer;font-size:12px}}.filter-toggle.active{{background:#167a2e;color:#fff;border-color:#167a2e}}.brand-panel{{display:none;margin:9px auto 0;background:#fff;border:1px solid #ddd;border-radius:14px;box-shadow:0 10px 30px rgba(0,0,0,.08);padding:9px;max-height:45vh;overflow:auto}}.brand-panel.open{{display:grid;grid-template-columns:repeat(2,1fr);gap:7px}}.brand-button{{border:1px solid #ddd;background:#fafafa;border-radius:10px;padding:8px;text-align:left;cursor:pointer;font-weight:bold;color:#222;font-size:11px}}.brand-button span{{float:right;color:#777;font-weight:normal}}.brand-button.active{{background:#222;color:#fff;border-color:#222}}.brand-button.active span{{color:#ddd}}.current-filter{{text-align:center;margin-top:7px;font-size:12px;color:#333;font-weight:bold}}.notice{{font-size:10px;color:#777;text-align:center;padding:7px 10px 0;line-height:1.45}}.grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:7px;padding:7px}}.card{{background:#fff;border:1px solid #ddd;border-radius:10px;overflow:hidden;box-shadow:0 1px 5px rgba(0,0,0,.05)}}.card.hidden{{display:none}}.image-link{{display:block;text-decoration:none;color:inherit}}.image-wrap{{background:#eee;aspect-ratio:5/7;overflow:hidden}}img{{width:100%;height:100%;object-fit:cover;display:block}}.no-image{{display:grid;place-items:center;height:100%;font-size:10px;color:#888}}.compact-head{{width:100%;border:0;background:#fff;text-align:left;padding:6px;cursor:pointer}}.vendor{{display:block;color:#555;font-size:9px;font-weight:bold;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}.title{{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;min-height:29px;font-size:10.5px;line-height:1.35;font-weight:bold;margin-top:4px}}.compact-price{{display:block;font-size:13px;font-weight:800;margin-top:5px;color:#111;letter-spacing:-.02em}}.compact-compare{{display:block;font-size:10px;color:#777;text-decoration:line-through;margin-top:2px}}.mini-row{{display:flex;justify-content:space-between;align-items:center;gap:5px;margin-top:6px}}.status{{display:inline-block;padding:2px 5px;border-radius:999px;font-size:9px;font-weight:bold}}.available{{background:#e8f7e8;color:#167a2e}}.soldout{{background:#f7e8e8;color:#a82222}}.stock-count{{font-size:10px;font-weight:bold;background:#f0f0ee;border-radius:999px;padding:2px 5px;white-space:nowrap}}.detail{{display:none;padding:0 7px 8px;border-top:1px solid #eee}}.card.open .detail{{display:block}}.stock-box{{border:1px solid #e1e1df;background:#fafaf8;border-radius:9px;padding:7px;margin:8px 0}}.stock-title{{font-size:11px;font-weight:bold;margin-bottom:5px;color:#333}}.variant{{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:5px;align-items:center;border-top:1px solid #e8e8e6;padding:6px 0;font-size:11px}}.variant:first-of-type{{border-top:0}}.variant-name{{line-height:1.3;overflow-wrap:anywhere}}.sku{{color:#888;font-size:9px;margin-top:2px}}.variant-right{{display:flex;flex-direction:column;align-items:flex-end;gap:3px}}.variant-price{{font-size:9px;color:#555}}.variant-status{{border-radius:999px;padding:3px 6px;font-weight:bold;white-space:nowrap;font-size:10px}}.in-stock .variant-status{{background:#dcf5dc;color:#137225}}.out-stock{{color:#999}}.out-stock .variant-status{{background:#eee;color:#777}}.empty-variant{{font-size:11px;color:#888}}.date{{color:#888;font-size:9px;margin:3px 0}}.tags{{color:#777;font-size:10px;line-height:1.35}}.action-pair{{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-top:9px}}.action-pair .button{{margin-top:0}}.button{{display:block;width:100%;text-align:center;margin-top:9px;padding:8px;border:0;border-radius:8px;background:#222;color:#fff;text-decoration:none;font:700 12px Arial,"Noto Sans KR",sans-serif;cursor:pointer}}.button.quote{{background:#03c75a}}.button.secondary{{background:#fff;color:#222;border:1px solid #bbb}}footer{{padding:18px 12px 26px;text-align:center;color:#777;font-size:10px;line-height:1.5}}@media(min-width:800px){{.grid{{grid-template-columns:repeat(5,1fr);max-width:1200px;margin:auto}}.brand-panel{{max-width:850px;grid-template-columns:repeat(4,1fr)}}}}@media(max-width:370px){{.grid{{grid-template-columns:repeat(2,1fr)}}}}
</style></head><body>
<header><h1>{esc(settings.site_title)}</h1><div class="summary"><span>총 {total_products}개</span><span>재고상품 {available_products}개</span><span>옵션 재고 {available_variants}/{total_variants}</span><span>{generated_at}</span><span>{settings.refresh_minutes}분 새로고침</span></div><div class="toolbar"><input id="search" class="search" type="search" placeholder="상품명·브랜드 검색"><button id="brandToggle" class="brand-toggle" type="button">브랜드 ▾</button><button id="availableToggle" class="filter-toggle" type="button">재고만 보기</button></div><div id="brandPanel" class="brand-panel">{''.join(brand_buttons)}</div><div id="currentFilter" class="current-filter">전체 브랜드 · {total_products}개</div></header>
<div class="notice">마지막 수집 시각 기준의 비공식 참고 페이지입니다. 실제 재고와 가격은 견적 확인 시점에 달라질 수 있습니다.</div>
<main id="grid" class="grid">{''.join(cards)}</main><footer>상품 이미지와 상표의 권리는 각 권리자에게 있습니다. 로그인 쿠키·비밀번호·개인정보는 이 페이지에 포함되지 않습니다.</footer>
<script>
const brandCounts={brand_json};let activeBrand='ALL',availableOnly=false;const cards=[...document.querySelectorAll('.card')];const search=document.getElementById('search');const panel=document.getElementById('brandPanel');const brandToggle=document.getElementById('brandToggle');const availableToggle=document.getElementById('availableToggle');const currentFilter=document.getElementById('currentFilter');
function applyFilters(){{const q=search.value.trim().toLowerCase();let visible=0;cards.forEach(card=>{{const brandOK=activeBrand==='ALL'||card.dataset.brand===activeBrand;const stockOK=!availableOnly||card.dataset.available==='true';const searchOK=!q||card.dataset.search.includes(q);const show=brandOK&&stockOK&&searchOK;card.classList.toggle('hidden',!show);if(show)visible++;}});currentFilter.textContent=(activeBrand==='ALL'?'전체 브랜드':activeBrand)+' · '+visible+'개';}}
async function copyLink(button){{const link=new URL(button.dataset.link,location.href).href;try{{if(navigator.clipboard&&window.isSecureContext){{await navigator.clipboard.writeText(link);}}else{{const area=document.createElement('textarea');area.value=link;area.setAttribute('readonly','');area.style.position='fixed';area.style.opacity='0';document.body.appendChild(area);area.select();if(!document.execCommand('copy'))throw new Error('copy failed');area.remove();}}const original=button.textContent;button.textContent='복사 완료';setTimeout(()=>button.textContent=original,1500);}}catch(error){{window.prompt('아래 상품 링크를 복사하세요.',link);}}}}
brandToggle.addEventListener('click',()=>panel.classList.toggle('open'));availableToggle.addEventListener('click',()=>{{availableOnly=!availableOnly;availableToggle.classList.toggle('active',availableOnly);applyFilters();}});search.addEventListener('input',applyFilters);document.querySelectorAll('.brand-button').forEach(btn=>btn.addEventListener('click',()=>{{activeBrand=btn.dataset.brand;document.querySelectorAll('.brand-button').forEach(b=>b.classList.toggle('active',b===btn));panel.classList.remove('open');applyFilters();}}));document.querySelectorAll('.compact-head').forEach(btn=>btn.addEventListener('click',()=>{{const card=btn.closest('.card');card.classList.toggle('open');btn.setAttribute('aria-expanded',card.classList.contains('open'));}}));document.querySelectorAll('.copy-product-link').forEach(btn=>btn.addEventListener('click',()=>copyLink(btn)));
</script></body></html>'''


async def collect(settings: Settings, *, headless: bool | None = None) -> dict[str, Any]:
    ensure_dirs()
    actual_headless = settings.headless_collect if headless is None else headless
    async with async_playwright() as playwright:
        context = await launch_context(playwright, settings, headless=actual_headless)
        page = await get_page(context)
        try:
            log("이세이 미야케 로그인 상태 확인")
            await goto_landing(page, settings)
            text = await body_text(page)
            login_message = next((msg for msg in LOGIN_REQUIRED_TEXTS if msg.lower() in text.lower()), None)
            if login_message:
                await save_debug(page, {"reason": "login_required"})
                raise CatalogError(
                    "로그인 상태가 확인되지 않았습니다. 02_LOGIN.bat을 다시 실행한 뒤 상품 페이지가 보이는 상태로 저장하세요."
                )

            products = await fetch_all_product_json(page, settings)
            method = "authenticated_multi_products_json"
            if not products:
                links = await extract_all_product_links(page, settings)
                if not links:
                    await save_debug(page, {"reason": "no_products_or_links"})
                    raise CatalogError(
                        "전체 상품 API와 설정된 컬렉션 링크에서 상품을 찾지 못했습니다. 07_DIAGNOSE.bat을 실행하세요."
                    )
                products = await fetch_products_from_links(page, links, settings)
                method = "collection_dom_links_and_product_json"

            normalized = [normalize_product(item, settings) for item in products]
            normalized = [p for p in normalized if p.get("handle") or p.get("title")]
            normalized = await enrich_product_details(page, normalized, settings)
            if not normalized:
                await save_debug(page, {"reason": "normalization_empty", "raw_count": len(products)})
                raise CatalogError("수집 데이터는 있었지만 상품으로 변환하지 못했습니다.")
        except Exception:
            try:
                await save_debug(page, {"command": "collect"})
            except Exception:
                pass
            raise
        finally:
            await context.close()

    exchange_rate = await asyncio.to_thread(get_exchange_rate, settings)
    normalized = await asyncio.to_thread(localize_and_price_products, normalized, exchange_rate, settings)
    normalized.sort(key=product_sort_key)
    payload = {
        "generated_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S KST"),
        "source": settings.site_base_url,
        "collection_method": method,
        "product_count": len(normalized),
        "exchange_rate": exchange_rate,
        "pricing": {
            "markup_percent": settings.fx_markup_percent,
            "fixed_fee_krw": settings.fixed_fee_krw,
            "round_unit": settings.price_round_unit,
            "round_mode": settings.price_round_mode,
        },
        "quote_url": settings.quote_url,
        "site_title": settings.site_title,
        "products": normalized,
    }
    write_catalog_files(payload)
    log(f"완료: 전체 상품 {len(normalized)}개, catalog.json/catalog.js 생성")
    return payload


async def login(settings: Settings) -> None:
    ensure_dirs()
    async with async_playwright() as playwright:
        context = await launch_context(playwright, settings, headless=False)
        page = await get_page(context)
        try:
            await goto_landing(page, settings)
            print("\n브라우저에서 이세이 미야케에 직접 로그인하세요.")
            print("상품 목록과 상세페이지가 정상적으로 보이면 이 창으로 돌아와 Enter를 누르세요.\n")
            await asyncio.to_thread(input, "로그인 완료 후 Enter: ")
            await goto_landing(page, settings)
            text = await body_text(page)
            if not any(msg.lower() in text.lower() for msg in LOGIN_REQUIRED_TEXTS):
                log("로그인 프로필 저장 완료")
            else:
                await save_debug(page, {"reason": "login_verify_failed"})
                raise CatalogError("로그인이 확인되지 않았습니다. 상품이 보이는 상태에서 다시 실행하세요.")
        finally:
            await context.close()


async def purchase_assist(settings: Settings, handle: str, variant_query: str) -> None:
    payload = load_json_file(CATALOG_JSON, {})
    products = payload.get("products") or [] if isinstance(payload, dict) else []
    product = next((p for p in products if str(p.get("handle")) == handle or str(p.get("id")) == handle), None)
    if not product:
        raise CatalogError("상품을 찾지 못했습니다. 먼저 03_TEST_COLLECTION.bat을 실행하고 정확한 handle을 입력하세요.")
    variants = product.get("variants") or []
    selected = None
    if variant_query:
        q = variant_query.lower().strip()
        selected = next(
            (v for v in variants if q in str(v.get("title") or "").lower() or q == str(v.get("id") or "")),
            None,
        )
    if selected is None and variants:
        selected = next((v for v in variants if v.get("available")), variants[0])

    print("\n==============================================")
    print("PURCHASE ASSISTANT - FINAL CHECK REQUIRED")
    print("==============================================")
    print("상품:", product.get("title_ko") or product.get("title"))
    print("원문:", product.get("title_ja") or product.get("title"))
    if selected:
        print("선택 옵션:", selected.get("title"))
        print("현재 수집 재고:", "재고 있음" if selected.get("available") else "품절")
        print("예상 원화가:", f"{int(selected.get('price_krw') or 0):,}원" if selected.get("price_krw") else "-")
    print("\n브라우저에서 실제 재고와 가격을 다시 확인한 뒤 직접 PayPal 결제하세요.")
    print("이 프로그램은 장바구니 추가, PayPal 로그인, 결제 승인, 최종 주문을 자동 실행하지 않습니다.\n")

    async with async_playwright() as playwright:
        context = await launch_context(playwright, settings, headless=False)
        page = await get_page(context)
        try:
            await page.goto(str(product.get("url") or settings.landing_url), wait_until="domcontentloaded", timeout=90_000)
            await page.wait_for_timeout(1500)
            await asyncio.to_thread(input, "확인을 마치면 Enter를 눌러 브라우저를 닫으세요: ")
        finally:
            await context.close()


def run_git(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=check,
    )


def publish(settings: Settings) -> bool:
    if not (ROOT / ".git").exists():
        raise CatalogError("Git 저장소가 연결되지 않았습니다. 먼저 04_CONNECT_GITHUB.bat을 실행하세요.")
    remote = run_git(["remote", "get-url", "origin"], check=False)
    if remote.returncode != 0:
        raise CatalogError("GitHub origin 주소가 없습니다. 04_CONNECT_GITHUB.bat을 다시 실행하세요.")
    public_files = [
        "index.html",
        "detail.html",
        "order.html",
        ".nojekyll",
        "data/catalog.json",
        "data/catalog.js",
        "data/exchange_rate.json",
    ]
    run_git(["add", *public_files])
    status = run_git(["status", "--porcelain", "--", *public_files])
    if not status.stdout.strip():
        log("GitHub에 올릴 변경 없음")
        return False
    message = "Update ISSEY Korea catalog " + datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")
    commit = run_git(["commit", "-m", message], check=False)
    if commit.returncode != 0:
        raise CatalogError(f"git commit 실패:\n{commit.stdout}\n{commit.stderr}")
    pushed = run_git(["push", "origin", settings.git_branch], check=False)
    if pushed.returncode != 0:
        raise CatalogError(f"git push 실패:\n{pushed.stdout}\n{pushed.stderr}")
    log("GitHub 업로드 완료")
    return True


async def monitor(settings: Settings, do_publish: bool) -> None:
    interval = max(60, settings.refresh_minutes * 60)
    log(f"자동 갱신 시작: {settings.refresh_minutes}분 간격")
    log("종료하려면 이 창에서 Ctrl+C를 누르세요.")
    while True:
        started = time.monotonic()
        try:
            await collect(settings)
            if do_publish:
                publish(settings)
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            log(f"업데이트 실패: {type(exc).__name__}: {exc}")
            log("마지막 정상 index.html은 유지됩니다.")
        elapsed = time.monotonic() - started
        sleep_for = max(5, interval - elapsed)
        log(f"다음 확인까지 약 {int(sleep_for)}초")
        await asyncio.sleep(sleep_for)


async def diagnose(settings: Settings) -> None:
    try:
        await collect(settings, headless=False)
        log("진단 수집 성공")
    except Exception as exc:
        log(f"진단 수집 실패: {exc}")
        log(f"디버그 파일: {DEBUG_HTML}")
        log(f"스크린샷: {DEBUG_SCREENSHOT}")
        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ISSEY MIYAKE Korea catalog and order assistant")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("login", help="직접 로그인하고 브라우저 프로필 저장")
    collect_parser = sub.add_parser("collect", help="한 번 전체 상품 수집")
    collect_parser.add_argument("--publish", action="store_true")
    monitor_parser = sub.add_parser("monitor", help="주기적으로 전체 상품 수집")
    monitor_parser.add_argument("--publish", action="store_true")
    sub.add_parser("publish", help="현재 정적 사이트와 데이터만 GitHub에 업로드")
    sub.add_parser("diagnose", help="브라우저를 보이게 열고 진단")
    purchase_parser = sub.add_parser("purchase-assist", help="공식 상품페이지를 열고 결제 전 직접 확인")
    purchase_parser.add_argument("--handle", required=True)
    purchase_parser.add_argument("--variant", default="")
    return parser.parse_args()


def main() -> int:
    os.chdir(ROOT)
    settings = load_settings()
    args = parse_args()
    try:
        if args.command == "login":
            asyncio.run(login(settings))
        elif args.command == "collect":
            asyncio.run(collect(settings))
            if args.publish:
                publish(settings)
        elif args.command == "monitor":
            asyncio.run(monitor(settings, args.publish))
        elif args.command == "publish":
            publish(settings)
        elif args.command == "diagnose":
            asyncio.run(diagnose(settings))
        elif args.command == "purchase-assist":
            asyncio.run(purchase_assist(settings, args.handle, args.variant))
        return 0
    except KeyboardInterrupt:
        log("사용자가 종료했습니다.")
        return 0
    except CatalogError as exc:
        log(f"오류: {exc}")
        return 2
    except Exception as exc:
        log(f"예상하지 못한 오류: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
