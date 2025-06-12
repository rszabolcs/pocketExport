#!/usr/bin/env python3
"""
Pocket API Article Export by Slug

This script exports all Pocket articles by their slugs, using the GraphQL API.
It fetches article content and metadata and saves them in a structured directory format.

"""
import os
import sys
import json
import time
import argparse
import logging
from pathlib import Path
from typing import Dict, Set, Optional, Any, Iterator, Union, Tuple

import requests
from tqdm import tqdm
from dotenv import load_dotenv

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('export_by_slug.log')
    ]
)
logger = logging.getLogger("pocket_export")

GRAPHQL_QUERY = """
query GetSavedItemBySlug($id: ID!) {
  readerSlug(slug: $id) {
    fallbackPage {
      ... on ReaderInterstitial {
        itemCard {
          ... on PocketMetadata {
            item {
              ...ItemDetails
            }
          }
        }
      }
    }
    savedItem {
      ...SavedItemDetails
      annotations {
        highlights {
          id
          quote
          patch
          version
          _createdAt
          _updatedAt
          note {
            text
            _createdAt
            _updatedAt
          }
        }
      }
      item {
        ...ItemDetails
        ... on Item {
          article
          relatedAfterArticle(count: 3) {
            corpusRecommendationId: id
            corpusItem {
              thumbnail: imageUrl
              publisher
              title
              externalUrl: url
              saveUrl: url
              id
              excerpt
            }
          }
        }
      }
    }
    slug
  }
}

fragment SavedItemDetails on SavedItem {
  _createdAt
  _updatedAt
  title
  url
  savedId: id
  status
  isFavorite
  favoritedAt
  isArchived
  archivedAt
  tags {
    id
    name
  }
  annotations {
    highlights {
      id
      quote
      patch
      version
      _createdAt
      _updatedAt
      note {
        text
        _createdAt
        _updatedAt
      }
    }
  }
}

fragment ItemDetails on Item {
  isArticle
  title
  shareId: id
  itemId
  readerSlug
  resolvedId
  resolvedUrl
  domain
  domainMetadata {
    name
  }
  excerpt
  hasImage
  hasVideo
  images {
    caption
    credit
    height
    imageId
    src
    width
  }
  videos {
    vid
    videoId
    type
    src
  }
  topImageUrl
  timeToRead
  givenUrl
  collection {
    imageUrl
    intro
    title
    excerpt
  }
  authors {
    id
    name
    url
  }
  datePublished
  syndicatedArticle {
    slug
    publisher {
      name
      url
    }
  }
}
"""

