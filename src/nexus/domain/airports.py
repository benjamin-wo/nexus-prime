"""Which airports a place means, for flight searches. Pure rules.

Google Flights (through SerpApi) takes airport codes, or a place's Freebase id (``/m/…``),
and not a city's name. The model usually knows the code ("BKK") and passes it; when it
passes a city's name instead ("Bangkok", "Tokyo") the common ones are found here, with every
airport that city's travellers would consider ("Tokyo" is Haneda and Narita). A place that
isn't here is left to the caller to ask the user about, rather than guessed.
"""

import re
import unicodedata

# SerpApi takes up to this many comma-separated airports on each side.
MAX_AIRPORTS = 4

_CODE = re.compile(r"^[A-Z]{3}$")
_KGMID = re.compile(r"^/[mg]/[0-9a-z_]{2,20}$")
_IN_BRACKETS = re.compile(r"\(([A-Za-z]{3})\)")

# City (lowercase, no accents) -> its airports, the busiest first.
CITIES: dict[str, tuple[str, ...]] = {
    "singapore": ("SIN",),
    "bangkok": ("BKK", "DMK"),
    "phuket": ("HKT",),
    "chiang mai": ("CNX",),
    "krabi": ("KBV",),
    "koh samui": ("USM",),
    "kuala lumpur": ("KUL",),
    "penang": ("PEN",),
    "langkawi": ("LGK",),
    "kota kinabalu": ("BKI",),
    "kuching": ("KCH",),
    "johor bahru": ("JHB",),
    "jakarta": ("CGK",),
    "bali": ("DPS",),
    "denpasar": ("DPS",),
    "surabaya": ("SUB",),
    "yogyakarta": ("YIA",),
    "medan": ("KNO",),
    "manila": ("MNL",),
    "cebu": ("CEB",),
    "clark": ("CRK",),
    "ho chi minh city": ("SGN",),
    "saigon": ("SGN",),
    "hanoi": ("HAN",),
    "da nang": ("DAD",),
    "nha trang": ("CXR",),
    "phnom penh": ("PNH",),
    "siem reap": ("REP",),
    "vientiane": ("VTE",),
    "luang prabang": ("LPQ",),
    "yangon": ("RGN",),
    "hong kong": ("HKG",),
    "macau": ("MFM",),
    "taipei": ("TPE", "TSA"),
    "kaohsiung": ("KHH",),
    "tokyo": ("HND", "NRT"),
    "osaka": ("KIX", "ITM"),
    "kyoto": ("KIX", "ITM"),
    "nagoya": ("NGO",),
    "fukuoka": ("FUK",),
    "sapporo": ("CTS",),
    "okinawa": ("OKA",),
    "naha": ("OKA",),
    "hiroshima": ("HIJ",),
    "seoul": ("ICN", "GMP"),
    "busan": ("PUS",),
    "jeju": ("CJU",),
    "beijing": ("PEK", "PKX"),
    "shanghai": ("PVG", "SHA"),
    "guangzhou": ("CAN",),
    "shenzhen": ("SZX",),
    "chengdu": ("CTU", "TFU"),
    "xi'an": ("XIY",),
    "xian": ("XIY",),
    "hangzhou": ("HGH",),
    "ulaanbaatar": ("UBN",),
    "delhi": ("DEL",),
    "new delhi": ("DEL",),
    "mumbai": ("BOM",),
    "bangalore": ("BLR",),
    "bengaluru": ("BLR",),
    "chennai": ("MAA",),
    "kolkata": ("CCU",),
    "hyderabad": ("HYD",),
    "kochi": ("COK",),
    "colombo": ("CMB",),
    "male": ("MLE",),
    "maldives": ("MLE",),
    "kathmandu": ("KTM",),
    "dhaka": ("DAC",),
    "karachi": ("KHI",),
    "dubai": ("DXB",),
    "abu dhabi": ("AUH",),
    "doha": ("DOH",),
    "istanbul": ("IST", "SAW"),
    "cairo": ("CAI",),
    "johannesburg": ("JNB",),
    "cape town": ("CPT",),
    "nairobi": ("NBO",),
    "sydney": ("SYD",),
    "melbourne": ("MEL",),
    "brisbane": ("BNE",),
    "perth": ("PER",),
    "adelaide": ("ADL",),
    "cairns": ("CNS",),
    "gold coast": ("OOL",),
    "darwin": ("DRW",),
    "canberra": ("CBR",),
    "auckland": ("AKL",),
    "christchurch": ("CHC",),
    "queenstown": ("ZQN",),
    "wellington": ("WLG",),
    "fiji": ("NAN",),
    "london": ("LHR", "LGW", "STN", "LTN"),
    "paris": ("CDG", "ORY"),
    "amsterdam": ("AMS",),
    "frankfurt": ("FRA",),
    "munich": ("MUC",),
    "berlin": ("BER",),
    "zurich": ("ZRH",),
    "geneva": ("GVA",),
    "vienna": ("VIE",),
    "prague": ("PRG",),
    "budapest": ("BUD",),
    "warsaw": ("WAW",),
    "rome": ("FCO", "CIA"),
    "milan": ("MXP", "LIN", "BGY"),
    "venice": ("VCE",),
    "florence": ("FLR",),
    "madrid": ("MAD",),
    "barcelona": ("BCN",),
    "lisbon": ("LIS",),
    "porto": ("OPO",),
    "athens": ("ATH",),
    "dublin": ("DUB",),
    "edinburgh": ("EDI",),
    "manchester": ("MAN",),
    "brussels": ("BRU",),
    "copenhagen": ("CPH",),
    "stockholm": ("ARN",),
    "oslo": ("OSL",),
    "helsinki": ("HEL",),
    "reykjavik": ("KEF",),
    "moscow": ("SVO", "DME", "VKO"),
    "new york": ("JFK", "EWR", "LGA"),
    "new york city": ("JFK", "EWR", "LGA"),
    "boston": ("BOS",),
    "washington": ("IAD", "DCA"),
    "chicago": ("ORD", "MDW"),
    "los angeles": ("LAX",),
    "san francisco": ("SFO",),
    "seattle": ("SEA",),
    "las vegas": ("LAS",),
    "miami": ("MIA",),
    "orlando": ("MCO",),
    "atlanta": ("ATL",),
    "dallas": ("DFW",),
    "houston": ("IAH",),
    "denver": ("DEN",),
    "honolulu": ("HNL",),
    "toronto": ("YYZ",),
    "vancouver": ("YVR",),
    "montreal": ("YUL",),
    "mexico city": ("MEX",),
    "cancun": ("CUN",),
    "sao paulo": ("GRU", "CGH"),
    "rio de janeiro": ("GIG", "SDU"),
    "rio": ("GIG", "SDU"),
    "buenos aires": ("EZE", "AEP"),
    "santiago": ("SCL",),
    "lima": ("LIM",),
    "bogota": ("BOG",),
}


