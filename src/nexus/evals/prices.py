"""Live prices in the evals: canned, so the flight_prices, product_prices and flight_status
tools work offline, for free and the same every time (there is no live version: the real
searches come from a small monthly allowance, and the evals must never spend it).

Made-up figures for made-up offers, on a domain reserved for examples. Nothing is counted,
and every lookup is remembered so a case can see what was asked."""

from datetime import date, datetime, timedelta
from decimal import Decimal

from nexus.domain.ledger import UserId
from nexus.domain.live_prices import (
    CalendarQuery,
    FareCalendar,
    FareDay,
    FlightFares,
    FlightOption,
    FlightQuery,
    FlightStatus,
    PriceInsight,
    ProductOffer,
    ProductPrices,
    ProductQuery,
    StatusLeg,
    StatusQuery,
)
from nexus.evals import seed

DOMAIN = "example.com"
FARES_URL = f"https://flights.{DOMAIN}/nexus-evals/search"
SHOP_URL = f"https://shop.{DOMAIN}/nexus-evals"
STATUS_URL = f"https://tracker.{DOMAIN}/nexus-evals/flight"


class CannedPrices:
    """Answers every lookup the same way and remembers what was asked."""

    def __init__(self, now: datetime = seed.NOW) -> None:
        self._now = now
        self.asked: list[object] = []

    async def flights(self, user: UserId, q: FlightQuery, today: date) -> FlightFares:
        self.asked.append(q)
        night = datetime.combine(q.outbound, datetime.min.time())
        options = [
            FlightOption(
                "Scoot",
                0,
                [],
                150,
                Decimal(180) * q.adults,
                f"{night:%Y-%m-%d} 07:30",
                f"{night:%Y-%m-%d} 09:00",
                ["TR 868"],
            ),
            FlightOption(
                "Singapore Airlines",
                0,
                [],
                145,
                Decimal(260) * q.adults,
                f"{night:%Y-%m-%d} 10:15",
                f"{night:%Y-%m-%d} 11:40",
                ["SQ 976"],
            ),
            FlightOption(
                "AirAsia",
                1,
                ["KUL"],
                330,
                Decimal(150) * q.adults,
                f"{night:%Y-%m-%d} 06:10",
                f"{night:%Y-%m-%d} 11:40",
                ["AK 704", "AK 877"],
            ),
        ]
        insight = PriceInsight("typical", Decimal(150) * q.adults, Decimal(140), Decimal(300))
        return FlightFares(q, sorted(options, key=lambda o: o.price), insight, FARES_URL, self._now)

    async def calendar(self, user: UserId, q: CalendarQuery, today: date) -> FareCalendar:
        self.asked.append(q)
        days: list[FareDay] = []
        day = q.start
        while day <= q.end:
            price = Decimal(160 + (day.toordinal() * 37) % 140) * q.adults
            back = day + timedelta(days=q.trip_days) if q.trip_days else None
            days.append(FareDay(day, back, price, False))
            day += timedelta(days=1)
        low = min((d.price for d in days), default=Decimal(0))
        days = [
            FareDay(d.outbound, d.back, d.price, d.price <= low * Decimal("1.05")) for d in days
        ]
        return FareCalendar(q, days, self._now)

    async def products(self, user: UserId, q: ProductQuery, today: date) -> ProductPrices:
        self.asked.append(q)
        name = q.query.title()
        offers = [
            ProductOffer(
                f"{name}",
                Decimal("499.00"),
                "S$499.00",
                "SGD",
                "Example Mart",
                4.7,
                f"{SHOP_URL}/mart",
            ),
            ProductOffer(
                f"{name} (bundle)",
                Decimal("519.00"),
                "S$519.00",
                "SGD",
                "Sample Store",
                4.5,
                f"https://store.{DOMAIN}/nexus-evals/bundle",
            ),
            ProductOffer(
                f"{name}",
                Decimal("529.90"),
                "S$529.90",
                "SGD",
                "Demo Electronics",
                None,
                f"https://electronics.{DOMAIN}/nexus-evals/item",
            ),
        ]
        return ProductPrices(q, offers, f"https://shopping.{DOMAIN}/nexus-evals", self._now)

    async def status(self, user: UserId, q: StatusQuery, today: date) -> FlightStatus:
        self.asked.append(q)
        day = q.day or today
        leg_out = StatusLeg(
            "SIN", "Singapore", f"{day} 08:25", f"{day} 08:40", "3", "B12", "Departed"
        )
        leg_in = StatusLeg("BKK", "Bangkok", f"{day} 09:55", f"{day} 10:05", "1", None, None)
        return FlightStatus(
            q,
            True,
            day,
            "Delayed",
            "Example Air",
            "Singapore to Bangkok",
            leg_out,
            leg_in,
            15,
            10,
            f"{day} 08:45",
            "Example Tracker",
            STATUS_URL,
            [str(day)],
            self._now,
        )
