"""
Hero Portrait Scraper

Downloads all hero portrait images from the Mobile Legends API.
Can be run multiple times to update the hero portrait database.

Usage:
    python tools/scrape_hero_portraits.py              # Download all heroes
    python tools/scrape_hero_portraits.py --force      # Re-download existing portraits
    python tools/scrape_hero_portraits.py --start 100  # Start from hero ID 100
"""

import http.client
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional, Dict, Any
import urllib.request
import argparse

# API Configuration
API_HOST = "api.gms.moontontech.com"
API_ENDPOINT = "/api/gms/source/2669606/2756564"
API_HEADERS = {
    'accept': 'application/json, text/plain, */*',
    'accept-language': 'de,en;q=0.9,pt;q=0.8',
    'content-type': 'application/json;charset=UTF-8',
    'origin': 'https://www.mobilelegends.com',
    'priority': 'u=1, i',
    'referer': 'https://www.mobilelegends.com/',
    'sec-ch-ua': '"Chromium";v="142", "Microsoft Edge";v="142", "Not_A Brand";v="99"',
    'sec-ch-ua-mobile': '?1',
    'sec-ch-ua-platform': '"Android"',
    'sec-fetch-dest': 'empty',
    'sec-fetch-mode': 'cors',
    'sec-fetch-site': 'cross-site',
    'user-agent': 'Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Mobile Safari/537.36 Edg/142.0.0.0',
    'x-actid': '2669607',
    'x-appid': '2669606',
    'x-lang': 'en'
}

# Output directory
PORTRAITS_DIR = Path("heroes/portraits")


def fetch_hero_data(hero_id: int) -> Optional[Dict[str, Any]]:
    """
    Fetch hero data from the API.
    
    Args:
        hero_id: Hero ID to fetch
        
    Returns:
        Hero data record or None if not found
    """
    authorization = os.environ.get('NEXUS_MOONTON_AUTHORIZATION')
    if not authorization:
        print("  NEXUS_MOONTON_AUTHORIZATION is not set")
        return None

    conn: http.client.HTTPSConnection | None = None
    try:
        conn = http.client.HTTPSConnection(API_HOST, timeout=10)
        headers = {**API_HEADERS, 'authorization': authorization}
        
        # Prepare payload with correct structure
        payload = json.dumps({
            "pageSize": 20,
            "pageIndex": 1,
            "filters": [
                {"field": "hero_id", "operator": "eq", "value": str(hero_id)}
            ],
            "sorts": [],
            "object": []
        })
        
        conn.request("POST", API_ENDPOINT, payload, headers)
        res = conn.getresponse()
        data = res.read()
        
        if res.status != 200:
            return None
        
        response = json.loads(data.decode("utf-8"))
        
        # Check response code (0 = success in this API)
        if response.get('code') != 0 or not response.get('data'):
            return None
        
        # Check if we have records
        records = response['data'].get('records', [])
        if not records:
            return None
        
        return records[0]  # Return first record
        
    except Exception as e:
        print(f"  Error fetching hero {hero_id}: {e}")
        return None
    finally:
        if conn is not None:
            conn.close()


def download_image(url: str, output_path: Path) -> bool:
    """
    Download image from URL to file.
    
    Args:
        url: Image URL
        output_path: Path to save image
        
    Returns:
        True if successful
    """
    try:
        # Add headers to avoid 403 errors
        req = urllib.request.Request(
            url,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Referer': 'https://www.mobilelegends.com/'
            }
        )
        
        with urllib.request.urlopen(req, timeout=30) as response:
            data = response.read()
            
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(data)
        
        return True
        
    except Exception as e:
        print(f"  ✗ Failed to download image: {e}")
        return False


def sanitize_filename(name: str) -> str:
    """
    Sanitize hero name for use in filename.
    
    Args:
        name: Hero name
        
    Returns:
        Sanitized filename
    """
    # Remove special characters, replace spaces with underscores
    import re
    name = re.sub(r'[<>:"/\\|?*]', '', name)
    name = name.replace(' ', '_').replace("'", "").lower()
    return name


