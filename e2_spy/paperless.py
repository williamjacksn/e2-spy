import json
import logging
import pathlib
import time

import httpx

log = logging.getLogger(__name__)


def get_client(api_key: str) -> httpx.Client:
    auth_header = {"Authorization": f"API-Token {api_key}"}
    return httpx.Client(headers=auth_header)


def get_quotes(c: httpx.Client, use_cache: bool = True) -> list:
    p = pathlib.Path(".local/quotes.json")
    if not use_cache or not p.exists():
        response = c.get("https://api.paperlessparts.com/quotes/public/new")
        p.write_bytes(response.content)
    with p.open() as f:
        return json.load(f)


def get_quote_details(
    c: httpx.Client, quote_number: int, revision: int | None, use_cache: bool = True
) -> dict:
    if revision is None:
        path_rev = 0
        params = {}
    else:
        path_rev = revision
        params = {"revision": revision}
    p = pathlib.Path(f".local/quote-{quote_number}-{path_rev}.json")
    if not use_cache or not p.exists():
        log.info(f"Fetching info from API for quote {quote_number} revision {revision}")
        while True:
            response = c.get(
                f"https://api.paperlessparts.com/quotes/public/{quote_number}",
                params=params,
            )
            if "error" in response.json():
                log.error(response.text)
                log.error("Sleeping for 5 seconds")
                time.sleep(5)
            else:
                break
        p.write_bytes(response.content)
    with p.open(encoding="utf-8") as f:
        return json.load(f)
