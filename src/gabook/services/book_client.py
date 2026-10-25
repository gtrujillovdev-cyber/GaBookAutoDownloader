import os
import re
import uuid
import logging
import requests
from bs4 import BeautifulSoup
from typing import List, Dict, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin, urlparse, quote
from gabook.config import HEADERS, LANG_MAP, DOWNLOADS_DIR, MAX_DOWNLOAD_BYTES

logger = logging.getLogger(__name__)

def clean_filename(name: Optional[str]) -> str:
    """Sanitize string to be safe as a filename."""
    if not name:
        return ""
    return re.sub(r'[\/*?:"<>|]', "", str(name)).strip()

def get_book_synopsis(title: str, author: str = "") -> Optional[str]:
    """
    Retrieves a rich, accurate Spanish synopsis using Wikipedia ES with smart fallback.
    Avoids short or poor English summaries.
    """
    headers = {"User-Agent": "GaBookBot/2.0 (https://github.com/gtrujillovdev-cyber/GaBookAutoDownloader)"}

    # 1. Clean title for Wikipedia query
    clean_t = re.sub(r'[\(\[\{].*?[\)\]\}]', '', title).strip()
    clean_t_no_art = re.sub(r'^(el|la|los|las|un|una|unos|unas)\s+', '', clean_t, flags=re.IGNORECASE).strip()

    search_candidates = [
        f"{clean_t} (novela)",
        f"{clean_t} (libro)",
        clean_t
    ]
    if clean_t_no_art and clean_t_no_art != clean_t:
        search_candidates.append(f"{clean_t_no_art} (novela)")
        search_candidates.append(clean_t_no_art)

    for cand in search_candidates:
        try:
            url = f"https://es.wikipedia.org/api/rest_v1/page/summary/{requests.utils.quote(cand)}"
            r = requests.get(url, headers=headers, timeout=2.5)
            if r.status_code == 200:
                data = r.json()
                if data.get("type") == "standard" and data.get("extract"):
                    extract = data["extract"].strip()
                    # Filter out useless disambiguation extracts
                    if not extract.lower().startswith("puede referirse a") and not extract.lower().startswith("hace referencia a"):
                        clean_text = re.sub(r'[*_`\[\]<>]', '', extract)
                        if len(clean_text) > 420:
                            clean_text = clean_text[:417] + "…"
                        return clean_text
        except Exception:
            pass

    # 2. Fallback to OpenLibrary if Wikipedia has no match
    try:
        q = f"{clean_t} {author}".strip()[:40]
        url = f"https://openlibrary.org/search.json?q={requests.utils.quote(q)}&limit=1"
        r = requests.get(url, timeout=2.5)
        if r.status_code == 200:
            docs = r.json().get("docs", [])
            if docs:
                doc = docs[0]
                first_sent = doc.get("first_sentence")
                if first_sent:
                    raw_text = first_sent.get("value", "") if isinstance(first_sent, dict) else (first_sent[0] if isinstance(first_sent, list) else str(first_sent))
                    if raw_text:
                        clean_text = re.sub(r'[*_`\[\]<>]', '', raw_text).strip()
                        return clean_text[:350] + ("…" if len(clean_text) > 350 else "")

                work_key = doc.get("key")
                if work_key:
                    w_resp = requests.get(f"https://openlibrary.org{work_key}.json", timeout=2.0)
                    if w_resp.status_code == 200:
                        desc = w_resp.json().get("description")
                        raw_desc = desc.get("value", "") if isinstance(desc, dict) else str(desc or "")
                        if raw_desc:
                            clean_desc = re.sub(r'[*_`\[\]<>]', '', raw_desc).strip()
                            if len(clean_desc) > 350:
                                clean_desc = clean_desc[:347] + "…"
                            return clean_desc
    except Exception:
        pass

    return None

