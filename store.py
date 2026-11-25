"""Svežinka: sezonske košarice, naročnine in JSON baza."""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
import os
import re
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "data" / "db.json"
_MEMORY = {"db": None}


class _Guard:
    """Workers can import threading, but locks there are not usable."""

    def __enter__(self):
        return None

    def __exit__(self, *exc):
        return False


_lock = _Guard()
PBKDF_ROUNDS = 60_000
DEMO_PASSWORD = "kosarica"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

META = {
    "brand": "Svežinka",
    "tagline": "Od kmeta do vrat",
    "season": "Pozna jesen",
    "season_note": "Zemlja se ohlaja. V zaboj gredo korenovke, ohrovti in buče, ki so ta teden dozorele na treh kmetijah.",
    "field_note": "Krompir je izkopan in počiva v kleti. Motovilec je šele zdaj dovolj gost za solato.",
    "window": "14:00–19:00",
}

GROUP_ICON = {
    "Korenovke": "root",
    "Kapusnice": "cabbage",
    "Listnata": "leaf",
    "Čebulnice": "bulb",
    "Zelišča": "herb",
    "Stebla in buče": "squash",
}

DAY_OFFSET = {"torek": 1, "sreda": 2, "cetrtek": 3}
DAY_LABEL = {"torek": "torek", "sreda": "sreda", "cetrtek": "četrtek"}
STATUS_LABEL = {
    "nacrtovano": "Načrtovano",
    "pakiranje": "Pakiranje",
    "na_poti": "Na poti",
    "dostavljeno": "Dostavljeno",
    "pavzirano": "Pavzirano",
}
OPEN_STATUSES = {"nacrtovano", "pakiranje", "pavzirano"}
ACTIVE_ROUTE = {"nacrtovano", "pakiranje", "na_poti"}

MONTHS = [
    "januarja",
    "februarja",
    "marca",
    "aprila",
    "maja",
    "junija",
    "julija",
    "avgusta",
    "septembra",
    "oktobra",
    "novembra",
    "decembra",
]

PRODUCE = [
    {"id": "krompir", "name": "Krompir", "group": "Korenovke", "hint": "Mivka, dobra za pečenje in pire.", "qty": {"mala": "800 g", "srednja": "1,2 kg", "velika": "1,8 kg"}},
    {"id": "korenje", "name": "Korenje", "group": "Korenovke", "hint": "Sladko, poznojesensko.", "qty": {"mala": "400 g", "srednja": "700 g", "velika": "1 kg"}},
    {"id": "pastinak", "name": "Pastinak", "group": "Korenovke", "hint": "Za kremne juhe.", "qty": {"mala": "300 g", "srednja": "400 g", "velika": "600 g"}},
    {"id": "rdeca-pesa", "name": "Rdeča pesa", "group": "Korenovke", "hint": "Peči cele, z orehi.", "qty": {"mala": "400 g", "srednja": "500 g", "velika": "700 g"}},
    {"id": "koleraba", "name": "Koleraba", "group": "Korenovke", "hint": "Surova na rezine ali v juho.", "qty": {"mala": "1 kos", "srednja": "1 kos", "velika": "2 kosa"}},
    {"id": "repa", "name": "Repa", "group": "Korenovke", "hint": "Blaga, za juho.", "qty": {"mala": "1 kos", "srednja": "1 kos", "velika": "2 kosa"}},
    {"id": "ohrovt", "name": "Ohrovt", "group": "Kapusnice", "hint": "Za enolončnice in ocvrtke.", "qty": {"mala": "1 glava", "srednja": "1 glava", "velika": "1 večja glava"}},
    {"id": "brokoli", "name": "Brokoli", "group": "Kapusnice", "hint": "Kratek čas na pari.", "qty": {"mala": "1 kos", "srednja": "1 kos", "velika": "2 kosa"}},
    {"id": "cvetaca", "name": "Cvetača", "group": "Kapusnice", "hint": "Cela glava iz tunela.", "qty": {"mala": "1 kos", "srednja": "1 kos", "velika": "1 kos"}},
    {"id": "zelje", "name": "Zelje", "group": "Kapusnice", "hint": "Belo, čvrsto.", "qty": {"mala": "1 glava", "srednja": "1 glava", "velika": "1 velika glava"}},
    {"id": "rdece-zelje", "name": "Rdeče zelje", "group": "Kapusnice", "hint": "Za hitro solato.", "qty": {"mala": "1 glava", "srednja": "1 glava", "velika": "1 glava"}},
    {"id": "brsticni", "name": "Brstični ohrovt", "group": "Kapusnice", "hint": "Najboljši na hitro popečen.", "qty": {"mala": "250 g", "srednja": "350 g", "velika": "500 g"}},
    {"id": "radic", "name": "Radič", "group": "Listnata", "hint": "Grenak, uravnoteži sladke korenovke.", "qty": {"mala": "1 glava", "srednja": "1 glava", "velika": "2 glavi"}},
    {"id": "motovilec", "name": "Motovilec", "group": "Listnata", "hint": "Nežna zimska solata.", "qty": {"mala": "100 g", "srednja": "125 g", "velika": "150 g"}},
    {"id": "blitva", "name": "Blitva", "group": "Listnata", "hint": "Stebla in listi.", "qty": {"mala": "1 šop", "srednja": "1 šop", "velika": "2 šopa"}},
    {"id": "endivija", "name": "Endivija", "group": "Listnata", "hint": "Hrustljava, za toplo solato.", "qty": {"mala": "1 glava", "srednja": "1 glava", "velika": "1 glava"}},
    {"id": "rukola", "name": "Rukola", "group": "Listnata", "hint": "Zimska, iz tunela.", "qty": {"mala": "80 g", "srednja": "100 g", "velika": "125 g"}},
    {"id": "cebula", "name": "Čebula", "group": "Čebulnice", "hint": "Rumena, dobro posušena.", "qty": {"mala": "400 g", "srednja": "600 g", "velika": "800 g"}},
    {"id": "por", "name": "Por", "group": "Čebulnice", "hint": "Za juho in rižoto.", "qty": {"mala": "2 kosa", "srednja": "3 kosi", "velika": "4 kosi"}},
    {"id": "cesen", "name": "Česen", "group": "Čebulnice", "hint": "Domač, oster.", "qty": {"mala": "1 glava", "srednja": "1 glava", "velika": "2 glavi"}},
    {"id": "drobnjak", "name": "Drobnjak", "group": "Zelišča", "hint": "Svež šop z grede.", "qty": {"mala": "1 šop", "srednja": "1 šop", "velika": "1 šop"}},
    {"id": "petersilj", "name": "Peteršilj", "group": "Zelišča", "hint": "Ravnolistni.", "qty": {"mala": "1 šop", "srednja": "1 šop", "velika": "2 šopa"}},
    {"id": "bucke-hokaido", "name": "Buča hokaido", "group": "Stebla in buče", "hint": "Lupine ni treba lupiti.", "qty": {"mala": "1 mala", "srednja": "1 srednja", "velika": "1 velika"}},
    {"id": "koromac", "name": "Koromač", "group": "Stebla in buče", "hint": "Sladki komarček.", "qty": {"mala": "1 kos", "srednja": "1 kos", "velika": "2 kosa"}},
]

