"""Normalisation: titles, venues, cities, dates, dedup keys.

The dedup key is deliberately coarse (venue + local date + a few title tokens) so the same show
listed by a venue, a ticketing platform and an aggregator collapses into one inventory record.
"""
import datetime as dt
import hashlib
import html
import re
import unicodedata
from zoneinfo import ZoneInfo

from dateutil import parser as dtparser

from .config import LOCAL_TZ

TZ = ZoneInfo(LOCAL_TZ)

# ---------------------------------------------------------------- text
_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s&]")
STOP = {
    "the", "a", "an", "and", "with", "w", "feat", "featuring", "ft", "of", "at", "in", "on", "live",
    "presents", "present", "presented", "by", "plus", "special", "guest", "guests", "night", "show",
    "concert", "tour", "band", "trio", "quartet", "quintet", "duo", "solo", "evening", "music",
    "tickets", "ticket", "free", "doors", "pm", "am", "sold", "out", "early", "late", "set", "sets",
    "album", "release", "party", "celebration", "performance", "performances", "series", "to", "for",
    "from", "vs", "x", "&", "an", "annual", "th", "st", "nd", "rd",
}


def clean_text(s: str | None) -> str:
    if not s:
        return ""
    s = html.unescape(str(s))
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = _WS.sub(" ", s).strip()
    return s


def fold(s: str) -> str:
    """Lowercase ASCII fold without punctuation."""
    s = unicodedata.normalize("NFKD", clean_text(s)).encode("ascii", "ignore").decode()
    s = s.lower().replace("&", " and ")
    s = _PUNCT.sub(" ", s)
    return _WS.sub(" ", s).strip()


def tokens(s: str) -> list[str]:
    return [t for t in fold(s).split() if t not in STOP and len(t) > 1]


def slug(s: str, n: int = 60) -> str:
    return re.sub(r"[^a-z0-9]+", "-", fold(s)).strip("-")[:n]


