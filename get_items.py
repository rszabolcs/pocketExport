#!/usr/bin/env python3
"""
Pocket API Article Retrieval Script

This script fetches all saved articles from a Pocket account using the Pocket API
and saves them to JSON files in chunks for further processing.
"""
import os
import sys
import json
import time
import argparse
import requests
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

API_URL = "https://getpocket.com/v3/get"
API_HEADERS = {"Content-Type": "application/json; charset=UTF-8", "X-Accept": "application/json"}

def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Fetch and save articles from Pocket API")
    parser.add_argument("--output-dir", default="pocket_data", help="Directory to save JSON files (default: pocket_data)")
    parser.add_argument("--batch-size", type=int, default=100, help="Number of items to fetch per API call (default: 100)")
    parser.add_argument("--chunk-size", type=int, default=1000, help="Number of items per output file (default: 1000)")
    parser.add_argument("--state", default="all", choices=["unread", "archive", "all"], help="Filter by read state (default: all)")
    parser.add_argument("--retry-count", type=int, default=3, help="Number of retries for failed API calls (default: 3)")
    parser.add_argument("--retry-delay", type=int, default=5, help="Seconds to wait between retries (default: 5)")
    return parser.parse_args()

def load_credentials():
    load_dotenv()
    consumer_key = os.getenv("CONSUMER_KEY")
    access_token = os.getenv("ACCESS_TOKEN")

    if not consumer_key or not access_token:
        print("❌ Error: CONSUMER_KEY or ACCESS_TOKEN missing from the .env file")
        print("Please run get_access_token.py first to obtain your access token.")
        sys.exit(1)

    return consumer_key, access_token

def load_progress(output_dir):
    progress_path = output_dir / "progress.json"

    if progress_path.exists():
        try:
            with open(progress_path, "r") as f:
                state = json.load(f)
            offset = state.get("offset", 0)
            file_index = state.get("file_index", 1)
            print(f"🔄 Resuming from offset {offset}, file index {file_index}")
            return offset, file_index
        except json.JSONDecodeError as e:
            print(f"⚠️ Warning: Could not parse progress file: {e}")
            print("Starting from the beginning.")

    return 0, 1

def save_progress(output_dir, offset, file_index):
    progress_path = output_dir / "progress.json"

    try:
        with open(progress_path, "w") as f:
            json.dump({
                "offset": offset,
                "file_index": file_index,
                "last_updated": datetime.now().isoformat()
            }, f)
    except Exception as e:
        print(f"⚠️ Warning: Failed to save progress: {e}")

def fetch_items(consumer_key, access_token, offset, batch_size, state, retry_count, retry_delay):
    payload = {
        "consumer_key": consumer_key,
        "access_token": access_token,
        "detailType": "complete",
        "state": state,
        "sort": "newest",
        "count": batch_size,
        "offset": offset
    }

    for attempt in range(retry_count + 1):
        try:
            response = requests.post(
                API_URL,
                json=payload,
                headers=API_HEADERS,
                timeout=30
            )
            response.raise_for_status()

            data = response.json()

            if "error" in data and data["error"]:
                print(f"❌ API response contains an error: {data['error']}")
                return None

            return data

        except requests.exceptions.RequestException as e:
            if attempt < retry_count:
                wait_time = retry_delay * (attempt + 1)
                print(f"⚠️ API request failed: {e}. Retrying in {wait_time}s...")
                time.sleep(wait_time)
            else:
                print(f"❌ Failed to fetch data after {retry_count} retries: {e}")
                return None
        except json.JSONDecodeError:
            print("❌ Non-JSON response received!")
            print(response.text if 'response' in locals() else "No response")
            return None

    return None

def save_chunk(items, output_dir, file_index):
    filename = output_dir / f"pocket_items_{file_index:05d}.json"

    try:
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(items, f, indent=2, ensure_ascii=False)
        print(f"💾 Saved → {filename} ({len(items)} articles)")
        return True
    except Exception as e:
        print(f"❌ Failed to save {filename}: {e}")
        return False

def main():
    args = parse_arguments()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    consumer_key, access_token = load_credentials()
    offset, file_index = load_progress(output_dir)

    batch_size = args.batch_size
    chunk_size = args.chunk_size

    total_saved = 0
    buffer = []

    print(f"🔄 Fetching articles from Pocket API...")
    print(f"📂 Saving to: {output_dir.absolute()}")
    print(f"⚙️ Batch size: {batch_size}, Chunk size: {chunk_size}")

    start_time = time.time()
    last_request_time = 0

    try:
        while True:
            elapsed = time.time() - last_request_time
            if elapsed < 1.0:
                time.sleep(1.0 - elapsed)

            last_request_time = time.time()

            data = fetch_items(
                consumer_key,
                access_token,
                offset,
                batch_size,
                args.state,
                args.retry_count,
                args.retry_delay
            )

            if data is None:
                break

            raw_items = list(data.get("list", {}).values())

            if not raw_items:
                print("✅ No more items to retrieve.")
                break

            buffer.extend(raw_items)

            elapsed_time = time.time() - start_time
            articles_per_min = (total_saved + len(buffer)) / (elapsed_time / 60) if elapsed_time > 0 else 0

            print(f"📦 Buffer: {len(buffer)} | Total: {total_saved + len(buffer)} | "
                  f"Rate: {articles_per_min:.1f} articles/min")

            while len(buffer) >= chunk_size:
                chunk = buffer[:chunk_size]
                if save_chunk(chunk, output_dir, file_index):
                    total_saved += len(chunk)
                    buffer = buffer[chunk_size:]
                    file_index += 1

                    save_progress(output_dir, offset + batch_size, file_index)
                else:
                    print("❌ Exiting due to file save error.")
                    return

            offset += batch_size

    except KeyboardInterrupt:
        print("\n⏹️ Process interrupted by user.")
    finally:
        if buffer:
            if save_chunk(buffer, output_dir, file_index):
                total_saved += len(buffer)
                file_index += 1

        save_progress(output_dir, offset, file_index)

        elapsed_time = time.time() - start_time
        minutes = elapsed_time / 60

        print(f"🎉 Total of {total_saved} articles saved in {minutes:.1f} minutes.")
        if minutes > 0:
            print(f"📊 Average rate: {total_saved / minutes:.1f} articles/min")

if __name__ == "__main__":
    main()