def get_book_cover(title: str, author: str = "") -> Optional[str]:
    """Retrieves high quality book cover image URL from Wikipedia or OpenLibrary."""
    headers = {"User-Agent": "GaBookBot/2.0 (https://github.com/gtrujillovdev-cyber/GaBookAutoDownloader)"}
    clean_t = re.sub(r'[\(\[\{].*?[\)\]\}]', '', title).strip()

    # 1. Check Wikipedia thumbnail
    for cand in [f"{clean_t} (novela)", f"{clean_t} (libro)", clean_t]:
        try:
            url = f"https://es.wikipedia.org/api/rest_v1/page/summary/{requests.utils.quote(cand)}"
            r = requests.get(url, headers=headers, timeout=2.0)
            if r.status_code == 200:
                data = r.json()
                thumb = data.get("thumbnail", {}).get("source")
                if thumb:
                    return thumb
        except Exception:
            pass

    # 2. OpenLibrary large cover
    try:
        q = f"{clean_t} {author}".strip()[:40]
        url = f"https://openlibrary.org/search.json?q={requests.utils.quote(q)}&limit=1"
        r = requests.get(url, timeout=2.5)
        if r.status_code == 200:
            docs = r.json().get("docs", [])
            if docs and docs[0].get("cover_i"):
                cover_id = docs[0]["cover_i"]
                return f"https://covers.openlibrary.org/b/id/{cover_id}-L.jpg"
    except Exception:
        pass

    return None

def parse_query_and_language(raw_text: str, default_lang: Optional[str] = "Spanish") -> Tuple[str, Optional[str]]:
    """Parses natural language queries to detect requested language and cleans prefixes."""
    text = raw_text.strip()
    target_lang = default_lang
    clean_query = text

    bracket_match = re.search(r'[\[\(]([a-zA-ZáéíóúñÁÉÍÓÚÑ]+)[\]\)]$', text)
    if bracket_match:
        lang_token = bracket_match.group(1).lower()
        if lang_token in LANG_MAP:
            clean_query = text[:bracket_match.start()].strip()
            target_lang = LANG_MAP[lang_token]

    elif re.search(r'\s+en\s+([a-zA-ZáéíóúñÁÉÍÓÚÑ]+)$', text, re.IGNORECASE):
        en_match = re.search(r'\s+en\s+([a-zA-ZáéíóúñÁÉÍÓÚÑ]+)$', text, re.IGNORECASE)
        lang_token = en_match.group(1).lower()
        if lang_token in LANG_MAP:
            clean_query = text[:en_match.start()].strip()
            target_lang = LANG_MAP[lang_token]

    else:
        words = text.split()
        if len(words) > 1:
            last_word = words[-1].lower()
            if last_word in LANG_MAP:
                clean_query = " ".join(words[:-1]).strip()
                target_lang = LANG_MAP[last_word]

    clean_query = re.sub(r'^(libros|novelas|cuentos|obras)\s+(de|sobre)\s+', '', clean_query, flags=re.IGNORECASE).strip()
    return clean_query, target_lang

def fetch_libgen_page(base_url: str, query: str, page: int) -> List[Dict]:
    """Fetches a specific page of results from a Libgen mirror."""
    params = {
        "req": query,
        "page": page,
        "res": 100
    }
    results = []
    try:
        resp = requests.get(base_url, params=params, headers=HEADERS, timeout=8)
        if resp.status_code != 200:
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        tables = soup.find_all("table")
        if len(tables) < 2:
            return []

        rows = tables[1].find_all("tr")[1:]
        for row in rows:
            tds = row.find_all("td")
            if len(tds) < 9:
                continue

            ext = tds[7].get_text(strip=True).lower()
            if ext != "epub":
                continue

            title_td = tds[0]
            title_a = title_td.find("a", href=lambda h: h and "item/detail" in h) or title_td.find("a")
            title = title_a.get_text(strip=True) if title_a else title_td.get_text(strip=True)
            title = re.sub(r'\s+', ' ', title).strip()

            author = tds[1].get_text(strip=True) or "Autor desconocido"
            year = tds[3].get_text(strip=True)
            lang = tds[4].get_text(strip=True) or "Unknown"
            size = tds[6].get_text(strip=True)

            mirror_links = [a.get("href") for a in tds[8].find_all("a") if a.get("href")]
            if not mirror_links:
                continue

            results.append({
                "title": title,
                "author": author,
                "year": year,
                "lang": lang,
                "size": size,
                "mirrors": mirror_links,
                "base": f"{urlparse(base_url).scheme}://{urlparse(base_url).netloc}",
                "source": "libgen"
            })
    except Exception:
        pass
    return results