# ---------------------------------------------------------------- venues
VENUE_ALIASES = {
    "freight salvage": "Freight & Salvage",
    "freight and salvage": "Freight & Salvage",
    "the freight": "Freight & Salvage",
    "freight salvage coffeehouse": "Freight & Salvage",
    "cafe du nord": "Cafe du Nord",
    "swedish american hall": "Swedish American Hall",
    "the chapel": "The Chapel",
    "chapel": "The Chapel",
    "great american music hall": "Great American Music Hall",
    "gamh": "Great American Music Hall",
    "bottom of the hill": "Bottom of the Hill",
    "the independent": "The Independent",
    "the fillmore": "The Fillmore",
    "fillmore": "The Fillmore",
    "fox theater": "Fox Theater Oakland",
    "fox theater oakland": "Fox Theater Oakland",
    "the fox oakland": "Fox Theater Oakland",
    "paramount theatre": "Paramount Theatre Oakland",
    "paramount theatre oakland": "Paramount Theatre Oakland",
    "greek theatre": "Greek Theatre Berkeley",
    "greek theatre berkeley": "Greek Theatre Berkeley",
    "william randolph hearst greek theatre": "Greek Theatre Berkeley",
    "the uc theatre": "The UC Theatre",
    "uc theatre": "The UC Theatre",
    "uc theatre taube family music hall": "The UC Theatre",
    "the new parish": "The New Parish",
    "new parish": "The New Parish",
    "little hill lounge": "Little Hill Lounge",
    "the back room": "The Back Room",
    "back room": "The Back Room",
    "the back room berkeley": "The Back Room",
    "fifth street farms": "Fifth Street Farms",
    "5th street farms": "Fifth Street Farms",
    "hillside club": "Hillside Club",
    "the hillside club": "Hillside Club",
    "berkeley hillside club": "Hillside Club",
    "ashkenaz": "Ashkenaz",
    "ashkenaz music dance community center": "Ashkenaz",
    "ashkenaz music and dance community center": "Ashkenaz",
    "the starry plough": "The Starry Plough",
    "starry plough": "The Starry Plough",
    "the starry plough pub": "The Starry Plough",
    "ivy room": "Ivy Room",
    "the ivy room": "Ivy Room",
    "elis mile high club": "Eli's Mile High Club",
    "eli s mile high club": "Eli's Mile High Club",
    "thee stork club": "Thee Stork Club",
    "stork club": "Thee Stork Club",
    "the stork club": "Thee Stork Club",
    "down home music": "Down Home Music",
    "down home music store": "Down Home Music",
    "sfjazz center": "SFJAZZ Center",
    "sfjazz": "SFJAZZ Center",
    "miner auditorium": "SFJAZZ Center",
    "robert n miner auditorium": "SFJAZZ Center",
    "joe henderson lab": "SFJAZZ Center",
    "joe henderson lab sfjazz center": "SFJAZZ Center",
    "zellerbach hall": "Zellerbach Hall",
    "zellerbach playhouse": "Zellerbach Playhouse",
    "hertz hall": "Hertz Hall",
    "sweetwater music hall": "Sweetwater Music Hall",
    "sweetwater": "Sweetwater Music Hall",
    "yoshis": "Yoshi's Oakland",
    "yoshi s": "Yoshi's Oakland",
    "yoshis oakland": "Yoshi's Oakland",
    "the sound room": "The Sound Room",
    "guild theatre": "Guild Theatre",
    "the guild theatre": "Guild Theatre",
    "felton music hall": "Felton Music Hall",
    "moes alley": "Moe's Alley",
    "moe s alley": "Moe's Alley",
    "kuumbwa jazz center": "Kuumbwa Jazz",
    "kuumbwa jazz": "Kuumbwa Jazz",
    "the lost church": "The Lost Church",
    "lost church": "The Lost Church",
    "the lost church san francisco": "The Lost Church",
    "rickshaw stop": "Rickshaw Stop",
    "bing concert hall": "Bing Concert Hall",
    "rancho nicasio": "Rancho Nicasio",
    "hopmonk tavern": "HopMonk Tavern",
    "hopmonk tavern novato": "HopMonk Tavern Novato",
    "hopmonk tavern sebastopol": "HopMonk Tavern Sebastopol",
    "hopmonk tavern sonoma": "HopMonk Tavern Sonoma",
    "siesta valley bowl": "Siesta Valley Bowl",
    "berkeley repertory theatre": "Berkeley Rep",
    "berkeley rep": "Berkeley Rep",
    "roda theatre": "Berkeley Rep",
    "peets theatre": "Berkeley Rep",
    "act strand theater": "A.C.T. Strand Theater",
    "strand theater": "A.C.T. Strand Theater",
    "toni rembe theater": "A.C.T. Toni Rembe Theater",
    "geary theater": "A.C.T. Toni Rembe Theater",
    "aurora theatre": "Aurora Theatre",
    "aurora theatre company": "Aurora Theatre",
    "ashby stage": "Shotgun Players (Ashby Stage)",
    "shotgun players": "Shotgun Players (Ashby Stage)",
    "magic theatre": "Magic Theatre",
    "san francisco playhouse": "San Francisco Playhouse",
    "sf playhouse": "San Francisco Playhouse",
    "marin theatre": "Marin Theatre",
    "marin theatre company": "Marin Theatre",
    "z space": "Z Space",
    "red poppy art house": "Red Poppy Art House",
    "bird beckett books records": "Bird & Beckett",
    "bird and beckett books and records": "Bird & Beckett",
    "bird beckett": "Bird & Beckett",
    "black cat": "Black Cat SF",
    "keys jazz bistro": "Keys Jazz Bistro",
    "the sound room oakland": "The Sound Room",
    "henry j kaiser center for the arts": "Henry J. Kaiser Center for the Arts",
    "kaiser center for the arts": "Henry J. Kaiser Center for the Arts",
    "the chase center": "Chase Center",
}


def norm_venue(name: str | None) -> str:
    f = fold(name or "")
    f = re.sub(r"\b(the )?(san francisco|oakland|berkeley|ca)$", "", f).strip()
    if f in VENUE_ALIASES:
        return VENUE_ALIASES[f]
    f2 = re.sub(r"^the ", "", f)
    if f2 in VENUE_ALIASES:
        return VENUE_ALIASES[f2]
    return clean_text(name or "").strip()


def venue_key(name: str | None) -> str:
    v = norm_venue(name)
    return slug(v, 40)


