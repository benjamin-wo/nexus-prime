"""Which bank an email came from, by the domain it was sent from. Pure rules, no I/O.

This is only a label: it names a card the bank's alert mentions ("UOB card"), and it picks
between two cards that end in the same four digits. A sender address can be forged, so it is
never used to decide whether to trust an email, to log an expense or to change what is paid.
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


def sender_domain(sender: str) -> str:
    """The domain of a sender, lower case: from "alerts@uob.com.sg" or
    "UOB Alerts <alerts@uob.com.sg>". Empty when there is no address."""
    address = parseaddr(sender)[1] or sender
    _, at, domain = address.strip().rpartition("@")
    return domain.strip().strip(".").casefold() if at else ""


def issuer_from_sender(sender: str) -> str | None:
    """The bank whose domain (or a subdomain of it) the sender is, if it is one we know.
    "alerts.uob.com.sg" is UOB; "notuob.com.sg" and "uob.com.sg.example.com" are not."""
    domain = sender_domain(sender)
    while domain:
        if domain in _BY_DOMAIN:
            return _BY_DOMAIN[domain]
        _, dot, domain = domain.partition(".")
        if not dot:
            break
    return None
