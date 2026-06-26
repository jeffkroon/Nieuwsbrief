"""
Haalt recente LinkedIn-posts op via de Apify API (supreme_coder/linkedin-post)
en print ze als JSON naar stdout.

Gebruik:
    python tools/fetch_linkedin_posts.py --url "https://www.linkedin.com/company/dunion-online-marketing/" --posts 4

Vereisten:
    pip install requests python-dotenv

Omgevingsvariabelen (.env in de Email Marketing-map):
    APIFY_API_KEY=...
"""

import argparse
import json
import os
import sys
import time

import requests
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

APIFY_API_KEY = os.getenv("APIFY_API_KEY")
ACTOR_ID = "supreme_coder~linkedin-post"
BASE_URL = "https://api.apify.com/v2"


def start_run(linkedin_url: str) -> str:
    url = f"{BASE_URL}/acts/{ACTOR_ID}/runs"
    payload = {"urls": [linkedin_url]}
    resp = requests.post(
        url,
        params={"token": APIFY_API_KEY},
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["data"]["id"]


def wait_for_run(run_id: str, timeout: int = 300) -> None:
    url = f"{BASE_URL}/actor-runs/{run_id}"
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = requests.get(url, params={"token": APIFY_API_KEY}, timeout=15)
        resp.raise_for_status()
        status = resp.json()["data"]["status"]
        if status == "SUCCEEDED":
            return
        if status in ("FAILED", "ABORTED", "TIMED-OUT"):
            raise RuntimeError(f"Apify run mislukt met status: {status}")
        time.sleep(5)
    raise TimeoutError("Apify run timed out na 300 seconden.")


def check_accounts_unavailable(run_id: str) -> bool:
    """Controleer of de run mislukte vanwege gebrek aan LinkedIn-accounts."""
    try:
        log = requests.get(
            f"{BASE_URL}/actor-runs/{run_id}/log",
            params={"token": APIFY_API_KEY},
            timeout=15,
        )
        return "no available accounts found" in log.text
    except Exception:
        return False


def fetch_dataset(run_id: str, max_results: int) -> list[dict]:
    url = f"{BASE_URL}/actor-runs/{run_id}/dataset/items"
    resp = requests.get(
        url,
        params={"token": APIFY_API_KEY, "limit": max_results},
        timeout=30,
    )
    resp.raise_for_status()
    items = resp.json()

    posts = []
    for item in items[:max_results]:
        if "error" in item:
            continue

        text = item.get("text") or ""

        # Afbeelding: eerst document cover, dan images-array
        image_url = ""
        doc = item.get("document") or {}
        covers = doc.get("coverPages") or []
        if covers:
            image_url = covers[0]
        else:
            raw = item.get("images") or item.get("image") or ""
            if isinstance(raw, list) and raw:
                image_url = raw[0] if isinstance(raw[0], str) else ""
            elif isinstance(raw, str):
                image_url = raw

        post_url = item.get("url") or item.get("postUrl") or item.get("shareUrl") or ""

        posts.append({
            "text": text.strip(),
            "imageUrl": image_url,
            "postUrl": post_url,
        })
    return posts


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Haal LinkedIn-posts op via Apify.")
    parser.add_argument("--url", required=True, help="LinkedIn bedrijfspagina-URL")
    parser.add_argument("--posts", type=int, default=4, help="Aantal posts (standaard: 4)")
    args = parser.parse_args()

    if not APIFY_API_KEY:
        print("FOUT: APIFY_API_KEY niet gevonden in .env", file=sys.stderr)
        sys.exit(1)

    max_pogingen = 3
    posts = []
    for poging in range(1, max_pogingen + 1):
        print(f"Apify-run starten (poging {poging}/{max_pogingen})...", file=sys.stderr)
        run_id = start_run(args.url)
        print(f"Wachten op voltooiing (run ID: {run_id})...", file=sys.stderr)
        wait_for_run(run_id)
        posts = fetch_dataset(run_id, args.posts)
        print(f"{len(posts)} posts opgehaald.", file=sys.stderr)

        if posts:
            break

        if check_accounts_unavailable(run_id):
            print(
                "FOUT: De Apify-actor heeft momenteel geen LinkedIn-accounts beschikbaar. "
                "Dit is een tijdelijk probleem aan de kant van de actor. "
                "Probeer het over een uur opnieuw.",
                file=sys.stderr,
            )
            sys.exit(1)

        if poging < max_pogingen:
            print("Geen posts gevonden, opnieuw proberen over 30 seconden...", file=sys.stderr)
            time.sleep(30)

    if not posts:
        print(
            "FOUT: na 3 pogingen zijn er nog steeds 0 posts gevonden. "
            "Controleer of de LinkedIn-URL correct is en probeer het later opnieuw.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(json.dumps(posts, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
