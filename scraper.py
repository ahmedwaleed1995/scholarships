#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scraper.py — يجمع منح دراسية من عدة مواقع، يستخرج بياناتها الأساسية،
يضيف الجديد ويحذف المنح المغلقة/المنتهية من scholarships.json

طريقة الاستخدام:
    python3 scraper.py

يعمل بشكل مستقل تمامًا، وتقدر تجدوله ليعمل تلقائيًا (راجع README.md).

مهم جدًا:
- بنية HTML لهذه المواقع تتغير مع الوقت. القيم داخل SOURCES (خصوصًا
  item_selector) هي نقطة بداية معقولة وليست مضمونة 100%. إذا توقف
  مصدر عن إرجاع نتائج، افتح الموقع بالمتصفح، اضغط F12 (أدوات المطور)،
  وحدد الـ CSS selector الصحيح لعنصر "بطاقة المنحة" في صفحة الأرشيف/القائمة.
- استخراج (الدولة، الجامعة، المتطلبات، آخر موعد...) يعتمد على البحث عن
  كلمات مفتاحية شائعة داخل نص المقال. هذا "أفضل تخمين" وليس دقيقًا 100%،
  خصوصًا للمواقع التي لا تستخدم تنسيق "التسمية: القيمة" (label: value).
  راجع الحقول اللي تظهر "غير محدد" يدويًا عند الحاجة.