def extract_hero_info(record: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """
    Extract relevant hero information from API record.
    
    Args:
        record: API response record
        
    Returns:
        Dictionary with hero_id, name, and portrait_url
    """
    try:
        # API structure: record.data contains hero info
        data = record.get('data', {})
        
        # Get nested hero object
        hero_obj = data.get('hero', {}).get('data', {})
        
        # Get hero_id from nested hero object
        hero_id = hero_obj.get('heroid', hero_obj.get('hero_id', ''))
        
        # Get name from nested hero object
        name = hero_obj.get('name', 'unknown')
        
        # Get portrait URL (called 'head' in the API at data level)
        portrait_url = data.get('head', data.get('head_big', ''))
        
        # Alternative: use squarehead from hero object
        if not portrait_url and hero_obj:
            portrait_url = hero_obj.get('squarehead', hero_obj.get('head', ''))
        
        if not hero_id or not portrait_url:
            return None
        
        return {
            'hero_id': str(hero_id),
            'name': name,
            'portrait_url': portrait_url
        }
        
    except Exception as e:
        print(f"  Error parsing hero data: {e}")
        return None


def scrape_heroes(start_id: int = 1, end_id: int = 9999, force: bool = False) -> None:
    """
    Scrape all hero portraits from the API.
    
    Args:
        start_id: Starting hero ID
        end_id: Maximum hero ID to try
        force: Force re-download of existing portraits
    """
    print("=" * 60)
    print("HERO PORTRAIT SCRAPER")
    print("=" * 60)
    print(f"\nSettings:")
    print(f"  Hero ID range: {start_id} - {end_id}")
    print(f"  Force re-download: {force}")
    print(f"  Output directory: {PORTRAITS_DIR}")
    print()
    
    # Create output directory
    PORTRAITS_DIR.mkdir(parents=True, exist_ok=True)
    
    # Statistics
    total_found = 0
    total_downloaded = 0
    total_skipped = 0
    total_failed = 0
    consecutive_not_found = 0
    max_consecutive_failures = 20  # Stop after 20 consecutive failures
    
    print("Starting scan...\n")
    
    for hero_id in range(start_id, end_id + 1):
        print(f"[{hero_id:4d}] ", end="", flush=True)
        
        # Fetch hero data
        data = fetch_hero_data(hero_id)
        
        if not data:
            print(f"Not found")
            consecutive_not_found += 1
            
            # Stop if too many consecutive failures
            if consecutive_not_found >= max_consecutive_failures:
                print(f"\n⚠ Stopped after {max_consecutive_failures} consecutive not-found responses")
                break
            
            # Rate limiting
            time.sleep(0.2)
            continue
        
        # Reset consecutive not found counter
        consecutive_not_found = 0
        total_found += 1
        
        # Extract hero info
        hero_info = extract_hero_info(data)
        
        if not hero_info or not hero_info.get('portrait_url'):
            # Debug output
            print(f"No portrait URL found")
            if data:
                print(f"  Available keys: {list(data.keys())[:10]}")
                if 'data' in data:
                    print(f"  data.keys: {list(data['data'].keys())[:10]}")
            total_failed += 1
            time.sleep(0.2)
            continue
        
        hero_name = hero_info['name']
        portrait_url = hero_info['portrait_url']
        
        # Determine output filename
        safe_name = sanitize_filename(hero_name)
        output_filename = f"hero_{hero_id:03d}_{safe_name}.png"
        output_path = PORTRAITS_DIR / output_filename
        
        # Check if already exists
        if output_path.exists() and not force:
            print(f"'{hero_name}' - Already exists (skipped)")
            total_skipped += 1
            time.sleep(0.1)
            continue
        
        # Download portrait
        print(f"'{hero_name}' - Downloading...", end="", flush=True)
        
        success = download_image(portrait_url, output_path)
        
        if success:
            # Get file size
            file_size = output_path.stat().st_size
            print(f"\r[{hero_id:4d}] '{hero_name}' - ✓ Downloaded ({file_size:,} bytes)")
            total_downloaded += 1
        else:
            print(f"\r[{hero_id:4d}] '{hero_name}' - ✗ Failed")
            total_failed += 1
        
        # Rate limiting to avoid overwhelming the API
        time.sleep(0.3)
    
    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Heroes found:       {total_found}")
    print(f"Portraits downloaded: {total_downloaded}")
    print(f"Skipped (existing): {total_skipped}")
    print(f"Failed:             {total_failed}")
    print(f"\nPortraits saved to: {PORTRAITS_DIR.absolute()}")
    print("=" * 60)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Download hero portraits from Mobile Legends API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python tools/scrape_hero_portraits.py                # Download all heroes
  python tools/scrape_hero_portraits.py --force        # Re-download all
  python tools/scrape_hero_portraits.py --start 100    # Start from ID 100
  python tools/scrape_hero_portraits.py --end 500      # Only IDs 1-500
        """
    )
    
    parser.add_argument(
        '--start',
        type=int,
        default=1,
        help='Starting hero ID (default: 1)'
    )
    
    parser.add_argument(
        '--end',
        type=int,
        default=9999,
        help='Ending hero ID (default: 9999)'
    )
    
    parser.add_argument(
        '--force',
        action='store_true',
        help='Force re-download of existing portraits'
    )
    
    args = parser.parse_args()
    
    try:
        scrape_heroes(
            start_id=args.start,
            end_id=args.end,
            force=args.force
        )
    except KeyboardInterrupt:
        print("\n\n⚠ Interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