def _plain(text: str) -> str:
    """Lowercase, no accents, one space between words."""
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return " ".join(folded.casefold().replace(",", " ").split())


def resolve(place: str) -> str | None:
    """What to send as a flight's departure or arrival: airport codes joined by commas
    ("HND,NRT"), or a place id (``/m/…``). Takes a code ("bkk"), several ("NRT, HND"), a code
    in brackets ("Tokyo (NRT)"), a place id, or the name of a city in ``CITIES``. None if
    the place isn't recognised: the caller asks the user which airport they mean."""
    raw = place.strip()
    if not raw:
        return None
    if _KGMID.match(raw.lower()):
        return str(raw.lower())
    # "Bangkok", or "Bangkok, Thailand": the city is what comes before the first comma.
    cities = CITIES.get(_plain(raw)) or CITIES.get(_plain(raw.split(",")[0]))
    if cities is not None:
        return ",".join(cities)
    bracketed = _IN_BRACKETS.findall(raw)
    if len(bracketed) == 1:
        return str(bracketed[0]).upper()
    parts = [p for p in re.split(r"[\s,/]+", raw) if p]
    codes = [p.upper() for p in parts]
    if 1 <= len(codes) <= MAX_AIRPORTS and all(_CODE.match(c) for c in codes):
        return ",".join(dict.fromkeys(codes))
    return None
