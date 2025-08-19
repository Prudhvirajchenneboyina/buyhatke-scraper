# -*- coding: utf-8 -*-
"""
BuyHatke scraper — search -> numbered menu -> user picks -> show offers -> exit.

- Uses demjson3 to parse embedded JavaScript-like data.
- Merchant inferred from URL domain (mapped to clean names).
"""

import re
import sys
import requests
import demjson3
from bs4 import BeautifulSoup
from urllib.parse import urlparse

# ---------- CONFIG ----------

HEADERS = {
    "Referer": "https://buyhatke.com/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/128.0.0.0 Safari/537.36"
    ),
}
TIMEOUT = 20

DOMAIN_MAP = {
    "amazon.in": "Amazon",
    "flipkart.com": "Flipkart",
    "croma.com": "Croma",
    "jiomart.com": "JioMart",
    "reliancedigital.in": "Reliance Digital",
    "vijaysales.com": "Vijay Sales",
    "apple.com": "Apple Store",
    "bigbasket.com": "BigBasket",
    "shopsy.in": "Shopsy",
    "paiinternational.in": "Pai International",
}


# ---------- UTILS ----------

def normalize_slug(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s


def extract_js_array(text: str, start_bracket_idx: int) -> str:
    """Extract a bracket-balanced JS array starting at '['."""
    if text[start_bracket_idx] != "[":
        raise ValueError("extract_js_array must start at '['")

    i = start_bracket_idx
    depth = 0
    in_string = False
    string_delim = ""
    escaped = False

    while i < len(text):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == string_delim:
                in_string = False
        else:
            if ch in ("'", '"'):
                in_string = True
                string_delim = ch
            elif ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    return text[start_bracket_idx : i + 1]
        i += 1

    raise ValueError("Unterminated JS array")


def extract_array_for_key(html: str, key: str) -> str | None:
    pos = html.find(key)
    if pos == -1:
        return None
    colon = html.find(":", pos)
    if colon == -1:
        return None
    m = re.search(r"\[", html[colon:])
    if not m:
        return None
    abs_idx = colon + m.start()
    return extract_js_array(html, abs_idx)


def rupee(n: int | float | None) -> str | None:
    if n is None:
        return None
    try:
        return f"₹{int(n):,}"
    except Exception:
        return str(n)


def clean_price_to_int(price_str: str | None) -> int:
    if not price_str:
        return 10**12
    digits = re.sub(r"[^\d]", "", price_str)
    return int(digits) if digits else 10**12


def domain_to_merchant(url: str, fallback: str = "Unknown") -> str:
    if not url:
        return fallback
    domain = urlparse(url).netloc.lower()
    domain = domain.replace("www.", "")
    return DOMAIN_MAP.get(domain, domain.split(".")[0].capitalize())


# ---------- SCRAPERS ----------

def scrape_buyhatke_search(query: str) -> list[dict]:
    url = "https://buyhatke.com/search"
    params = {"product": query, "x-sveltekit-invalidated": "001"}

    r = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    html = r.text

    arr_text = extract_array_for_key(html, "SearchProductsList")
    if not arr_text:
        raise RuntimeError("SearchProductsList not found in search page.")

    products = demjson3.decode(arr_text)

    results = []
    for p in products:
        prod_name = p.get("prod")
        prod_search = normalize_slug(p.get("prodSearch") or (prod_name or ""))
        pos = p.get("pos")
        internal_pid = p.get("internalPid")

        redirect_url = f"https://buyhatke.com/{prod_search}-price-in-india-{pos}-{internal_pid}"

        results.append(
            {
                "title": prod_name,
                "price": p.get("price"),
                "redirect_url": redirect_url,
            }
        )
    return results


def scrape_product_offers(product_url: str) -> list[dict]:
    r = requests.get(product_url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    offers: list[dict] = []

    for script in soup.find_all("script"):
        text = (script.string or script.text or "").strip()
        if "dealsData" not in text:
            continue

        idx = 0
        while True:
            idx = text.find("dealsData", idx)
            if idx == -1:
                break
            m = re.search(r"\[", text[idx:])
            if not m:
                idx += 9
                continue
            abs_idx = idx + m.start()

            try:
                arr_text = extract_js_array(text, abs_idx)
            except Exception:
                idx += 9
                continue

            try:
                deals = demjson3.decode(arr_text)
            except Exception:
                idx += 9
                continue

            for item in deals:
                price_val = item.get("price")
                link = item.get("link")
                merchant = domain_to_merchant(link)

                offers.append(
                    {
                        "merchant": merchant,
                        "product": item.get("prod"),
                        "price": rupee(price_val),
                        "url": link,
                    }
                )

            idx = abs_idx + len(arr_text)

    return offers


# ---------- MAIN ----------

def main():
    query = input("Enter product name: ").strip()
    if not query:
        print("No product entered. Exiting.")
        sys.exit(0)

    products = scrape_buyhatke_search(query)

    if not products:
        print("No products found.")
        sys.exit(0)

    print("\nAvailable Products:\n")
    for i, p in enumerate(products, 1):
        print(f"{i}. {p['title']}")

    try:
        choice = int(input("\nEnter the number of the product you want to view: ").strip())
    except ValueError:
        print("Invalid choice.")
        sys.exit(0)

    if not (1 <= choice <= len(products)):
        print("Invalid choice!")
        sys.exit(0)

    selected = products[choice - 1]
    print(f"\nYou selected: {selected['title']}")
    #print(f"Opening: {selected['redirect_url']}\n")

    offers = scrape_product_offers(selected["redirect_url"])

    if not offers:
        print("No offers found.")
        sys.exit(0)

    print("Available Offers:\n")
    for off in offers:
        print(f"{off['merchant']}: {off['price']}  ({off['url']})")

    cheapest = min(offers, key=lambda x: clean_price_to_int(x["price"]))
    if cheapest and cheapest["price"]:
        print(f"\n👉 Lowest Price: {cheapest['merchant']} at {cheapest['price']}")

    # Exit right after printing
    sys.exit(0)


if __name__ == "__main__":
    main()