"""

import json
import re
import time
import sys
from datetime import datetime, timezone
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

DB_PATH = "scholarships.json"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ScholarshipTracker/1.0; personal use)"
}
TIMEOUT = 15
REQUEST_DELAY_SECONDS = 2  # تأخير مؤدب بين الطلبات حتى لا نُثقل على المواقع

# ---------------------------------------------------------------------------
# 1) قائمة المصادر — عدّل / أضف عليها حسب الحاجة
# كل مصدر: اسم، رابط صفحة القائمة/الأرشيف، والـ CSS selector لبطاقة المنحة
# item_selector لازم يشير لعنصر <a> (أو عنصر يحتوي <a>) فيه رابط وعنوان المنحة
# ---------------------------------------------------------------------------
SOURCES = [
    {
        "name": "for9a.com",
        "list_url": "https://www.for9a.com/opportunity/category/%D9%85%D9%86%D8%AD-%D8%AF%D8%B1%D8%A7%D8%B3%D9%8A%D8%A9/all/%D9%85%D9%85%D9%88%D9%84%D8%A9-%D8%A8%D8%A7%D9%84%D9%83%D8%A7%D9%85%D9%84",
        "item_selector": "article a.opportunity-card, article h2 a, .card a",
    },
    {
        "name": "studyshoot.com",
        "list_url": "https://studyshoot.com/%D8%A7%D9%84%D9%85%D9%86%D8%AD-%D8%A7%D9%84%D8%AF%D8%B1%D8%A7%D8%B3%D9%8A%D9%87-%D8%AD%D9%88%D9%84-%D8%A7%D9%84%D8%B9%D8%A7%D9%84%D9%85/",
        "item_selector": "article h2 a, .post-title a",
    },
    {
        "name": "grabscholarship.com",
        "list_url": "https://grabscholarship.com/scholarships/",
        "item_selector": "article h2 a, .entry-title a",
    },
    {
        "name": "evascholarships.com",
        "list_url": "https://www.evascholarships.com/",
        "item_selector": "article h2 a, .post-title a",
    },
    {
        "name": "scholars4dev.com",
        "list_url": "https://www.scholars4dev.com/category/scholarships-list/",
        "item_selector": "article h2 a, .post-title a, h2.entry-title a",
    },
    {
        "name": "findaphd.com",
        "list_url": "https://www.findaphd.com/phds/funded-studentships/",
        "item_selector": "a.h4Fade, .studentshipTitleLink, h4 a",
    },
    {
        "name": "fastweb.com",
        "list_url": "https://www.fastweb.com/college-scholarships",
        "item_selector": "a.scholarship-title, .scholarship-name a, article h3 a",
    },
    {
        "name": "internationalscholarships.com",
        "list_url": "https://www.internationalscholarships.com/scholarships",
        "item_selector": "article h2 a, .views-field-title a, .scholarship-title a",
    },
    {
        "name": "scholarships.com",
        "list_url": "https://www.scholarships.com/financial-aid/college-scholarships/scholarship-directory",
        "item_selector": "a.scholarship-name, .scholarship-title a, article h3 a",
    },
    {
        "name": "scholarshipscorner.website",
        "list_url": "https://scholarshipscorner.website/",
        "item_selector": "article h2 a, .post-title a, h2.entry-title a",
    },
    # --- مصادر إضافية عالمية (أمريكا/أوروبا/آسيا - مجمّعة) ---
    {
        "name": "iefa.org",
        "list_url": "https://www.iefa.org/scholarships",
        "item_selector": "article h2 a, .scholarship-title a, td a",
    },
    {
        "name": "opportunitydesk.org",
        "list_url": "https://opportunitydesk.org/category/scholarships/",
        "item_selector": "article h2 a, .entry-title a",
    },
    {
        "name": "scholarshipsads.com",
        "list_url": "https://scholarshipsads.com/",
        "item_selector": "article h2 a, .post-title a",
    },
    {
        "name": "scholarshipportal.com (أوروبا)",
        "list_url": "https://www.scholarshipportal.com/scholarships",
        "item_selector": "a.scholarship-name, article h3 a, .card a",
    },
    {
        "name": "internationalstudent.com",
        "list_url": "https://www.internationalstudent.com/scholarships/",
        "item_selector": "article h2 a, .scholarship-title a, td a",
    },
    # أضف مصادر إضافية بنفس الشكل هنا (مواقع جامعات/سفارات عادة تحتاج
    # selector مختلف لكل موقع، جرّب أولاً وشوف شو بيرجع). مواقع جامعات
    # وسفارات محددة (مثل صفحة منحة واحدة بعينها) لا تصلح كمصدر هنا لأنها
    # ليست صفحة قائمة فيها عدة منح — أضفها يدويًا في scholarships.json بدلاً من ذلك.
]

# كلمات مفتاحية لتصنيف المستوى الأكاديمي — الترتيب مهم (تحقق من "ما بعد دكتوراه" أولاً)
LEVEL_KEYWORDS = [
    ("ما بعد دكتوراه", "ما بعد دكتوراه"),
    ("بوستدوك", "ما بعد دكتوراه"),
    ("دكتوراه", "دكتوراه"),
    ("PhD", "دكتوراه"),
    ("ماجستير", "ماجستير"),
    ("Master", "ماجستير"),
    ("بكالوريوس", "بكالوريوس"),
    ("البكالوريوس", "بكالوريوس"),
    ("Bachelor", "بكالوريوس"),
]

FUNDING_KEYWORDS = [
    ("ممولة بالكامل", "ممولة بالكامل"),
    ("ممول بالكامل", "ممولة بالكامل"),
    ("تمويل كامل", "ممولة بالكامل"),
    ("تمويل جزئي", "تمويل جزئي"),
    ("ممولة جزئياً", "تمويل جزئي"),
    ("ممولة جزئيا", "تمويل جزئي"),
    ("بدون تمويل", "دراسة فقط (بدون تمويل)"),
    ("دراسة فقط", "دراسة فقط (بدون تمويل)"),
    ("إعفاء من الرسوم", "تمويل جزئي (إعفاء رسوم)"),
]

CLOSED_KEYWORDS = [
    "تم إغلاق التقديم", "انتهى التقديم", "انتهت المنحة", "الموعد النهائي مر",
    "التقديم مغلق حاليًا", "no longer accepting applications",
    "applications are now closed", "this scholarship has closed",
    "the scholarship is now closed", "applications closed for this cycle",
]
# كلمات لأسماء عناصر مش منح فعلية (شارات/إعلانات/عناصر واجهة التقطها الـ selector
# بالغلط) — أي عنوان يطابق أحدها بالكامل يُتجاهل
TITLE_BLOCKLIST = {
    "featured", "sponsored", "advertisement", "ad", "related scholarships",
    "view all", "see more", "load more", "read more", "learn more",
    "مميز", "إعلان", "المزيد", "شاهد المزيد",
}
MIN_TITLE_LENGTH = 12

COUNTRY_LIST = [
    "ألمانيا", "السعودية", "الإمارات", "قطر", "تركيا", "ماليزيا", "إندونيسيا",
    "الولايات المتحدة", "أمريكا", "بريطانيا", "المملكة المتحدة", "كندا",
    "أستراليا", "اليابان", "الصين", "الهند", "إيطاليا", "فرنسا", "هولندا",
    "السويد", "النرويج", "سويسرا", "النمسا", "بلجيكا", "إسبانيا", "كوريا الجنوبية",
    "روسيا", "مصر", "الأردن", "العراق", "المغرب", "تونس",
]


def log(msg):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}")


def load_db():
    try:
        with open(DB_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"last_updated": None, "added_since_last_run": [],
                "removed_since_last_run": [], "scholarships": []}


def save_db(db):
    with open(DB_PATH, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)


def classify(text, keyword_list, default="غير محدد"):
    for kw, label in keyword_list:
        if kw.lower() in text.lower():
            return label
    return default


def extract_country(text):
    for c in COUNTRY_LIST:
        if c in text:
            return c
    return "غير محدد"


def extract_labelled_field(text, labels):
    """يبحث عن نمط 'التسمية: القيمة' الشائع في مقالات المنح العربية."""
    for label in labels:
        m = re.search(rf"{label}\s*[:：]\s*(.+)", text)
        if m:
            value = m.group(1).strip()
            # اقطع عند أول سطر جديد أو طول زائد
            value = value.split("\n")[0].strip()
            return value[:200]
    return "غير محدد"


def fetch(url):
    resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp


def discover_items(source):
    """يرجع لائحة (title, url) من صفحة القائمة لمصدر واحد."""
    items = []
    try:
        resp = fetch(source["list_url"])
    except Exception as e:
        log(f"⚠️  تعذر الوصول لمصدر {source['name']}: {e}")
        return items

    soup = BeautifulSoup(resp.text, "html.parser")
    links = soup.select(source["item_selector"])
    seen = set()
    for a in links:
        href = a.get("href")
        title = a.get_text(strip=True)
        if not href or not title or len(title) < MIN_TITLE_LENGTH:
            continue
        if title.strip().lower() in TITLE_BLOCKLIST:
            continue
        full_url = urljoin(source["list_url"], href)
        if full_url in seen:
            continue
        seen.add(full_url)
        items.append((title, full_url))
    log(f"  {source['name']}: وجدت {len(items)} عنصر في صفحة القائمة")
    return items


def extract_details(url):
    """يفتح صفحة المنحة ويحاول استخراج الحقول التفصيلية بأفضل تخمين ممكن."""
    try:
        resp = fetch(url)
    except Exception as e:
        log(f"  ⚠️  تعذر فتح {url}: {e}")
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    # نص الصفحة الكامل (لتصنيف/استخراج الكلمات المفتاحية)
    full_text = soup.get_text(separator="\n", strip=True)

    is_closed = any(kw.lower() in full_text.lower() for kw in CLOSED_KEYWORDS)

    level = classify(full_text, LEVEL_KEYWORDS)
    funding = classify(full_text, FUNDING_KEYWORDS)
    country = extract_country(full_text)
    university = extract_labelled_field(
        full_text, ["الجامعة المانحة", "الجامعة", "المؤسسة المانحة", "University"])
    requirements = extract_labelled_field(
        full_text, ["الشروط", "متطلبات التقديم", "شروط التقديم", "Requirements"])
    benefits = extract_labelled_field(
        full_text, ["مميزات المنحة", "توفر المنحة", "تشمل المنحة", "Benefits"])
    open_date = extract_labelled_field(
        full_text, ["تاريخ فتح باب التقديم", "موعد فتح التقديم", "بداية التقديم"])
    deadline = extract_labelled_field(
        full_text, ["آخر موعد للتقديم", "الموعد النهائي", "آخر موعد", "Deadline"])

    return {
        "is_closed": is_closed,
        "level": level,
        "funding_type": funding,
        "country": country,
        "university": university,
        "requirements": requirements,
        "benefits": benefits,
        "open_date": open_date,
        "deadline": deadline,
    }


def check_still_open(url):
    """يتحقق هل رابط منحة موجودة سابقًا ما زال شغّال وغير مغلق."""
    try:
        resp = fetch(url)
    except requests.exceptions.HTTPError as e:
        code = e.response.status_code if e.response is not None else None
        if code in (404, 410):
            return False
        return True  # خطأ مؤقت غير موثوق - لا تحذف بسببه
    except Exception:
        return True  # لا تحذف بسبب خطأ شبكة مؤقت

    text = resp.text.lower()
    if any(kw.lower() in text for kw in CLOSED_KEYWORDS):
        return False
    return True


def normalize_title(title):
    """يبسّط العنوان للمقارنة (يتجاهل حالة الأحرف والمسافات الزائدة) حتى نكتشف
    نفس المنحة لو تكررت برابطين مختلفين (مثلاً بارامترات تتبّع مختلفة)."""
    return re.sub(r"\s+", " ", title).strip().lower()


def main():
    db = load_db()
    existing_urls = {s["url"] for s in db["scholarships"]}
    existing_titles = {normalize_title(s["title"]) for s in db["scholarships"]}
    added = []
    removed = []

    # 1) تحقق من المنح الموجودة سابقًا - احذف المغلق/المحذوف
    log("🔎 فحص المنح الموجودة (هل ما زالت مفتوحة)...")
    still_open_list = []
    for s in db["scholarships"]:
        time.sleep(REQUEST_DELAY_SECONDS)
        if check_still_open(s["url"]):
            still_open_list.append(s)
        else:
            removed.append(s["title"])
            log(f"  ❌ أُزيلت (مغلقة/غير موجودة): {s['title']}")
    db["scholarships"] = still_open_list

    # 2) اكتشف عناصر جديدة من كل مصدر
    log("🔎 البحث عن منح جديدة في المصادر...")
    for source in SOURCES:
        items = discover_items(source)
        for title, url in items:
            norm = normalize_title(title)
            if url in existing_urls or norm in existing_titles:
                continue
            time.sleep(REQUEST_DELAY_SECONDS)
            details = extract_details(url)
            if details is None:
                continue
            if details["is_closed"]:
                log(f"  ⏭️  تجاهل (مغلقة أصلاً): {title}")
                continue

            entry = {
                "id": re.sub(r"[^a-zA-Z0-9]+", "-", url)[-60:],
                "title": title,
                "url": url,
                "source": source["name"],
                "level": details["level"],
                "funding_type": details["funding_type"],
                "country": details["country"],
                "university": details["university"],
                "requirements": details["requirements"],
                "benefits": details["benefits"],
                "open_date": details["open_date"],
                "deadline": details["deadline"],
                "scraped_at": datetime.now(timezone.utc).isoformat(),
            }
            db["scholarships"].append(entry)
            existing_urls.add(url)
            existing_titles.add(norm)
            added.append(title)
            log(f"  ✅ أُضيفت: {title} [{details['level']} | {details['funding_type']}]")

    db["last_updated"] = datetime.now(timezone.utc).isoformat()
    db["added_since_last_run"] = added
    db["removed_since_last_run"] = removed
    save_db(db)

    log(f"✔️  انتهى التحديث. أُضيف: {len(added)} | أُزيل: {len(removed)} | الإجمالي الآن: {len(db['scholarships'])}")


if __name__ == "__main__":
    main()