BASKETS = {
    "mala": {
        "id": "mala",
        "name": "Mala",
        "people": "Za 1–2 osebi",
        "price": 68,
        "weight": "3–4 kg",
        "swaps": 2,
        "text": "Za enega ali dva, ki kuhata čez teden in nočeta, da zelenjava ostane v predalu.",
        "produce": ["krompir", "korenje", "cebula", "bucke-hokaido", "ohrovt", "por", "petersilj"],
    },
    "srednja": {
        "id": "srednja",
        "name": "Srednja",
        "people": "Za 3–4 osebe",
        "price": 96,
        "weight": "5–7 kg",
        "swaps": 3,
        "text": "Za gospodinjstvo, kjer sta juha in solata del navadnega tedna.",
        "produce": ["krompir", "korenje", "cebula", "bucke-hokaido", "ohrovt", "por", "petersilj", "rdeca-pesa", "radic", "brokoli"],
    },
    "velika": {
        "id": "velika",
        "name": "Velika",
        "people": "Za 5 ali več",
        "price": 128,
        "weight": "8–10 kg",
        "swaps": 4,
        "text": "Za veliko mizo, deljenje s sosedo ali kuho, ki napolni hladilnik za konec tedna.",
        "produce": ["krompir", "korenje", "cebula", "bucke-hokaido", "ohrovt", "por", "petersilj", "rdeca-pesa", "radic", "brokoli", "zelje", "cvetaca", "motovilec", "cesen"],
    },
}

FARMS = [
    {
        "name": "Kmetija Zajc",
        "place": "Grosuplje",
        "soil": "Ilovica ob potoku",
        "grows": "Krompir, korenje, pesa, pastinak",
        "text": "Družina Zajc koplje korenovke v istem tednu, ko gredo v zaboj. Krompir teden dni počiva v kleti, da se skorja umiri.",
    },
    {
        "name": "Kmetija Kovač",
        "place": "Vrhnika",
        "soil": "Vlažni travniki",
        "grows": "Ohrovt, zelje, radič, motovilec",
        "text": "Na vlažni zemlji rastejo kapusnice in zimska solata. Radič režemo zjutraj, da ostane čvrst do večera.",
    },
    {
        "name": "Kmetija Mlinar",
        "place": "Kamnik",
        "soil": "Višje lege",
        "grows": "Buče, por, čebula, česen",
        "text": "Višje lege dajejo počasnejšo rast. Hokaido in česen posušijo na kozolcu, por pa režemo sproti.",
    },
]

FAQS = [
    {
        "q": "Kdaj pride košarica?",
        "a": "Torek, sredo ali četrtek, med 14. in 19. uro. Dan izbereš ob naročilu in ga lahko kasneje spremeniš.",
    },
    {
        "q": "Kaj je noter?",
        "a": "Zelenjava, ki je ta teden zrela na treh kmetijah. Seznam vidiš, preden potrdiš naročnino, in v računu, dokler košarice še nismo začeli pakirati.",
    },
    {
        "q": "Lahko kaj zamenjam?",
        "a": "Da. Mala košarica dovoli 2 menjavi, srednja 3, velika 4. Menjava velja za košarice, ki še čakajo na pakiranje.",
    },
    {
        "q": "Kaj če me ni doma?",
        "a": "V opombe napišeš, kje pustimo zaboj: pred vrati, pri sosedu ali pri vratarju. Lesen zaboj naslednji teden vzamemo nazaj.",
    },
    {
        "q": "Kako plačam?",
        "a": "Enkrat mesečno, za štiri košarice. Dostava je vključena. V tej različici strani kartice še ne bremenimo — naročilo se zapiše v pregled kmetije.",
    },
    {
        "q": "Lahko pavziram?",
        "a": "Da, v svojem računu. Pavza ustavi košarice, ki jih še nismo odpeljali na pot.",
    },
    {
        "q": "Kam dostavljate?",
        "a": "Po Sloveniji. Za odmaknjene zaselke se pred prvo dostavo oglasimo in potrdimo uro.",
    },
    {
        "q": "Je zelenjava ekološka?",
        "a": "Pridelek je z majhnih kmetij, brez letalskega prevoza in brez dolgega skladiščenja. Na tej strani ne obljubljamo certifikata — piše, katera kmetija prideluje katero skupino.",
    },
]

TESTIMONIALS = [
    {
        "quote": "Motovilec namesto pese je majhna stvar, zaradi katere košarico res pojemo do konca.",
        "name": "Ana Horvat",
        "place": "Ljubljana",
        "detail": "srednja košarica",
    },
    {
        "quote": "Buče ne jem. Koleraba pa gre v vsako juho. Menjava je zato, da zaboj ni muzej.",
        "name": "Peter Hribar",
        "place": "Koper",
        "detail": "mala košarica",
    },
    {
        "quote": "Za nas štiri je velika košarica ravno prav. V četrtek je že na stopnicah, ko pridemo domov.",
        "name": "Tine Zupan",
        "place": "Domžale",
        "detail": "velika košarica",
    },
]

