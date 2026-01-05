"""Item Icon Scraper - Validated Against Wiki Equipment Page

Downloads item icons from Mobile Legends Fandom Wiki.
Only downloads/keeps items that appear on the official Equipment page.

Workflow:
1. Fetch item list from game API
2. Scrape current equipment list from wiki Equipment page
3. Download icons only for items that exist on wiki
4. Clean up any old items not on current wiki list
"""

import requests
import os
import json
import re
from pathlib import Path
from bs4 import BeautifulSoup
from typing import Set, List, Dict

# Game data API (for item list)
GAME_API = "https://synatic.horben-bleiben.de/api/neo4j/items"
# Wiki Equipment page (canonical list of current items)
WIKI_EQUIPMENT_PAGE = "https://mobile-legends.fandom.com/wiki/Equipment"
# Wiki API (for icon images)
WIKI_API = "https://mobile-legends.fandom.com/api.php"

# Output directories
ITEMS_DIR = Path("items/icons")
METADATA_FILE = Path("items/items_metadata_validated.json")

# Name mappings: Game API name -> Wiki name
NAME_MAPPINGS = {
    "Demon Boots": "Demon Shoes",
    "Magic Boots": "Magic Shoes",
    "Rapid Boots- Conceal": "Rapid Boots",
    "Flame Hunter's Demon Boots": "Demon Shoes",
    "Flame Hunter's Magic Boots": "Magic Shoes",
    "Ice Hunter's Magic Boots": "Magic Shoes",
}


def fetch_current_equipment_from_wiki() -> Set[str]:
    """
    Scrape the wiki Equipment page to get the canonical list of current items.
    
    Returns:
        Set of current equipment names as they appear on the wiki
    """
    print("🌐 Fetching current equipment list from wiki...")
    
    try:
        response = requests.get(WIKI_EQUIPMENT_PAGE, timeout=15)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Find all links in the "List of equipment" section
        # Equipment items are linked like: <a href="/wiki/Item_Name">Item Name</a>
        equipment_set = set()
        
        # Find the "List of equipment" section
        list_section = soup.find('span', id='List_of_equipment')
        if list_section:
            # Get the parent heading, then find all equipment links after it
            section_parent = list_section.find_parent(['h2', 'h3'])
            if section_parent:
                # Find the equipment gallery (usually in a div or table after heading)
                current = section_parent.find_next_sibling()
                
                # Search through next siblings until we hit another section
                while current and current.name not in ['h2', 'h3']:
                    # Find all wiki links to equipment pages
                    for link in current.find_all('a', href=True):
                        href = link['href']
                        # Equipment links are like /wiki/Blade_of_Despair
                        if href.startswith('/wiki/') and not any(x in href for x in ['Category:', 'File:', 'Equipment#', 'Special:', 'Template:']):
                            # Extract item name from URL
                            item_name = href.replace('/wiki/', '').replace('_', ' ')
                            # Get the actual text if available
                            if link.get_text(strip=True):
                                item_name = link.get_text(strip=True)
                            
                            # Skip meta pages, blessed boot variants, and Conceal items
                            skip_prefixes = ["Flame Hunter's", "Ice Hunter's"]
                            skip_keywords = ["Conceal"]
                            if item_name and item_name not in ['Equipment', 'Mobile Legends: Bang Bang Wiki']:
                                # Skip blessed boot variants and Conceal items
                                if not any(item_name.startswith(prefix) for prefix in skip_prefixes):
                                    if not any(keyword in item_name for keyword in skip_keywords):
                                        equipment_set.add(item_name)
                    
                    current = current.find_next_sibling()
        
        # Also search for any table/gallery with equipment items
        # Sometimes equipment is displayed in divs with "wikia-gallery" class
        for gallery_item in soup.find_all(['div', 'figure'], class_=re.compile('gallery|wikia-gallery')):
            for link in gallery_item.find_all('a', href=True):
                href = link['href']
                if href.startswith('/wiki/') and not any(x in href for x in ['Category:', 'File:', 'Equipment#', 'Special:', 'Template:']):
                    item_name = link.get_text(strip=True)
                    # Skip blessed boot variants and Conceal items
                    skip_prefixes = ["Flame Hunter's", "Ice Hunter's"]
                    skip_keywords = ["Conceal"]
                    if item_name and item_name not in ['Equipment', 'Mobile Legends: Bang Bang Wiki']:
                        if not any(item_name.startswith(prefix) for prefix in skip_prefixes):
                            if not any(keyword in item_name for keyword in skip_keywords):
                                equipment_set.add(item_name)
        
        print(f"✓ Found {len(equipment_set)} current equipment items on wiki (excluding blessed boots & Conceal)")
        
        # Debug: Print first 10 items
        if equipment_set:
            print(f"  Sample items: {sorted(list(equipment_set))[:10]}")
        
        return equipment_set
        
    except Exception as e:
        print(f"❌ Failed to fetch equipment list from wiki: {e}")
        print("⚠️  Continuing without validation...")
        return set()