class PocketExporter:

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.session = self._setup_session()
        self.graphql_url = f"https://getpocket.com/graphql?consumer_key={config['consumer_key']}&enable_cors=1"
        self.done_slugs: Set[str] = set()
        self.failed_slugs: Dict[str, str] = {}
        self.stats = {
            "total": 0,
            "skipped": 0,
            "success": 0,
            "failed": 0,
            "binary": 0
        }

    def _setup_session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update({
            "Content-Type": "application/json",
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Accept-Language": "en-US,en;q=0.8",
            "X-Accept": "application/json; charset=UTF8",
            "Origin": "https://getpocket.com",
            "Referer": "https://getpocket.com/",
            "Connection": "keep-alive",
            "apollographql-client-name": "web-client",
            "apollographql-client-version": "1.162.3",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:140.0) Gecko/20100101 Firefox/140.0",
        })

        # Add cookies if they exist
        cookies = []
        if self.config.get("pocket_cookie"):
            cookies.append(self.config["pocket_cookie"])
        if self.config.get("sp_lit"):
            cookies.append(f"sp_lit={self.config['sp_lit']}")
        if self.config.get("sp_ltk"):
            cookies.append(f"sp_ltk={self.config['sp_ltk']}")
        if self.config.get("auth_bearer"):
            cookies.append(f"AUTH_BEARER_default={self.config['auth_bearer']}")

        if cookies:
            session.headers["Cookie"] = "; ".join(filter(None, cookies))

        return session

    def post_with_backoff(self, url: str, payload: Dict[str, Any]) -> requests.Response:
        attempt = 0
        while True:
            try:
                if attempt > 0:
                    delay = min(self.config["base_delay"] * (2 ** attempt), self.config["max_delay"])
                    time.sleep(delay)

                resp = self.session.post(url, json=payload, timeout=self.config["timeout"])

                if resp.status_code == 429 or (500 <= resp.status_code < 600):
                    delay = min(self.config["base_delay"] * (2 ** attempt), self.config["max_delay"])
                    logger.warning(f"Received {resp.status_code}, retrying in {delay:.1f}s (attempt {attempt+1}/{self.config['max_retries']})")
                    attempt += 1
                    if attempt >= self.config["max_retries"]:
                        logger.error(f"Exceeded max retries ({self.config['max_retries']}) for {resp.status_code}")
                        resp.raise_for_status()
                    continue

                time.sleep(self.config["request_delay"])
                resp.raise_for_status()
                return resp
            except requests.RequestException as e:
                if hasattr(e, 'response') and e.response is not None:
                    status = e.response.status_code
                    if status == 429 or (500 <= status < 600):
                        delay = min(self.config["base_delay"] * (2 ** attempt), self.config["max_delay"])
                        logger.warning(f"Exception {status}, retrying in {delay:.1f}s (attempt {attempt+1}/{self.config['max_retries']})")
                        attempt += 1
                        if attempt >= self.config["max_retries"]:
                            logger.error(f"Exceeded max retries ({self.config['max_retries']}) for {status}")
                            raise
                        continue
                logger.error(f"Request failed: {e}")
                raise

    def load_progress(self) -> None:
        if os.path.exists(self.config["progress_file"]):
            try:
                with open(self.config["progress_file"], "r", encoding="utf-8") as f:
                    self.done_slugs = set(json.load(f))
                logger.info(f"Loaded progress: {len(self.done_slugs)} items already processed")
            except json.JSONDecodeError:
                logger.warning("Error parsing progress file. Starting from beginning.")
                self.done_slugs = set()

        failed_file = self.config["progress_file"].replace(".json", "_failed.json")
        if os.path.exists(failed_file):
            try:
                with open(failed_file, "r", encoding="utf-8") as f:
                    self.failed_slugs = json.load(f)
                logger.info(f"Loaded {len(self.failed_slugs)} previously failed items")
            except json.JSONDecodeError:
                logger.warning("Error parsing failed items file.")
                self.failed_slugs = {}

    def save_progress(self) -> None:
        try:
            with open(self.config["progress_file"], "w", encoding="utf-8") as f:
                json.dump(sorted(list(self.done_slugs)), f)

            if self.failed_slugs:
                failed_file = self.config["progress_file"].replace(".json", "_failed.json")
                with open(failed_file, "w", encoding="utf-8") as f:
                    json.dump(self.failed_slugs, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to save progress: {e}")

    def extract_slug(self, entry: Dict[str, Any]) -> Optional[str]:
        # Use shareId within item as slugId
        item = entry.get("item")
        if item and "shareId" in item:
            return item["shareId"]
        # Try other identifiers
        return entry.get("readerSlug") or entry.get("slug") or entry.get("itemId")

    def iter_slug_entries(self) -> Iterator[Dict[str, Any]]:
        for fname in sorted(os.listdir(self.config["slug_dir"])):
            if fname.startswith("slugs_") and fname.endswith(".json"):
                file_path = os.path.join(self.config["slug_dir"], fname)
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        entries = json.load(f)
                        for entry in entries:
                            yield entry
                except Exception as e:
                    logger.error(f"Error processing {fname}: {e}")

    def structured_file_path(self, slug: str, base_dir: str) -> Path:
        slug_str = str(slug)
        # Use first 3 characters as subdirectories for better distribution
        subdirs = [slug_str[i] if i < len(slug_str) else "_" for i in range(3)]
        dir_path = Path(base_dir, *subdirs)
        return dir_path / slug_str

    def save_file(self, slug: str, content: Union[Dict, bytes], is_json: bool = True) -> Path:
        base_dir = self.config["output_dir"] if is_json else self.config["bin_output_dir"]
        file_path = self.structured_file_path(slug, base_dir)

        file_path.parent.mkdir(parents=True, exist_ok=True)

        if is_json:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(content, f, ensure_ascii=False, indent=2 if self.config["pretty_json"] else None)
        else:
            with open(file_path, "wb") as f:
                f.write(content)

        return file_path

    def fetch_article(self, slug: str) -> Tuple[bool, str]:
        payload = {
            "operationName": "GetReaderItem",
            "variables": {"id": slug},
            "query": GRAPHQL_QUERY
        }

        try:
            resp = self.post_with_backoff(self.graphql_url, payload)

            try:
                data = resp.json()
                if "errors" in data:
                    error_msg = "; ".join([e.get("message", "Unknown GraphQL error") for e in data["errors"]])
                    logger.warning(f"GraphQL error for slug {slug}: {error_msg}")
                    self.failed_slugs[slug] = error_msg
                    self.stats["failed"] += 1
                    return False, f"GraphQL error: {error_msg}"

                canonical_slug = None
                try:
                    canonical_slug = data["data"]["readerSlug"]["slug"]
                except Exception:
                    pass

                final_slug = canonical_slug if canonical_slug else slug
                self.save_file(final_slug, data, is_json=True)
                self.done_slugs.add(final_slug)
                self.stats["success"] += 1
                return True, f"Saved JSON: {final_slug}"

            except json.JSONDecodeError:
                # Not JSON, save as binary
                self.save_file(slug, resp.content, is_json=False)
                self.done_slugs.add(slug)
                self.stats["binary"] += 1
                return True, f"Saved binary response: {slug}"

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Failed for slug {slug}: {error_msg}")
            self.failed_slugs[slug] = error_msg
            self.stats["failed"] += 1
            return False, f"Request error: {error_msg}"

    def export_all(self) -> None:
        Path(self.config["output_dir"]).mkdir(parents=True, exist_ok=True)
        Path(self.config["bin_output_dir"]).mkdir(parents=True, exist_ok=True)

        self.load_progress()

        entries = list(self.iter_slug_entries())
        self.stats["total"] = len(entries)

        logger.info(f"Found {len(entries)} entries. {len(self.done_slugs)} already processed.")

        with tqdm(total=len(entries), desc="Exporting articles") as pbar:
            for idx, entry in enumerate(entries, 1):
                if entry.get("status") == "DELETED":
                    self.stats["skipped"] += 1
                    pbar.update(1)
                    continue

                slug = self.extract_slug(entry)
                if not slug:
                    logger.warning(f"Entry missing slug: {entry}")
                    self.stats["skipped"] += 1
                    pbar.update(1)
                    continue

                json_path = self.structured_file_path(slug, self.config["output_dir"])
                bin_path = self.structured_file_path(slug, self.config["bin_output_dir"])

                if slug in self.done_slugs or json_path.exists() or bin_path.exists():
                    self.stats["skipped"] += 1
                    pbar.update(1)
                    continue

                success, message = self.fetch_article(slug)
                pbar.set_postfix_str(f"Current: {slug[:8]}...")
                pbar.update(1)

                if idx % self.config["save_interval"] == 0:
                    self.save_progress()

                if self.config["request_delay"] > 0:
                    time.sleep(self.config["request_delay"])

        self.save_progress()

        logger.info(f"Export completed:")
        logger.info(f"  Total entries: {self.stats['total']}")
        logger.info(f"  Skipped: {self.stats['skipped']}")
        logger.info(f"  Successful JSON exports: {self.stats['success']}")
        logger.info(f"  Binary responses: {self.stats['binary']}")
        logger.info(f"  Failed: {self.stats['failed']}")

def parse_arguments():
    parser = argparse.ArgumentParser(description="Export Pocket articles by slug")

    parser.add_argument("--slug-dir", default="slug",
                       help="Directory containing slug JSON files (default: slug)")
    parser.add_argument("--output-dir", default="articles",
                       help="Directory for exported JSON files (default: articles)")
    parser.add_argument("--bin-output-dir", default="articles_bin",
                       help="Directory for binary responses (default: articles_bin)")
    parser.add_argument("--progress-file", default="progress_slug.json",
                       help="File to track progress (default: progress_slug.json)")
    parser.add_argument("--retry-count", type=int, default=5,
                       help="Max retries for API requests (default: 5)")
    parser.add_argument("--base-delay", type=float, default=1.0,
                       help="Base delay for retry backoff in seconds (default: 1.0)")
    parser.add_argument("--max-delay", type=int, default=60,
                       help="Maximum delay for retry backoff in seconds (default: 60)")
    parser.add_argument("--request-delay", type=float, default=0.5,
                       help="Delay between requests in seconds (default: 0.5)")
    parser.add_argument("--timeout", type=int, default=30,
                       help="Request timeout in seconds (default: 30)")
    parser.add_argument("--save-interval", type=int, default=10,
                       help="Save progress every N items (default: 10)")
    parser.add_argument("--pretty-json", action="store_true",
                       help="Save JSON with indentation (slower but more readable)")

    return parser.parse_args()

def main():
    args = parse_arguments()

    load_dotenv()

    consumer_key = os.getenv("CONSUMER_KEY")
    if not consumer_key:
        logger.error("CONSUMER_KEY environment variable is not set")
        sys.exit(1)

    config = {
        "consumer_key": consumer_key,
        "pocket_cookie": os.getenv("POCKET_COOKIE"),
        "sp_lit": os.getenv("SP_LIT"),
        "sp_ltk": os.getenv("SP_LTK"),
        "auth_bearer": os.getenv("AUTH_BEARER"),
        "slug_dir": args.slug_dir,
        "output_dir": args.output_dir,
        "bin_output_dir": args.bin_output_dir,
        "progress_file": args.progress_file,
        "max_retries": args.retry_count,
        "base_delay": args.base_delay,
        "max_delay": args.max_delay,
        "request_delay": args.request_delay,
        "timeout": args.timeout,
        "save_interval": args.save_interval,
        "pretty_json": args.pretty_json
    }

    exporter = PocketExporter(config)
    try:
        exporter.export_all()
    except KeyboardInterrupt:
        logger.info("Export interrupted by user. Saving progress...")
        exporter.save_progress()
        sys.exit(1)

if __name__ == "__main__":
    main()