PEOPLE = [
    {"firstName": "Ana", "lastName": "Horvat", "email": "ana.horvat@example.com", "phone": "041 555 210", "createdAt": "2026-09-04", "startedAt": "2026-09-08", "size": "srednja", "day": "sreda", "swaps": [{"remove": "rdeca-pesa", "add": "motovilec"}], "address": {"street": "Trubarjeva cesta 18", "postal": "1000", "city": "Ljubljana", "notes": "2. nadstropje, zvonec Horvat"}},
    {"firstName": "Marko", "lastName": "Kralj", "email": "marko.kralj@example.com", "phone": "051 300 118", "createdAt": "2026-09-12", "startedAt": "2026-09-15", "size": "mala", "day": "torek", "swaps": [], "address": {"street": "Bleiweisova cesta 5", "postal": "4000", "city": "Kranj", "notes": "Hiša na dvorišču, levi zvonec"}},
    {"firstName": "Maja", "lastName": "Potočnik", "email": "maja.potocnik@example.com", "phone": "031 442 907", "createdAt": "2026-08-20", "startedAt": "2026-08-25", "size": "velika", "day": "cetrtek", "swaps": [{"remove": "ohrovt", "add": "brsticni"}, {"remove": "zelje", "add": "rdece-zelje"}], "address": {"street": "Partizanska cesta 22", "postal": "2000", "city": "Maribor", "notes": "Pustite pri vratarju"}},
    {"firstName": "Luka", "lastName": "Bizjak", "email": "luka.bizjak@example.com", "phone": "040 218 664", "createdAt": "2026-09-01", "startedAt": "2026-09-08", "size": "srednja", "day": "sreda", "swaps": [], "pausedAt": "2026-11-20", "address": {"street": "Prešernova ulica 9", "postal": "3000", "city": "Celje", "notes": ""}},
    {"firstName": "Eva", "lastName": "Novak", "email": "eva.novak@example.com", "phone": "041 777 014", "createdAt": "2026-10-02", "startedAt": "2026-10-06", "size": "mala", "day": "torek", "swaps": [], "address": {"street": "Resljeva cesta 7", "postal": "1000", "city": "Ljubljana", "notes": "Pisarna v pritličju, zvoni Novak"}},
    {"firstName": "Tine", "lastName": "Zupan", "email": "tine.zupan@example.com", "phone": "031 220 845", "createdAt": "2026-09-18", "startedAt": "2026-09-22", "size": "velika", "day": "cetrtek", "swaps": [{"remove": "cvetaca", "add": "pastinak"}], "address": {"street": "Ljubljanska cesta 14", "postal": "1230", "city": "Domžale", "notes": "Hiša z zeleno ograjo"}},
    {"firstName": "Sara", "lastName": "Kos", "email": "sara.kos@example.com", "phone": "070 334 221", "createdAt": "2026-11-06", "startedAt": "2026-11-11", "size": "srednja", "day": "sreda", "swaps": [], "address": {"street": "Glavni trg 4", "postal": "8000", "city": "Novo mesto", "notes": ""}},
    {"firstName": "Peter", "lastName": "Hribar", "email": "peter.hribar@example.com", "phone": "051 909 332", "createdAt": "2026-09-28", "startedAt": "2026-10-01", "size": "mala", "day": "torek", "swaps": [{"remove": "bucke-hokaido", "add": "koleraba"}], "address": {"street": "Kidričeva ulica 11", "postal": "6000", "city": "Koper", "notes": "Stanovanje 3, dvigalo desno"}},
    {"firstName": "Nina", "lastName": "Oblak", "email": "nina.oblak@example.com", "phone": "041 616 278", "createdAt": "2026-08-30", "startedAt": "2026-09-03", "size": "srednja", "day": "cetrtek", "swaps": [], "address": {"street": "Tomšičeva ulica 3", "postal": "1241", "city": "Kamnik", "notes": ""}},
    {"firstName": "Gregor", "lastName": "Vidmar", "email": "gregor.vidmar@example.com", "phone": "031 818 440", "createdAt": "2026-11-02", "startedAt": "2026-11-03", "size": "mala", "day": "torek", "swaps": [], "address": {"street": "Stara cesta 6", "postal": "1360", "city": "Vrhnika", "notes": "Zaboj pod nadstreškom"}},
    {"firstName": "Irena", "lastName": "Kovač", "email": "irena.kovac@example.com", "phone": "041 252 963", "createdAt": "2026-09-15", "startedAt": "2026-09-16", "size": "srednja", "day": "sreda", "swaps": [{"remove": "radic", "add": "blitva"}], "address": {"street": "Mestni trg 8", "postal": "4220", "city": "Škofja Loka", "notes": "Koda 1945"}},
    {"firstName": "Blaž", "lastName": "Medved", "email": "blaz.medved@example.com", "phone": "051 147 520", "createdAt": "2026-10-05", "startedAt": "2026-10-08", "size": "velika", "day": "cetrtek", "swaps": [{"remove": "cesen", "add": "drobnjak"}], "address": {"street": "Gorenjska cesta 21", "postal": "4240", "city": "Radovljica", "notes": ""}},
]


class StoreError(Exception):
    pass


def produce_map():
    return {item["id"]: item for item in PRODUCE}


def name_index():
    return {item["id"]: item["name"] for item in PRODUCE}


def produce_name(produce_id):
    item = produce_map().get(produce_id)
    return item["name"] if item else produce_id


def parse_iso(value: str) -> date:
    year, month, day = (int(part) for part in value.split("-"))
    return date(year, month, day)


def iso(value: date) -> str:
    return value.isoformat()


def monday_of(value: date) -> date:
    return value - timedelta(days=value.weekday())


def delivery_on(week_monday: date, day: str) -> date:
    return week_monday + timedelta(days=DAY_OFFSET[day])


def format_date(value) -> str:
    if isinstance(value, str):
        value = parse_iso(value)
    return f"{value.day}. {MONTHS[value.month - 1]} {value.year}"


def week_span_label(week_monday: date) -> str:
    sunday = week_monday + timedelta(days=6)
    if week_monday.month == sunday.month:
        return f"{week_monday.day}.–{sunday.day}. {MONTHS[week_monday.month - 1]}"
    return f"{week_monday.day}. {MONTHS[week_monday.month - 1]} – {sunday.day}. {MONTHS[sunday.month - 1]}"


def short_day(value: date) -> str:
    return f"{value.day}.{value.month}."


def _pbkdf2_python(password: bytes, salt: bytes, rounds: int) -> bytes:
    mac = hmac.new(password, salt + b"\x00\x00\x00\x01", hashlib.sha256).digest()
    mixed = int.from_bytes(mac, "big")
    for _ in range(rounds - 1):
        mac = hmac.new(password, mac, hashlib.sha256).digest()
        mixed ^= int.from_bytes(mac, "big")
    return mixed.to_bytes(32, "big")


