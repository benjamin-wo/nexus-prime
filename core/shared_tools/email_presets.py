from typing import List, Optional

DEFAULT_GMAIL_FINANCIAL_QUERY = (
    '("receipt" OR "transaction" OR "charge" OR "payment" OR "order" OR "you paid" OR "amount due" OR "invoice" OR "alert" OR "transfer") '
    'newer_than:7d'
)

GLOBAL_BANK_PRESET_DOMAINS = [
    "chase.com",
    "americanexpress.com",
    "citi.com",
    "bankofamerica.com",
    "capitalone.com",
    "paypal.com",
    "stripe.com",
    "square.com",
    "dbs.com",
    "dbs.com.sg",
    "ocbc.com",
    "uob.com.sg",
    "grab.com",
    "apple.com",
]

def build_gmail_query(tracked_banks: Optional[List[str]] = None, custom_query: Optional[str] = None) -> str:
    """
    Build the zero-friction smart query combining default financial keywords,
    global preset domains, and user-specific tracked banks.
    """
    if custom_query:
        return custom_query

    all_domains = list(GLOBAL_BANK_PRESET_DOMAINS)
    if tracked_banks:
        for b in tracked_banks:
            if b not in all_domains:
                all_domains.append(b)

    if all_domains:
        domains_str = " OR ".join(f"from:{domain}" for domain in all_domains)
        return f"({DEFAULT_GMAIL_FINANCIAL_QUERY}) OR ({domains_str} newer_than:7d)"

    return DEFAULT_GMAIL_FINANCIAL_QUERY

DEFAULT_OUTLOOK_FINANCIAL_SEARCH = (
    '"receipt" OR "transaction" OR "charge" OR "payment" OR "order" OR "you paid" OR "amount due"'
)

def build_outlook_query(tracked_banks: Optional[List[str]] = None, custom_query: Optional[str] = None) -> dict[str, str]:
    """
    Build OData query parameters ($search and $filter) for Microsoft Graph API.
    """
    if custom_query:
        return {
            "$search": f'"{custom_query}"',
            "$filter": "not(categories/any(c:c eq 'Assistant/Processed'))",
        }

    all_domains = list(GLOBAL_BANK_PRESET_DOMAINS)
    if tracked_banks:
        for b in tracked_banks:
            if b not in all_domains:
                all_domains.append(b)

    domain_search = " OR ".join(f"from:{domain}" for domain in all_domains)
    search_str = f"({DEFAULT_OUTLOOK_FINANCIAL_SEARCH}) OR ({domain_search})"
    filter_str = "not(categories/any(c:c eq 'Assistant/Processed'))"

    return {
        "$search": search_str,
        "$filter": filter_str,
    }