def fetch_items_from_game_api() -> List[str]:
    """Fetch current items from game data API."""
    print("\n📥 Fetching items from game data API...")
    
    try:
        response = requests.get(GAME_API, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if "items" in data:
            items = data["items"]
            # Extract just the names (without variants like "- Favor")
            base_items = set()
            for item in items:
                name = item.get('name', '')
                # Get base item name (remove "- Favor", "- Conceal", etc.)
                if ' - ' in name:
                    base_name = name.split(' - ')[0]
                    base_items.add(base_name)
                else:
                    base_items.add(name)
            
            print(f"✓ Found {len(base_items)} unique items from API")
            return sorted(base_items)
        else:
            return []
            
    except Exception as e:
        print(f"❌ Failed to fetch items from API: {e}")
        return []


def normalize_name(name: str) -> str:
    """Normalize item name for comparison."""
    # Remove special characters, convert to lowercase, strip whitespace
    return re.sub(r'[^\w\s]', '', name).lower().strip()


def validate_items_against_wiki(api_items: List[str], wiki_equipment: Set[str]) -> tuple[List[str], List[str]]:
    """
    Validate API items against wiki equipment list.
    
    Returns:
        (valid_items, invalid_items)
    """
    if not wiki_equipment:
        print("⚠️  No wiki equipment list available, accepting all API items")
        return api_items, []
    
    print(f"\n🔍 Validating {len(api_items)} API items against {len(wiki_equipment)} wiki items...")
    
    # Create normalized wiki set for matching
    wiki_normalized = {normalize_name(item): item for item in wiki_equipment}
    
    valid_items = []
    invalid_items = []
    
    for api_item in api_items:
        # Check both original and mapped names
        names_to_check = [api_item]
        if api_item in NAME_MAPPINGS:
            names_to_check.append(NAME_MAPPINGS[api_item])
        
        # Check if any variant exists on wiki
        found = False
        for name in names_to_check:
            normalized = normalize_name(name)
            if normalized in wiki_normalized:
                valid_items.append(api_item)
                found = True
                break
        
        if not found:
            invalid_items.append(api_item)
    
    print(f"✓ Valid items: {len(valid_items)}")
    print(f"✗ Invalid items (not on wiki): {len(invalid_items)}")
    
    if invalid_items and len(invalid_items) <= 20:
        print(f"\n  Items to skip: {', '.join(invalid_items)}")
    
    return valid_items, invalid_items


def get_wiki_icon_url(item_name: str) -> str:
    """Get icon URL from wiki for an item."""
    # Check for name mapping
    wiki_name = NAME_MAPPINGS.get(item_name, item_name)
    
    # Try exact match first
    params = {
        "action": "query",
        "titles": f"File:{wiki_name}.png",
        "prop": "imageinfo",
        "iiprop": "url",
        "format": "json"
    }
    
    try:
        response = requests.get(WIKI_API, params=params, timeout=10)
        data = response.json()
        
        pages = data.get("query", {}).get("pages", {})
        for page in pages.values():
            if "imageinfo" in page:
                return page["imageinfo"][0]["url"]
        
        # If exact match fails, try with spaces replaced by underscores
        alt_name = wiki_name.replace(" ", "_")
        params["titles"] = f"File:{alt_name}.png"
        response = requests.get(WIKI_API, params=params, timeout=10)
        data = response.json()
        
        pages = data.get("query", {}).get("pages", {})
        for page in pages.values():
            if "imageinfo" in page:
                return page["imageinfo"][0]["url"]
        
    except Exception as e:
        print(f"  ⚠️  Error fetching URL for {item_name}: {e}")
    
    return None


def download_item_icon(item_name: str, url: str) -> bool:
    """Download item icon from URL."""
    try:
        # Create filename
        filename = f"item_{item_name}.png"
        filepath = ITEMS_DIR / filename
        
        # Download image
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        
        # Save to file
        with open(filepath, 'wb') as f:
            f.write(response.content)
        
        return True
        
    except Exception as e:
        print(f"  ❌ Download failed: {e}")
        return False


def cleanup_old_items(valid_items: List[str]):
    """Delete item icons that are not in the valid items list."""
    print(f"\n🧹 Cleaning up old items...")
    
    if not ITEMS_DIR.exists():
        print("  No items directory found, skipping cleanup")
        return
    
    # Get list of files in items directory
    existing_files = list(ITEMS_DIR.glob("item_*.png"))
    
    if not existing_files:
        print("  No existing items found, skipping cleanup")
        return
    
    # Create set of valid filenames
    valid_filenames = {f"item_{item}.png" for item in valid_items}
    
    deleted_count = 0
    for file_path in existing_files:
        if file_path.name not in valid_filenames:
            print(f"  🗑️  Deleting: {file_path.name}")
            file_path.unlink()
            deleted_count += 1
    
    if deleted_count > 0:
        print(f"✓ Deleted {deleted_count} old item(s)")
    else:
        print("✓ No old items to delete")


def main():
    """Main scraping workflow."""
    print("=" * 70)
    print("Item Icon Scraper - Wiki Validated")
    print("=" * 70)
    
    # Create output directory
    ITEMS_DIR.mkdir(parents=True, exist_ok=True)
    
    # Step 1: Get canonical equipment list from wiki (this is our source of truth)
    wiki_equipment = fetch_current_equipment_from_wiki()
    
    if not wiki_equipment:
        print("\n❌ Failed to fetch equipment from wiki. Exiting.")
        return
    
    # Step 2: Use wiki equipment as the list to download (not API)
    items_to_download = sorted(wiki_equipment)
    
    print(f"\n📥 Will download {len(items_to_download)} items from wiki...")
    
    # Step 3: Download icons for all wiki equipment
    metadata = []
    success_count = 0
    failed_items = []
    
    for i, item_name in enumerate(items_to_download, 1):
        print(f"\n[{i}/{len(items_to_download)}] {item_name}")
        
        # Always re-download to get latest version (icons can change with updates)
        filepath = ITEMS_DIR / f"item_{item_name}.png"
        
        # Get icon URL
        icon_url = get_wiki_icon_url(item_name)
        
        if icon_url:
            print(f"  📥 Downloading from wiki...")
            if download_item_icon(item_name, icon_url):
                print(f"  ✓ Downloaded successfully")
                metadata.append({
                    "name": item_name,
                    "wiki_name": NAME_MAPPINGS.get(item_name, item_name),
                    "filename": filepath.name,
                    "url": icon_url
                })
                success_count += 1
            else:
                failed_items.append(item_name)
        else:
            print(f"  ✗ Icon not found on wiki")
            failed_items.append(item_name)
    
    # Step 4: Save metadata
    with open(METADATA_FILE, 'w', encoding='utf-8') as f:
        json.dump({
            "total_items": len(items_to_download),
            "successful_downloads": success_count,
            "failed_downloads": len(failed_items),
            "validated_against_wiki": True,
            "wiki_equipment_count": len(wiki_equipment),
            "failed_items": failed_items,
            "items": metadata
        }, f, indent=2, ensure_ascii=False)
    
    # Step 5: Cleanup old items not on wiki
    cleanup_old_items(items_to_download)
    
    # Summary
    print("\n" + "=" * 70)
    print("✅ Scraping Complete!")
    print("=" * 70)
    print(f"Total items from wiki: {len(items_to_download)}")
    print(f"Successfully downloaded: {success_count}")
    print(f"Failed downloads: {len(failed_items)}")
    print(f"Metadata saved to: {METADATA_FILE}")
    print("=" * 70)
    
    if failed_items:
        print(f"\n⚠️  Failed to download {len(failed_items)} items:")
        for item in failed_items[:20]:  # Show first 20
            print(f"  - {item}")
        if len(failed_items) > 20:
            print(f"  ... and {len(failed_items) - 20} more")


if __name__ == "__main__":
    main()