def search_libgen(query: str, max_results: int = 30) -> List[Dict]:
    """Searches Libgen across prioritized mirrors concurrently with fast response."""
    base_url = "https://libgen.li/index.php"
    results = []
    seen = set()

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(fetch_libgen_page, base_url, query, p) for p in [1, 2, 3]]
        for f in futures:
            try:
                page_books = f.result()
                for b in page_books:
                    key = (b["title"].lower()[:30], b["author"].lower()[:20])
                    if key not in seen:
                        seen.add(key)
                        results.append(b)
            except Exception:
                pass

    # If first mirror yields very few, try backup mirror with limit 2 pages
    if len(results) < 5:
        backup_url = "https://libgen.vg/index.php"
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(fetch_libgen_page, backup_url, query, p) for p in [1, 2]]
            for f in futures:
                try:
                    page_books = f.result()
                    for b in page_books:
                        key = (b["title"].lower()[:30], b["author"].lower()[:20])
                        if key not in seen:
                            seen.add(key)
                            results.append(b)
                except Exception:
                    pass

    return results[:max_results]

def search_archive_org(query: str, max_results: int = 25) -> List[Dict]:
    """Searches Internet Archive (archive.org) for open EPUBs across an expanded range."""
    url = "https://archive.org/advancedsearch.php"
    params = {
        "q": f"({query}) format:EPUB -access-restricted-item:true",
        "fl[]": "identifier,title,creator,year,language",
        "sort[]": "downloads desc",
        "rows": max_results,
        "page": 1,
        "output": "json"
    }
    results = []
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=6)
        if r.status_code == 200:
            docs = r.json().get("response", {}).get("docs", [])
            for d in docs:
                ident = d.get("identifier")
                if not ident:
                    continue
                raw_title = d.get("title", "Sin título")
                # Archive.org titles often contain "Spanish title: English title 1st ed."
                # Keep only the part before the first colon if it's meaningful
                if ":" in raw_title:
                    before_colon = raw_title.split(":")[0].strip()
                    title = before_colon if len(before_colon) >= 10 else raw_title[:80]
                else:
                    title = raw_title[:80]
                creator = d.get("creator", "Desconocido")
                if isinstance(creator, list):
                    creator = ", ".join(creator)
                year = str(d.get("year", ""))
                lang_code = d.get("language", "es")
                lang_name = "Spanish" if lang_code in ["spa", "spanish", "es"] else "English"
                direct_url = f"https://archive.org/download/{ident}/{ident}.epub"

                results.append({
                    "title": title,
                    "author": creator,
                    "year": year,
                    "lang": lang_name,
                    "size": "~1 MB",
                    "direct_url": direct_url,
                    "source": "archive_org"
                })
    except Exception as e:
        logger.warning(f"Archive.org search error: {e}")

    return results

def search_openlibrary(query: str, max_results: int = 15) -> List[Dict]:
    """Searches OpenLibrary for readable full-text EPUB editions."""
    url = f"https://openlibrary.org/search.json?q={requests.utils.quote(query)}&has_fulltext=true&limit={max_results}"
    results = []
    try:
        r = requests.get(url, headers=HEADERS, timeout=5)
        if r.status_code == 200:
            docs = r.json().get("docs", [])
            for d in docs:
                # Skip lending-only items (not freely downloadable)
                if d.get("lending_edition_s") or d.get("lending_identifier_s"):
                    continue
                ia_list = d.get("ia", [])
                if not ia_list:
                    continue
                ia_id = ia_list[0]
                title = d.get("title", "Sin título")
                authors = d.get("author_name", ["Autor desconocido"])
                author = authors[0] if authors else "Autor desconocido"
                year = str(d.get("first_publish_year", ""))
                langs = d.get("language", [])
                lang_name = "Spanish" if any(l in ["spa", "es", "spanish"] for l in langs) else "English"
                direct_url = f"https://archive.org/download/{ia_id}/{ia_id}.epub"

                results.append({
                    "title": title,
                    "author": author,
                    "year": year,
                    "lang": lang_name,
                    "size": "~1 MB",
                    "direct_url": direct_url,
                    "source": "openlibrary"
                })
    except Exception:
        pass
    return results