def _pbkdf2_webcrypto(password: bytes, salt: bytes, rounds: int):
    try:
        import js
        from pyodide.ffi import run_sync, to_js
    except ImportError:
        return None

    def as_bytes(data: bytes):
        array = js.Uint8Array.new(len(data))
        for index, value in enumerate(data):
            array[index] = value
        return array

    def as_object(mapping):
        return to_js(mapping, dict_converter=js.Object.fromEntries)

    async def derive():
        key = await js.crypto.subtle.importKey(
            "raw",
            as_bytes(password),
            as_object({"name": "PBKDF2"}),
            False,
            to_js(["deriveBits"]),
        )
        bits = await js.crypto.subtle.deriveBits(
            as_object(
                {
                    "name": "PBKDF2",
                    "hash": "SHA-256",
                    "salt": as_bytes(salt),
                    "iterations": rounds,
                }
            ),
            key,
            256,
        )
        return bytes(js.Uint8Array.new(bits).to_py())

    try:
        return run_sync(derive())
    except Exception:
        return None


def _pbkdf2_sha256(password: bytes, salt: bytes, rounds: int) -> bytes:
    native = getattr(hashlib, "pbkdf2_hmac", None)
    if native is not None:
        return native("sha256", password, salt, rounds)
    derived = _pbkdf2_webcrypto(password, salt, rounds)
    if derived is not None:
        return derived
    return _pbkdf2_python(password, salt, rounds)


def hash_password(password: str, salt: str | None = None):
    if salt is None:
        salt = os.urandom(16).hex()
    digest = _pbkdf2_sha256(password.encode("utf-8"), bytes.fromhex(salt), PBKDF_ROUNDS).hex()
    return {"salt": salt, "hash": digest}


def verify_password(password: str, user: dict) -> bool:
    digest = hash_password(password, user["passwordSalt"])["hash"]
    return hmac.compare_digest(digest, user["passwordHash"])


def admin_ok(username: str, password: str) -> bool:
    user_match = hmac.compare_digest(username.strip().encode("utf-8"), b"uurbanija")
    pass_match = hmac.compare_digest(password.encode("utf-8"), b"123")
    return user_match and pass_match


def _memory_db() -> dict:
    if _MEMORY["db"] is None:
        import runtime_files

        _MEMORY["db"] = json.loads(runtime_files.load()["data/db.json"])
    return _MEMORY["db"]


def _binding(env, name):
    if env is None:
        return ""
    try:
        value = getattr(env, name)
    except Exception:
        value = None
    if not value:
        try:
            value = env[name]
        except Exception:
            value = None
    return str(value).strip() if value else ""


def _credentials():
    url = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not (url and key):
        try:
            from flask import has_request_context, request
        except ImportError:
            return None
        if not has_request_context():
            return None
        env = request.environ.get("workers.env")
        url = _binding(env, "SUPABASE_URL").rstrip("/")
        key = _binding(env, "SUPABASE_SERVICE_ROLE_KEY")
    if url and key:
        return url, key
    return None


def _supabase_request(creds, method, path, body=None):
    url, key = creds
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        f"{url}/rest/v1/{path}",
        data=data,
        method=method,
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates,return=minimal",
            "Range": "0-1999",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read()
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")[:240]
        raise StoreError(f"Supabase ni sprejel podatkov ({error.code}). {detail}") from error
    except OSError as error:
        raise StoreError("Povezava s Supabase ni uspela.") from error
    if not raw:
        return []
    return json.loads(raw)


def _address_from_row(row):
    if not row.get("street") and not row.get("city"):
        return None
    return {
        "street": row.get("street") or "",
        "postal": row.get("postal") or "",
        "city": row.get("city") or "",
        "notes": row.get("notes") or "",
    }


def _rows_to_db(customers, subscriptions, orders) -> dict:
    users = []
    for row in customers:
        users.append(
            {
                "id": row["id"],
                "firstName": row["first_name"],
                "lastName": row["last_name"],
                "email": row["email"],
                "phone": row.get("phone") or "",
                "passwordSalt": row.get("password_salt") or "",
                "passwordHash": row.get("password_hash") or "",
                "address": _address_from_row(row),
                "createdAt": str(row["created_at"])[:10],
            }
        )
    subs = []
    for row in subscriptions:
        subs.append(
            {
                "id": row["id"],
                "userId": row["user_id"],
                "size": row["size"],
                "status": row["status"],
                "deliveryDay": row["delivery_day"],
                "swaps": row.get("swaps") or [],
                "startedAt": str(row["started_at"])[:10],
                "pausedAt": str(row["paused_at"])[:10] if row.get("paused_at") else None,
            }
        )
    parsed_orders = []
    for row in orders:
        parsed_orders.append(
            {
                "id": row["id"],
                "userId": row["user_id"],
                "subscriptionId": row["subscription_id"],
                "weekOf": str(row["week_of"])[:10],
                "deliveryDate": str(row["delivery_date"])[:10],
                "deliveryDay": row["delivery_day"],
                "size": row["size"],
                "status": row["status"],
                "items": row.get("items") or [],
                "address": _address_from_row(row) or {"street": "", "postal": "", "city": "", "notes": ""},
                "priceMonthly": row["price_monthly"],
            }
        )
    return {"users": users, "subscriptions": subs, "orders": parsed_orders}


def _customer_row(user):
    address = user.get("address") or {}
    return {
        "id": user["id"],
        "first_name": user["firstName"],
        "last_name": user["lastName"],
        "email": user["email"],
        "phone": user.get("phone") or "",
        "password_salt": user.get("passwordSalt") or None,
        "password_hash": user.get("passwordHash") or None,
        "street": address.get("street") or "",
        "postal": address.get("postal") or "",
        "city": address.get("city") or "",
        "notes": address.get("notes") or "",
        "created_at": user["createdAt"],
    }


def _subscription_row(sub):
    return {
        "id": sub["id"],
        "user_id": sub["userId"],
        "size": sub["size"],
        "status": sub["status"],
        "delivery_day": sub["deliveryDay"],
        "swaps": sub.get("swaps") or [],
        "started_at": sub["startedAt"],
        "paused_at": sub.get("pausedAt"),
    }


def _order_row(order):
    address = order.get("address") or {}
    return {
        "id": order["id"],
        "user_id": order["userId"],
        "subscription_id": order["subscriptionId"],
        "week_of": order["weekOf"],
        "delivery_date": order["deliveryDate"],
        "delivery_day": order["deliveryDay"],
        "size": order["size"],
        "status": order["status"],
        "items": order.get("items") or [],
        "street": address.get("street") or "",
        "postal": address.get("postal") or "",
        "city": address.get("city") or "",
        "notes": address.get("notes") or "",
        "price_monthly": order["priceMonthly"],
    }


