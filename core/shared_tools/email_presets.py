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

def build_gmail_query(
    tracked_banks: Optional[List[str]] = None,
    custom_query: Optional[str] = None,
    exclude_domains: Optional[List[str]] = None,
) -> str:
    """
    Build the zero-friction smart query combining default financial keywords,
    global preset domains, and user-specific tracked banks.

    When exclude_domains is provided, append -from:domain clauses so the
    Gmail API excludes messages from those sender domains.
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
        query = f"({DEFAULT_GMAIL_FINANCIAL_QUERY}) OR ({domains_str} newer_than:7d)"
    else:
        query = DEFAULT_GMAIL_FINANCIAL_QUERY

    if exclude_domains:
        exclusion_clauses = " ".join(f"-from:{domain}" for domain in exclude_domains)
        query = f"({query}) {exclusion_clauses}"

    return query

DEFAULT_OUTLOOK_FINANCIAL_SEARCH = (
    '"receipt" OR "transaction" OR "charge" OR "payment" OR "order" OR "you paid" OR "amount due"'
)

def build_outlook_query(
    tracked_banks: Optional[List[str]] = None,
    custom_query: Optional[str] = None,
    exclude_domains: Optional[List[str]] = None,
) -> dict[str, str]:
    """
    Build OData query parameters ($search and $filter) for Microsoft Graph API.

    When exclude_domains is provided, append
    ``and not(from/emailAddress/address eq 'domain')`` clauses to $filter so
    the Graph API excludes messages from those sender domains.
    """
    if custom_query:
        filter_str = "not(categories/any(c:c eq 'Assistant/Processed'))"
        if exclude_domains:
            exclude_filter = " and ".join(
                f"not(from/emailAddress/address eq '{d}')" for d in exclude_domains
            )
            filter_str = f"{filter_str} and {exclude_filter}"
        return {
            "$search": f'"{custom_query}"',
            "$filter": filter_str,
        }

    all_domains = list(GLOBAL_BANK_PRESET_DOMAINS)
    if tracked_banks:
        for b in tracked_banks:
            if b not in all_domains:
                all_domains.append(b)

    # Graph message search does not accept Gmail's `from:domain` operator.
    # Keep domain terms searchable without emitting invalid OData search syntax.
    domain_search = " OR ".join(f'"{domain}"' for domain in all_domains)
    search_str = f"({DEFAULT_OUTLOOK_FINANCIAL_SEARCH}) OR ({domain_search})"
    filter_str = "not(categories/any(c:c eq 'Assistant/Processed'))"

    if exclude_domains:
        exclude_filter = " and ".join(
            f"not(from/emailAddress/address eq '{d}')" for d in exclude_domains
        )
        filter_str = f"{filter_str} and {exclude_filter}"

    return {
        "$search": search_str,
        "$filter": filter_str,
    }