def search_gutenberg(query: str, max_results: int = 5) -> List[Dict]:
    """Searches Project Gutenberg (Gutendex) for classic literature EPUBs."""
    url = f"https://gutendex.com/books/?search={requests.utils.quote(query)}"
    results = []
    try:
        r = requests.get(url, headers=HEADERS, timeout=2.5)
        if r.status_code == 200:
            books = r.json().get("results", [])
            for b in books[:max_results]:
                formats = b.get("formats", {})
                epub_url = formats.get("application/epub+zip")
                if not epub_url:
                    continue
                authors = [a.get("name", "") for a in b.get("authors", [])]
                author_str = ", ".join(authors) if authors else "Clásico"
                langs = b.get("languages", [])
                lang_name = "Spanish" if "es" in langs else ("English" if "en" in langs else "Other")

                results.append({
                    "title": b.get("title", ""),
                    "author": author_str,
                    "year": "Clásico",
                    "lang": lang_name,
                    "size": "~600 kB",
                    "direct_url": epub_url,
                    "source": "gutenberg"
                })
    except Exception:
        pass

    return results

def search_standard_ebooks(query: str, max_results: int = 5) -> List[Dict]:
    """Searches Standard Ebooks via web search for high-quality public domain EPUBs."""
    url = f"https://standardebooks.org/ebooks?q={requests.utils.quote(query)}"
    browser_headers = {**HEADERS, "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
    results = []
    try:
        r = requests.get(url, headers=browser_headers, timeout=5)
        if r.status_code != 200:
            return []
        soup = BeautifulSoup(r.text, "html.parser")
        for item in soup.select('li[typeof="schema:Book"]')[:max_results]:
            about = item.get("about", "")
            if not about:
                continue
            title_tag = item.select_one('span[property="schema:name"]')
            title = title_tag.get_text(strip=True) if title_tag else about.split("/")[-1].replace("-", " ").title()
            author_tag = item.select_one('p.author a')
            author = author_tag.get_text(strip=True) if author_tag else "Clásico"
            # Epub URL follows predictable pattern: /ebooks/{author}/{title}/downloads/{author}_{title}.epub
            slug = about.strip("/").replace("ebooks/", "")  # e.g. "bram-stoker/dracula"
            parts = slug.split("/")
            epub_filename = "_".join(parts) + ".epub"
            epub_url = f"https://standardebooks.org{about}/downloads/{epub_filename}"
            results.append({
                "title": title,
                "author": author,
                "year": "Clásico",
                "lang": "English",
                "size": "~500 kB",
                "direct_url": epub_url,
                "source": "standard_ebooks"
            })
    except Exception as e:
        logger.warning(f"Standard Ebooks search error: {e}")
    return results

def search_manybooks(query: str, max_results: int = 8) -> List[Dict]:
    """Searches ManyBooks via OPDS for free EPUB books."""
    url = f"https://manybooks.net/opds/search/?q={requests.utils.quote(query)}"
    results = []
    try:
        r = requests.get(url, headers=HEADERS, timeout=6)
        if r.status_code != 200:
            return []
        soup = BeautifulSoup(r.content, "xml")
        for entry in soup.find_all("entry")[:max_results]:
            title_tag = entry.find("title")
            title = title_tag.get_text(strip=True) if title_tag else "Sin título"
            author_tag = entry.find("author")
            name_tag = author_tag.find("name") if author_tag else None
            author = name_tag.get_text(strip=True) if name_tag else "Autor desconocido"
            epub_link = entry.find("link", {"type": "application/epub+zip"})
            if not epub_link:
                continue
            href = epub_link.get("href", "")
            if not href:
                continue
            results.append({
                "title": title,
                "author": author,
                "year": "",
                "lang": "English",
                "size": "~500 kB",
                "direct_url": href,
                "source": "manybooks"
            })
    except Exception as e:
        logger.warning(f"ManyBooks search error: {e}")
    return results

def search_annas_archive(query: str, max_results: int = 10) -> List[Dict]:
    """Searches Anna's Archive for EPUB books (best effort, may be throttled by Cloudflare)."""
    url = f"https://annas-archive.org/search?q={requests.utils.quote(query)}&ext=epub"
    results = []
    try:
        r = requests.get(url, headers={**HEADERS, "Accept-Language": "es-ES,es;q=0.9"}, timeout=8)
        if r.status_code != 200:
            return []
        soup = BeautifulSoup(r.text, "html.parser")
        cards = soup.select("a[href*='/md5/']")[:max_results]
        for card in cards:
            texts = [t.strip() for t in card.stripped_strings if t.strip()]
            if not texts:
                continue
            title = texts[0][:80]
            author = texts[1][:50] if len(texts) > 1 else "Autor desconocido"
            md5_match = re.search(r"/md5/([a-f0-9]+)", card.get("href", ""))
            if not md5_match:
                continue
            md5 = md5_match.group(1)
            results.append({
                "title": title,
                "author": author,
                "year": "",
                "lang": "Unknown",
                "size": "~1 MB",
                "direct_url": f"https://annas-archive.org/fast_download/{md5}/0/0",
                "source": "annas_archive"
            })
    except Exception as e:
        logger.warning(f"Anna's Archive search error: {e}")
    return results

def search_zlib(query: str, max_results: int = 10) -> List[Dict]:
    """Searches Z-Library via z-lib.fm for EPUB books (best effort, may be throttled)."""
    base = "https://z-lib.fm"
    results = []
    try:
        r = requests.get(f"{base}/s/{requests.utils.quote(query)}?e=1", headers=HEADERS, timeout=8)
        if r.status_code != 200:
            return []
        soup = BeautifulSoup(r.text, "html.parser")
        cards = soup.select(".book-item, .bookRow, .resItemBox")[:max_results]
        for card in cards:
            title_tag = card.select_one("h3, .book__title, .itemCover")
            if not title_tag:
                continue
            title = title_tag.get_text(strip=True)[:80]
            author_tag = card.select_one(".book__author, .authors")
            author = author_tag.get_text(strip=True)[:50] if author_tag else "Autor desconocido"
            link_tag = card.select_one("a[href]")
            if not link_tag:
                continue
            book_href = link_tag.get("href", "")
            if not book_href.startswith("http"):
                book_href = base + book_href
            detail_r = requests.get(book_href, headers=HEADERS, timeout=6)
            if detail_r.status_code == 200:
                detail_soup = BeautifulSoup(detail_r.text, "html.parser")
                dl_btn = detail_soup.find("a", href=lambda h: h and ("/dl/" in h or "/downloads/" in h))
                if dl_btn:
                    dl_href = dl_btn.get("href", "")
                    if not dl_href.startswith("http"):
                        dl_href = base + dl_href
                    results.append({
                        "title": title,
                        "author": author,
                        "year": "",
                        "lang": "Unknown",
                        "size": "~1 MB",
                        "direct_url": dl_href,
                        "source": "zlibrary"
                    })
    except Exception as e:
        logger.warning(f"Z-Library search error: {e}")
    return results

def search_epubs(query: str, max_results: int = 40, target_lang: Optional[str] = "Spanish") -> Tuple[List[Dict], List[Dict]]:
    """
    Multi-source engine: Libgen, Archive.org, OpenLibrary, Gutenberg,
    Standard Ebooks, ManyBooks, Anna's Archive, Z-Library.
    """
    all_books = []
    seen_titles = set()

    with ThreadPoolExecutor(max_workers=8) as executor:
        f_libgen = executor.submit(search_libgen, query, 35)
        f_archive = executor.submit(search_archive_org, query, 25)
        f_openlibrary = executor.submit(search_openlibrary, query, 15)
        f_gutenberg = executor.submit(search_gutenberg, query, 5)
        f_standard = executor.submit(search_standard_ebooks, query, 5)
        f_manybooks = executor.submit(search_manybooks, query, 8)
        f_annas = executor.submit(search_annas_archive, query, 10)
        f_zlib = executor.submit(search_zlib, query, 10)

        for future in [f_libgen, f_archive, f_openlibrary, f_gutenberg,
                       f_standard, f_manybooks, f_annas, f_zlib]:
            try:
                res = future.result()
                for b in res:
                    clean_t = re.sub(r'[^a-zA-Z0-9]', '', b.get('title', '').lower()[:45])
                    clean_a = re.sub(r'[^a-zA-Z0-9]', '', b.get('author', '').lower()[:20])
                    norm = f"{clean_t}_{clean_a}" if clean_a else clean_t
                    if norm and norm not in seen_titles:
                        seen_titles.add(norm)
                        all_books.append(b)
            except Exception:
                pass

    matching_books = []
    other_books = []

    for book in all_books:
        lang = book.get("lang", "Unknown")
        if target_lang is None or target_lang.lower() in lang.lower():
            matching_books.append(book)
        else:
            other_books.append(book)

    return matching_books[:max_results], other_books[:max_results]

EPUB_MAGIC = b"PK\x03\x04"  # EPUB files are ZIP containers

def _safe_remove(path: str) -> None:
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass

_DOWNLOAD_HEADERS = {
    **HEADERS,
    "Accept": "application/epub+zip, application/zip, application/octet-stream, */*",
    "Accept-Language": "en-US,en;q=0.9,es;q=0.8",
}

def _stream_to_file(url: str, filepath: str, timeout: int = 30, progress_cb=None) -> bool:
    """
    Streams `url` to `filepath` with a hard size cap and validates that the payload is really
    an EPUB (ZIP) and not an HTML error page. Returns True on success; cleans up on failure.
    """
    try:
        with requests.get(url, headers=_DOWNLOAD_HEADERS, timeout=timeout, stream=True) as resp:
            resp.raise_for_status()
            declared = resp.headers.get("Content-Length", "")
            total_bytes = int(declared) if declared.isdigit() else None
            if total_bytes and total_bytes > MAX_DOWNLOAD_BYTES:
                logger.warning(f"Download refused (declared {total_bytes} bytes > cap): {url}")
                return False
            written = 0
            with open(filepath, "wb") as f:
                for chunk in resp.iter_content(chunk_size=65536):
                    if not chunk:
                        continue
                    written += len(chunk)
                    if written > MAX_DOWNLOAD_BYTES:
                        raise ValueError("download exceeded size cap")
                    f.write(chunk)
                    if progress_cb:
                        progress_cb(written, total_bytes)
        with open(filepath, "rb") as f:
            head = f.read(4)
        if written < 1024 or head != EPUB_MAGIC:
            logger.warning(f"Downloaded payload is not a valid EPUB ({written} bytes) from {url}")
            _safe_remove(filepath)
            return False
        return True
    except Exception as e:
        logger.warning(f"Download from {url} failed: {e}")
        _safe_remove(filepath)
        return False

def _resolve_archive_epub_url(ident: str) -> Optional[str]:
    """Looks up the real EPUB file name of an Internet Archive item (it is often not <id>.epub)."""
    try:
        r = requests.get(f"https://archive.org/metadata/{quote(ident)}", headers=HEADERS, timeout=10)
        if r.status_code != 200:
            return None
        files = r.json().get("files", [])
        epubs = [f for f in files if str(f.get("name", "")).lower().endswith(".epub")]
        if not epubs:
            return None
        epubs.sort(key=lambda f: (f.get("format") != "EPUB", f.get("source") != "original"))
        return f"https://archive.org/download/{quote(ident)}/{quote(epubs[0]['name'])}"
    except Exception as e:
        logger.warning(f"Archive.org metadata lookup failed for {ident}: {e}")
        return None

def _libgen_download_candidates(book: Dict) -> List[str]:
    """Collects candidate direct-download URLs from every Libgen mirror page of a book."""
    base = book.get("base") or "https://libgen.li"
    candidates: List[str] = []

    # Extract md5 from any mirror link to try library.lol (more reliable mirror)
    md5 = None
    for mirror in book.get("mirrors", []):
        m = re.search(r'md5=([a-fA-F0-9]{32})', mirror, re.IGNORECASE)
        if m:
            md5 = m.group(1).lower()
            break

    if md5:
        try:
            lol_resp = requests.get(f"https://library.lol/main/{md5}", headers=HEADERS, timeout=10)
            if lol_resp.status_code == 200:
                lol_soup = BeautifulSoup(lol_resp.text, "html.parser")
                dl_link = lol_soup.select_one("#download a") or lol_soup.find("a", href=lambda h: h and "get.php" in str(h))
                if dl_link and dl_link.get("href"):
                    lol_url = urljoin("https://library.lol/", dl_link["href"])
                    if lol_url not in candidates:
                        candidates.append(lol_url)
        except Exception as e:
            logger.warning(f"library.lol fallback failed for md5={md5}: {e}")

    for mirror in book.get("mirrors", []):
        mirror_url = urljoin(base + "/", mirror)
        try:
            m_resp = requests.get(mirror_url, headers=HEADERS, timeout=10)
            if m_resp.status_code != 200:
                continue
            m_soup = BeautifulSoup(m_resp.text, "html.parser")
            get_btn = m_soup.find("a", string=lambda t: t and "get" in t.lower())
            if not get_btn:
                get_btn = m_soup.find("a", href=lambda h: h and "get.php" in h)
            if get_btn and get_btn.get("href"):
                url = urljoin(mirror_url, get_btn["href"])
                if url not in candidates:
                    candidates.append(url)
        except Exception as e:
            logger.warning(f"Libgen mirror {mirror_url} failed: {e}")
    return candidates

def download_epub(book: Dict, output_dir: Optional[str] = None, progress_cb=None) -> Optional[str]:
    """
    Downloads an EPUB from a direct URL or Libgen mirrors and saves it locally with a
    collision-resistant temporary filename. Returns the file path, or None on failure.
    """
    target_dir = output_dir or DOWNLOADS_DIR
    os.makedirs(target_dir, exist_ok=True)
    safe_title = clean_filename(book.get('title', 'libro')[:45]) or "libro"
    filepath = os.path.join(target_dir, f"{safe_title}_{uuid.uuid4().hex[:6]}.epub")

    # 1. Direct download (Archive.org / OpenLibrary / Gutenberg)
    direct = book.get("direct_url")
    if direct:
        logger.info(f"Downloading from direct source: {direct}")
        if _stream_to_file(direct, filepath, timeout=25, progress_cb=progress_cb):
            return filepath
        m = re.search(r"archive\.org/download/([^/]+)/", direct)
        if m:
            real_url = _resolve_archive_epub_url(m.group(1))
            if real_url and real_url != direct:
                logger.info(f"Retrying with resolved Archive.org file: {real_url}")
                if _stream_to_file(real_url, filepath, timeout=25, progress_cb=progress_cb):
                    return filepath
            else:
                logger.warning(f"Archive.org item {m.group(1)} has no downloadable EPUB (may be lending-only).")

    # 2. Libgen mirrors: try every candidate link until one yields a valid EPUB
    for url in _libgen_download_candidates(book):
        logger.info(f"Downloading from Libgen: {url}")
        if _stream_to_file(url, filepath, timeout=30, progress_cb=progress_cb):
            return filepath

    logger.error(f"All download sources failed for '{book.get('title', '?')}' ({book.get('source', '?')})")
    return None