def _upsert(creds, table, rows):
    for start in range(0, len(rows), 40):
        chunk = rows[start : start + 40]
        _supabase_request(creds, "POST", f"{table}?on_conflict=id", chunk)


def _delete_missing(creds, table, ids):
    if not ids:
        _supabase_request(creds, "DELETE", f"{table}?id=not.is.null")
        return
    listed = ",".join(f'"{item}"' for item in ids)
    _supabase_request(creds, "DELETE", f"{table}?id=not.in.({listed})")


def _load_supabase(creds) -> dict:
    customers = _supabase_request(creds, "GET", "customers?select=*")
    subscriptions = _supabase_request(creds, "GET", "subscriptions?select=*")
    orders = _supabase_request(creds, "GET", "orders?select=*")
    return _rows_to_db(customers, subscriptions, orders)


def _save_supabase(creds, db: dict) -> None:
    _upsert(creds, "customers", [_customer_row(user) for user in db["users"]])
    _upsert(creds, "subscriptions", [_subscription_row(sub) for sub in db["subscriptions"]])
    _upsert(creds, "orders", [_order_row(order) for order in db["orders"]])
    _delete_missing(creds, "orders", [order["id"] for order in db["orders"]])


def _read_file():
    if not DB_PATH.exists():
        return None
    try:
        return json.loads(DB_PATH.read_text(encoding="utf-8"))
    except OSError:
        return None


