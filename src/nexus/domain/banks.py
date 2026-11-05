"""Which bank an email came from, by the domain it was sent from. Pure rules, no I/O.

This is only a label: it names a card the bank's alert mentions ("UOB card"), and it picks
between two cards that end in the same four digits. A sender address can be forged, so it is
never used to decide whether to trust an email, to log an expense or to change what is paid.
The one rule that leans on the sender is narrowing: only a bank or a payment service may be
read as money received (``can_pay_you``); a forged sender can at most make Nexus ask "Log it
as money in?", which the user still answers.
"""

from email.utils import parseaddr

# Bank name -> the domains it sends from. A subdomain of one of these counts too.
_BANKS: dict[str, tuple[str, ...]] = {
    "UOB": ("uobgroup.com", "uob.com.sg"),
    "DBS": ("dbs.com", "dbs.com.sg"),
    "POSB": ("posb.com.sg",),
    "Citi": ("citibank.com.sg", "citi.com"),
    "OCBC": ("ocbc.com",),
    "HSBC": ("hsbc.com.sg", "hsbc.com"),
    "Standard Chartered": ("sc.com",),
    "American Express": ("americanexpress.com", "aexp.com"),
    "Maybank": ("maybank.com.sg", "maybank2u.com"),
    "Trust": ("trustbank.sg",),
}
_BY_DOMAIN = {domain: bank for bank, domains in _BANKS.items() for domain in domains}

# Payment and transfer services that can send the user money (a PayPal payment, a Wise
# transfer, a Stripe payout). A subdomain of one of these counts too.
_PAYMENT_SERVICES: dict[str, tuple[str, ...]] = {
    "PayPal": ("paypal.com",),
    "Wise": ("wise.com", "transferwise.com"),
    "Revolut": ("revolut.com",),
    "YouTrip": ("you.co", "youtrip.com"),
    "GrabPay": ("grab.com",),
    "Amaze": ("amaze.co",),
    "Instarem": ("instarem.com",),
    "Stripe": ("stripe.com",),
}
_SERVICE_BY_DOMAIN = {d: name for name, domains in _PAYMENT_SERVICES.items() for d in domains}


def sender_domain(sender: str) -> str:
    """The domain of a sender, lower case: from "alerts@uob.com.sg" or
    "UOB Alerts <alerts@uob.com.sg>". Empty when there is no address."""
    address = parseaddr(sender)[1] or sender
    _, at, domain = address.strip().rpartition("@")
    return domain.strip().strip(".").casefold() if at else ""


def _known(sender: str, names: dict[str, str]) -> str | None:
    """The name ``names`` gives the sender's domain, or its nearest parent domain's."""
    domain = sender_domain(sender)
    while domain:
        if domain in names:
            return names[domain]
        _, dot, domain = domain.partition(".")
        if not dot:
            break
    return None


def issuer_from_sender(sender: str) -> str | None:
    """The bank whose domain (or a subdomain of it) the sender is, if it is one we know.
    "alerts.uob.com.sg" is UOB; "notuob.com.sg" and "uob.com.sg.example.com" are not."""
    return _known(sender, _BY_DOMAIN)


def can_pay_you(sender: str) -> bool:
    """Whether the sender is a bank or a payment service, the only senders whose email
    can say money came in. A shop's "payment confirmation" means the reader paid it."""
    return issuer_from_sender(sender) is not None or _known(sender, _SERVICE_BY_DOMAIN) is not None