# ---------------------------------------------------------------- region
BAY_AREA_CITIES = {
    "san francisco", "oakland", "berkeley", "el cerrito", "albany", "richmond", "emeryville", "alameda",
    "piedmont", "san leandro", "hayward", "castro valley", "fremont", "union city", "newark", "san lorenzo",
    "walnut creek", "lafayette", "orinda", "moraga", "concord", "pleasant hill", "martinez", "danville",
    "san ramon", "dublin", "pleasanton", "livermore", "brentwood", "antioch", "pittsburg", "benicia",
    "vallejo", "napa", "sonoma", "petaluma", "santa rosa", "sebastopol", "healdsburg", "novato",
    "san rafael", "mill valley", "sausalito", "fairfax", "san anselmo", "nicasio", "point reyes station",
    "stinson beach", "bolinas", "tiburon", "larkspur", "corte madera", "san mateo", "burlingame",
    "millbrae", "south san francisco", "daly city", "pacifica", "half moon bay", "redwood city",
    "menlo park", "palo alto", "stanford", "mountain view", "los altos", "sunnyvale", "santa clara",
    "cupertino", "san jose", "saratoga", "los gatos", "campbell", "milpitas", "santa cruz", "felton",
    "capitola", "aptos", "soquel", "scotts valley", "ben lomond", "boulder creek", "watsonville",
    "monterey", "carmel", "pacific grove", "big sur", "sacramento", "davis", "woodland", "winters",
    "guerneville", "occidental", "bodega bay", "calistoga", "st helena", "yountville", "vacaville",
    "fairfield", "suisun city", "kensington", "pinole", "hercules", "crockett", "port costa", "rodeo",
    "san pablo", "el sobrante", "oakley", "clayton", "sunol", "niles", "woodside", "portola valley",
    "san carlos", "belmont", "foster city", "brisbane", "san bruno", "pescadero", "la honda", "gilroy",
    "morgan hill", "hollister", "san juan bautista", "nevada city", "grass valley", "auburn", "placerville",
    "truckee", "south lake tahoe", "tahoe city", "ukiah", "mendocino", "fort bragg", "point arena",
    "point reyes", "inverness", "marshall", "tomales", "cotati", "rohnert park", "windsor", "cloverdale",
    "boonville", "hopland", "philo", "yosemite", "mariposa", "sonora", "columbia", "murphys",
}
NORCAL_FAR = {"sacramento", "davis", "woodland", "winters", "nevada city", "grass valley", "auburn", "placerville",
              "truckee", "south lake tahoe", "tahoe city", "ukiah", "mendocino", "fort bragg", "point arena", "boonville",
              "hopland", "philo", "yosemite", "mariposa", "sonora", "columbia", "murphys", "monterey", "carmel",
              "pacific grove", "big sur", "hollister", "gilroy", "san juan bautista"}


def region_of(city: str | None, state: str | None = None) -> str:
    c = fold(city or "")
    c = re.sub(r"\bsf\b", "san francisco", c)
    if c in NORCAL_FAR:
        return "norcal"
    if c in BAY_AREA_CITIES:
        return "bay"
    if not c:
        return "unknown"
    if state and fold(state) not in ("ca", "california"):
        return "outside"
    return "unknown"


# ---------------------------------------------------------------- dates
def parse_dt(value, default_tz=TZ, assume_local=True):
    """Parse many date shapes into an aware datetime in local time. Returns None if unparseable."""
    if value is None or value == "":
        return None
    if isinstance(value, dt.datetime):
        d = value
    elif isinstance(value, dt.date):
        return dt.datetime(value.year, value.month, value.day, 0, 0, tzinfo=default_tz)
    elif isinstance(value, (int, float)):
        # epoch seconds or millis (Squarespace uses millis)
        v = float(value)
        if v > 1e11:
            v /= 1000.0
        return dt.datetime.fromtimestamp(v, tz=dt.timezone.utc).astimezone(default_tz)
    else:
        s = str(value).strip()
        s = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", s)
        try:
            d = dtparser.isoparse(s)
        except (ValueError, OverflowError):
            try:
                d = dtparser.parse(s, fuzzy=True)
            except (ValueError, OverflowError):
                return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=default_tz) if assume_local else d.replace(tzinfo=dt.timezone.utc)
    return d.astimezone(default_tz)


def local_date(d: dt.datetime | None) -> str | None:
    return d.astimezone(TZ).date().isoformat() if d else None


def iso(d: dt.datetime | None) -> str | None:
    return d.astimezone(TZ).replace(microsecond=0).isoformat() if d else None


# ---------------------------------------------------------------- dedup
def title_core(title: str, n: int = 3) -> str:
    """First few meaningful tokens of a title; splits on common separators so the headliner wins."""
    t = clean_text(title)
    t = re.split(r"\s+(?:w/|with|feat\.?|featuring|and|\+|/|\|)\s+|\s*&\s*|:\s|\s-\s|\s–\s|\s—\s", t, maxsplit=1)[0]
    toks = tokens(t)
    return " ".join(toks[:n])


def dedup_key(venue: str | None, date: str | None, title: str) -> str:
    return f"{date or 'nodate'}|{venue_key(venue) or 'novenue'}|{title_core(title) or slug(title, 20)}"


def event_id(key: str) -> str:
    return "ev_" + hashlib.sha1(key.encode()).hexdigest()[:12]


def similar_titles(a: str, b: str) -> float:
    """Jaccard overlap of meaningful tokens, used to merge same-night listings with different titles."""
    la, lb = tokens(a), tokens(b)
    ta, tb = set(la), set(lb)
    if not ta or not tb:
        return 0.0
    j = len(ta & tb) / len(ta | tb)
    if len(la) >= 2 and la[:2] == lb[:2]:
        j = max(j, 0.6)  # same headliner, different support billing
    return j