def _write_unlocked(db: dict) -> None:
    try:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        temporary = DB_PATH.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(db, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(DB_PATH)
    except OSError:
        _MEMORY["db"] = db


def _load_unlocked() -> dict:
    creds = _credentials()
    if creds:
        return _load_supabase(creds)
    db = _read_file()
    if db is None:
        return copy.deepcopy(_memory_db())
    return db


def _save_unlocked(db: dict) -> None:
    creds = _credentials()
    if creds:
        _save_supabase(creds, db)
        return
    if _read_file() is None and not DB_PATH.exists():
        _MEMORY["db"] = db
        return
    _write_unlocked(db)


def read_db() -> dict:
    with _lock:
        return _load_unlocked()


def update_db(mutator):
    with _lock:
        db = _load_unlocked()
        result = mutator(db)
        _save_unlocked(db)
        return result


def get_user(db, user_id):
    return next((user for user in db["users"] if user["id"] == user_id), None)


def get_user_by_email(db, email):
    needle = email.strip().lower()
    return next((user for user in db["users"] if user["email"] == needle), None)


def get_subscription(db, user_id):
    matches = [sub for sub in db["subscriptions"] if sub["userId"] == user_id]
    return matches[-1] if matches else None


def get_order(db, order_id):
    return next((order for order in db["orders"] if order["id"] == order_id), None)


def require_subscription(db, user_id):
    sub = get_subscription(db, user_id)
    if not sub:
        raise StoreError("Najprej izberi košarico.")
    return sub


def next_order_id(db) -> str:
    best = 2400
    for order in db["orders"]:
        try:
            best = max(best, int(order["id"].split("-")[1]))
        except (IndexError, ValueError):
            continue
    return f"KOS-{best + 1}"


def next_sub_id(db) -> str:
    best = 1000
    for sub in db["subscriptions"]:
        try:
            best = max(best, int(sub["id"].split("-")[1]))
        except (IndexError, ValueError):
            continue
    return f"SUB-{best + 1}"


def next_user_id(db) -> str:
    best = 0
    for user in db["users"]:
        try:
            best = max(best, int(user["id"][1:]))
        except ValueError:
            continue
    return f"u{best + 1:03d}"


def normalize_swaps(size: str, swaps) -> list[dict]:
    if size not in BASKETS:
        raise StoreError("Neznana velikost košarice.")
    swaps = swaps or []
    limit = BASKETS[size]["swaps"]
    if len(swaps) > limit:
        raise StoreError(f"Pri tej velikosti lahko zamenjaš največ {limit} sestavin.")
    catalog = produce_map()
    current = list(BASKETS[size]["produce"])
    clean = []
    for swap in swaps:
        remove = swap.get("remove")
        add = swap.get("add")
        if remove not in current:
            raise StoreError("Ena od sestavin ni v tej košarici.")
        if add not in catalog:
            raise StoreError("Izbrana zelenjava ta teden ni na voljo.")
        if add in current:
            raise StoreError(f"{catalog[add]['name']} je že v košarici.")
        current[current.index(remove)] = add
        clean.append({"remove": remove, "add": add})
    return clean


def compose_items(size: str, swaps) -> list[dict]:
    applied = normalize_swaps(size, swaps)
    ids = list(BASKETS[size]["produce"])
    instead = {}
    for swap in applied:
        ids[ids.index(swap["remove"])] = swap["add"]
        instead[swap["add"]] = swap["remove"]
    catalog = produce_map()
    items = []
    for produce_id in ids:
        item = catalog[produce_id]
        items.append(
            {
                "id": produce_id,
                "name": item["name"],
                "qty": item["qty"][size],
                "hint": item["hint"],
                "group": item["group"],
                "swapped": produce_id in instead,
                "insteadOf": catalog[instead[produce_id]]["name"] if produce_id in instead else None,
            }
        )
    return items


def basket_public(size: str) -> dict:
    raw = BASKETS[size]
    catalog = produce_map()
    items = []
    for produce_id in raw["produce"]:
        item = catalog[produce_id]
        items.append({**item, "qty_label": item["qty"][size]})
    return {**raw, "items": items, "weekly": raw["price"] // 4, "pieces": len(raw["produce"])}


def all_baskets():
    return [basket_public(size) for size in BASKETS]


def swap_options(size: str):
    taken = set(BASKETS[size]["produce"])
    return [item for item in PRODUCE if item["id"] not in taken]


def swap_map(swaps) -> dict:
    return {swap["remove"]: swap["add"] for swap in swaps or []}


def produce_groups():
    groups = []
    buckets = {}
    for item in PRODUCE:
        bucket = buckets.get(item["group"])
        if bucket is None:
            bucket = []
            buckets[item["group"]] = bucket
            groups.append({"name": item["group"], "icon": GROUP_ICON[item["group"]], "items": bucket})
        bucket.append(item)
    return groups


def swaps_from_form(size: str, form) -> list[dict]:
    raw = []
    for produce_id in BASKETS[size]["produce"]:
        add = (form.get(f"swap_{produce_id}") or "").strip()
        if add:
            raw.append({"remove": produce_id, "add": add})
    return normalize_swaps(size, raw)


def parse_person(form):
    first = (form.get("ime") or "").strip()
    last = (form.get("priimek") or "").strip()
    email = (form.get("email") or "").strip().lower()
    password = form.get("geslo") or ""
    password2 = form.get("geslo2") or ""
    if len(first) < 2 or len(last) < 2:
        raise StoreError("Vpiši ime in priimek.")
    if not EMAIL_RE.fullmatch(email):
        raise StoreError("E-pošta ni veljavna.")
    if len(password) < 6:
        raise StoreError("Geslo naj ima vsaj 6 znakov.")
    if password != password2:
        raise StoreError("Gesli se ne ujemata.")
    return first, last, email, password


def parse_address(form):
    street = (form.get("ulica") or "").strip()
    postal = (form.get("posta") or "").strip()
    city = (form.get("mesto") or "").strip()
    notes = (form.get("opombe") or "").strip()
    phone = (form.get("telefon") or "").strip()
    day = (form.get("dan") or "").strip()
    if len(street) < 3:
        raise StoreError("Vpiši ulico in hišno številko.")
    if not postal.isdigit() or len(postal) != 4:
        raise StoreError("Poštna številka ima štiri števke.")
    if len(city) < 2:
        raise StoreError("Vpiši kraj.")
    if len(notes) > 200:
        raise StoreError("Opombe so predolge. Zadošča kratek namig za voznika.")
    if phone and len(re.sub(r"\s+", "", phone)) < 6:
        raise StoreError("Telefonska številka je prekratka.")
    if day and day not in DAY_OFFSET:
        raise StoreError("Izberi dan dostave.")
    address = {"street": street, "postal": postal, "city": city, "notes": notes}
    return address, day, phone


def create_user(db, first, last, email, password, phone=""):
    if get_user_by_email(db, email):
        raise StoreError("Ta e-pošta je že registrirana.")
    secret = hash_password(password)
    user = {
        "id": next_user_id(db),
        "firstName": first.strip(),
        "lastName": last.strip(),
        "email": email.strip().lower(),
        "phone": phone.strip(),
        "passwordSalt": secret["salt"],
        "passwordHash": secret["hash"],
        "address": None,
        "createdAt": date.today().isoformat(),
    }
    db["users"].append(user)
    return user


def authenticate(db, email, password):
    user = get_user_by_email(db, email or "")
    if not user or not verify_password(password or "", user):
        raise StoreError("E-pošta ali geslo ni pravo.")
    return user


def upcoming_mondays(today: date, day: str, count: int = 4):
    monday = monday_of(today)
    found = []
    for step in range(0, 12):
        week = monday + timedelta(weeks=step)
        when = delivery_on(week, day)
        if when > today:
            found.append(week)
        if len(found) == count:
            break
    return found


def make_order(db, user, sub, week: date, when: date, status: str):
    return {
        "id": next_order_id(db),
        "userId": user["id"],
        "subscriptionId": sub["id"],
        "weekOf": iso(week),
        "deliveryDate": iso(when),
        "deliveryDay": sub["deliveryDay"],
        "size": sub["size"],
        "status": status,
        "items": compose_items(sub["size"], sub["swaps"]),
        "address": copy.deepcopy(user["address"]),
        "priceMonthly": BASKETS[sub["size"]]["price"],
    }


def order_status_for(when: date, today: date, sub) -> str:
    if sub["status"] == "pavzirana":
        return "pavzirano"
    if when <= monday_of(today) + timedelta(days=6):
        return "pakiranje"
    return "nacrtovano"


def ensure_future_orders(db, sub, user):
    today = date.today()
    existing = {order["deliveryDate"] for order in db["orders"] if order["subscriptionId"] == sub["id"]}
    created = []
    for week in upcoming_mondays(today, sub["deliveryDay"], 4):
        when = delivery_on(week, sub["deliveryDay"])
        if iso(when) in existing:
            continue
        order = make_order(db, user, sub, week, when, order_status_for(when, today, sub))
        db["orders"].append(order)
        existing.add(order["deliveryDate"])
        created.append(order)
    return created


def place_subscription(db, user_id, size, swaps, day):
    if day not in DAY_OFFSET:
        raise StoreError("Izberi dan dostave.")
    user = get_user(db, user_id)
    if not user or not user.get("address") or not user["address"].get("street"):
        raise StoreError("Manjka naslov dostave.")
    clean_swaps = normalize_swaps(size, swaps)
    today = date.today()
    sub = get_subscription(db, user_id)
    if sub is None:
        sub = {
            "id": next_sub_id(db),
            "userId": user_id,
            "size": size,
            "status": "aktivna",
            "deliveryDay": day,
            "swaps": clean_swaps,
            "startedAt": iso(today),
            "pausedAt": None,
        }
        db["subscriptions"].append(sub)
    else:
        sub["size"] = size
        sub["status"] = "aktivna"
        sub["deliveryDay"] = day
        sub["swaps"] = clean_swaps
        sub["pausedAt"] = None
        db["orders"] = [
            order
            for order in db["orders"]
            if not (
                order["subscriptionId"] == sub["id"]
                and order["status"] in OPEN_STATUSES
                and parse_iso(order["deliveryDate"]) >= today
            )
        ]
    created = ensure_future_orders(db, sub, user)
    if not created:
        upcoming = [
            order
            for order in db["orders"]
            if order["subscriptionId"] == sub["id"] and order["status"] in ACTIVE_ROUTE
        ]
        if not upcoming:
            raise StoreError("Ni prostega termina za dostavo.")
        created = upcoming
    first = min(created, key=lambda order: order["deliveryDate"])
    return sub, first


def update_swaps(db, user_id, swaps):
    sub = require_subscription(db, user_id)
    sub["swaps"] = normalize_swaps(sub["size"], swaps)
    for order in db["orders"]:
        if order["subscriptionId"] == sub["id"] and order["status"] == "nacrtovano":
            order["items"] = compose_items(sub["size"], sub["swaps"])
    return sub


def update_address(db, user_id, address, phone):
    user = get_user(db, user_id)
    if not user:
        raise StoreError("Račun ne obstaja.")
    user["address"] = address
    if phone:
        user["phone"] = phone
    today = date.today()
    for order in db["orders"]:
        if (
            order["userId"] == user_id
            and order["status"] in {"nacrtovano", "pakiranje"}
            and parse_iso(order["deliveryDate"]) >= today
        ):
            order["address"] = copy.deepcopy(address)
    return user


def update_day(db, user_id, day):
    if day not in DAY_OFFSET:
        raise StoreError("Izberi dan dostave.")
    sub = require_subscription(db, user_id)
    user = get_user(db, user_id)
    sub["deliveryDay"] = day
    today = date.today()
    db["orders"] = [
        order
        for order in db["orders"]
        if not (
            order["subscriptionId"] == sub["id"]
            and order["status"] == "nacrtovano"
            and parse_iso(order["deliveryDate"]) > today
        )
    ]
    ensure_future_orders(db, sub, user)
    return sub


def set_paused(db, user_id, paused: bool):
    sub = require_subscription(db, user_id)
    user = get_user(db, user_id)
    today = date.today()
    if paused:
        sub["status"] = "pavzirana"
        sub["pausedAt"] = iso(today)
        for order in db["orders"]:
            if (
                order["subscriptionId"] == sub["id"]
                and order["status"] in {"nacrtovano", "pakiranje"}
                and parse_iso(order["deliveryDate"]) >= today
            ):
                order["status"] = "pavzirano"
    else:
        sub["status"] = "aktivna"
        sub["pausedAt"] = None
        for order in db["orders"]:
            if (
                order["subscriptionId"] == sub["id"]
                and order["status"] == "pavzirano"
                and parse_iso(order["deliveryDate"]) > today
            ):
                when = parse_iso(order["deliveryDate"])
                order["status"] = order_status_for(when, today, sub)
                order["items"] = compose_items(sub["size"], sub["swaps"])
        ensure_future_orders(db, sub, user)
    return sub


def set_order_status(db, order_id, status):
    if status not in STATUS_LABEL:
        raise StoreError("Neznan status.")
    order = get_order(db, order_id)
    if not order:
        raise StoreError("Naročilo ne obstaja.")
    order["status"] = status
    return order


def present_order(db, order):
    user = get_user(db, order["userId"]) or {}
    customer = f"{user.get('firstName', '')} {user.get('lastName', '')}".strip()
    swap_count = sum(1 for item in order["items"] if item.get("swapped"))
    return {
        **order,
        "customer": customer or "Neznana stranka",
        "email": user.get("email", ""),
        "phone": user.get("phone", ""),
        "swapCount": swap_count,
        "sizeName": BASKETS[order["size"]]["name"],
        "dayName": DAY_LABEL[order["deliveryDay"]],
        "statusName": STATUS_LABEL[order["status"]],
    }


def present_subscription(sub):
    if not sub:
        return None
    lines = [f"{produce_name(swap['remove'])} → {produce_name(swap['add'])}" for swap in sub["swaps"]]
    return {
        **sub,
        "sizeName": BASKETS[sub["size"]]["name"],
        "price": BASKETS[sub["size"]]["price"],
        "weekly": BASKETS[sub["size"]]["price"] // 4,
        "swapLimit": BASKETS[sub["size"]]["swaps"],
        "dayName": DAY_LABEL[sub["deliveryDay"]],
        "statusName": "Aktivna" if sub["status"] == "aktivna" else "Pavzirana",
        "swapLines": lines,
    }


def account_snapshot(db, user_id):
    user = get_user(db, user_id)
    sub = present_subscription(get_subscription(db, user_id))
    orders = [present_order(db, order) for order in db["orders"] if order["userId"] == user_id]
    orders.sort(key=lambda order: order["deliveryDate"])
    upcoming = [order for order in orders if order["status"] != "dostavljeno"]
    history = [order for order in orders if order["status"] == "dostavljeno"]
    history.reverse()
    return {
        "user": user,
        "subscription": sub,
        "upcoming": upcoming,
        "history": history,
        "next_order": upcoming[0] if upcoming else None,
    }


def overview(db, today: date | None = None):
    today = today or date.today()
    monday = monday_of(today)
    sunday = monday + timedelta(days=6)
    active = [sub for sub in db["subscriptions"] if sub["status"] == "aktivna"]
    paused = [sub for sub in db["subscriptions"] if sub["status"] == "pavzirana"]
    mrr = sum(BASKETS[sub["size"]]["price"] for sub in active)
    week_orders = [
        order
        for order in db["orders"]
        if monday <= parse_iso(order["deliveryDate"]) <= sunday and order["status"] != "pavzirano"
    ]
    paused_this_week = [
        order
        for order in db["orders"]
        if monday <= parse_iso(order["deliveryDate"]) <= sunday and order["status"] == "pavzirano"
    ]
    swaps = sum(1 for order in week_orders for item in order["items"] if item.get("swapped"))
    size_rows = []
    active_count = len(active) or 1
    for size, basket in BASKETS.items():
        count = sum(1 for sub in active if sub["size"] == size)
        size_rows.append(
            {
                "id": size,
                "name": basket["name"],
                "count": count,
                "price": basket["price"],
                "share": round(count / active_count * 100) if active else 0,
            }
        )
    by_status = {key: 0 for key in ("dostavljeno", "na_poti", "pakiranje", "nacrtovano")}
    for order in week_orders:
        by_status[order["status"]] = by_status.get(order["status"], 0) + 1
    cities = {}
    for order in week_orders:
        city = order["address"]["city"]
        cities[city] = cities.get(city, 0) + 1
    city_rows = [{"city": city, "count": count} for city, count in sorted(cities.items(), key=lambda row: (-row[1], row[0]))]
    recent = sorted(db["orders"], key=lambda order: (order["deliveryDate"], order["id"]), reverse=True)[:8]
    month_prefix = today.strftime("%Y-%m")
    new_customers = sum(1 for user in db["users"] if user["createdAt"].startswith(month_prefix))
    weeks = []
    for step in range(-7, 2):
        week = monday + timedelta(weeks=step)
        end = week + timedelta(days=6)
        count = sum(
            1
            for order in db["orders"]
            if week <= parse_iso(order["deliveryDate"]) <= end and order["status"] != "pavzirano"
        )
        weeks.append({"label": short_day(week), "count": count, "current": step == 0})
    peak = max((week["count"] for week in weeks), default=1) or 1
    for week in weeks:
        week["share"] = round(week["count"] / peak * 100)
    return {
        "today": iso(today),
        "todayLabel": format_date(today),
        "weekLabel": week_span_label(monday),
        "weekOf": iso(monday),
        "active": len(active),
        "paused": len(paused),
        "customers": len(db["users"]),
        "mrr": mrr,
        "weekBaskets": len(week_orders),
        "pausedThisWeek": len(paused_this_week),
        "swaps": swaps,
        "onRoute": by_status.get("na_poti", 0),
        "deliveredToday": by_status.get("dostavljeno", 0),
        "sizes": size_rows,
        "statuses": [
            {"id": key, "name": STATUS_LABEL[key], "count": by_status.get(key, 0)}
            for key in ("pakiranje", "na_poti", "dostavljeno", "nacrtovano")
        ],
        "cities": city_rows,
        "recent": [present_order(db, order) for order in recent],
        "weeks": weeks,
        "newCustomers": new_customers,
    }


def week_choices(db):
    mondays = sorted({order["weekOf"] for order in db["orders"]}, reverse=True)
    return [{"value": monday, "label": week_span_label(parse_iso(monday))} for monday in mondays]


def filter_orders(db, query="", status="", size="", week=""):
    needle = query.strip().lower()
    rows = []
    for order in db["orders"]:
        if status and order["status"] != status:
            continue
        if size and order["size"] != size:
            continue
        if week and order["weekOf"] != week:
            continue
        presented = present_order(db, order)
        haystack = " ".join(
            [
                presented["id"],
                presented["customer"],
                presented["email"],
                presented["address"]["city"],
                presented["address"]["street"],
                presented["address"]["postal"],
            ]
        ).lower()
        if needle and needle not in haystack:
            continue
        rows.append(presented)
    rows.sort(key=lambda order: (order["deliveryDate"], order["id"]), reverse=True)
    return rows


def paginate(items, page, per_page=12):
    total = len(items)
    pages = max(1, (total + per_page - 1) // per_page)
    page = min(max(page, 1), pages)
    start = (page - 1) * per_page
    return {"rows": items[start : start + per_page], "page": page, "pages": pages, "total": total}


def deliveries_for_week(db, week_iso: str):
    monday = parse_iso(week_iso)
    days = []
    paused = 0
    dates = []
    for key in DAY_OFFSET:
        when = delivery_on(monday, key)
        dates.append(iso(when))
        rows = []
        for order in db["orders"]:
            if order["deliveryDate"] != iso(when):
                continue
            if order["status"] == "pavzirano":
                paused += 1
                continue
            rows.append(present_order(db, order))
        rows.sort(key=lambda order: (order["address"]["postal"], order["customer"]))
        days.append({"key": key, "label": DAY_LABEL[key], "date": iso(when), "orders": rows})
    return {"days": days, "paused": paused, "label": week_span_label(monday), "weekOf": week_iso}


def customer_rows(db, query=""):
    needle = query.strip().lower()
    rows = []
    for user in db["users"]:
        sub = present_subscription(get_subscription(db, user["id"]))
        delivered = sum(1 for order in db["orders"] if order["userId"] == user["id"] and order["status"] == "dostavljeno")
        city = (user.get("address") or {}).get("city", "")
        row = {
            "id": user["id"],
            "name": f"{user['firstName']} {user['lastName']}",
            "email": user["email"],
            "phone": user["phone"],
            "city": city,
            "address": user.get("address"),
            "createdAt": user["createdAt"],
            "subscription": sub,
            "delivered": delivered,
        }
        haystack = f"{row['name']} {row['email']} {city}".lower()
        if needle and needle not in haystack:
            continue
        rows.append(row)
    rows.sort(key=lambda row: row["name"])
    return rows


def address_values(user, form=None, day=""):
    if form is not None:
        return {
            "ulica": form.get("ulica", ""),
            "posta": form.get("posta", ""),
            "mesto": form.get("mesto", ""),
            "opombe": form.get("opombe", ""),
            "telefon": form.get("telefon", ""),
            "dan": form.get("dan", ""),
        }
    address = user.get("address") or {}
    return {
        "ulica": address.get("street", ""),
        "posta": address.get("postal", ""),
        "mesto": address.get("city", ""),
        "opombe": address.get("notes", ""),
        "telefon": user.get("phone", ""),
        "dan": day,
    }


def status_for_seed(when: date, today: date, paused_at: date | None) -> str:
    if paused_at and when >= paused_at and when >= today:
        return "pavzirano"
    if when < today:
        return "dostavljeno"
    if when == today:
        return "na_poti"
    if when <= monday_of(today) + timedelta(days=6):
        return "pakiranje"
    return "nacrtovano"


def seed_database():
    for person in PEOPLE:
        normalize_swaps(person["size"], person["swaps"])
    today = date.today()
    monday = monday_of(today)
    weeks = [monday + timedelta(weeks=step) for step in range(-8, 2)]
    db = {
        "about": {
            "note": "Lokalna JSON baza Košarice. Ponovno jo ustvariš s python seed.py.",
            "seededAt": iso(today),
        },
        "users": [],
        "subscriptions": [],
        "orders": [],
    }
    for person in PEOPLE:
        secret = hash_password(DEMO_PASSWORD)
        user = {
            "id": next_user_id(db),
            "firstName": person["firstName"],
            "lastName": person["lastName"],
            "email": person["email"],
            "phone": person["phone"],
            "passwordSalt": secret["salt"],
            "passwordHash": secret["hash"],
            "address": copy.deepcopy(person["address"]),
            "createdAt": person["createdAt"],
        }
        paused_at = person.get("pausedAt")
        sub = {
            "id": next_sub_id(db),
            "userId": user["id"],
            "size": person["size"],
            "status": "pavzirana" if paused_at else "aktivna",
            "deliveryDay": person["day"],
            "swaps": normalize_swaps(person["size"], person["swaps"]),
            "startedAt": person["startedAt"],
            "pausedAt": paused_at,
        }
        db["users"].append(user)
        db["subscriptions"].append(sub)
        started = parse_iso(person["startedAt"])
        pause_date = parse_iso(paused_at) if paused_at else None
        for week in weeks:
            when = delivery_on(week, person["day"])
            if when < started:
                continue
            status = status_for_seed(when, today, pause_date)
            if person["email"] == "gregor.vidmar@example.com" and when == today and status == "na_poti":
                status = "dostavljeno"
            db["orders"].append(make_order(db, user, sub, week, when, status))
    db["orders"].sort(key=lambda order: (order["deliveryDate"], order["id"]))
    with _lock:
        _write_unlocked(db)
    return overview(db, today)
