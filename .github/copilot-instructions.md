# GitHub Copilot Instructions for Squad STATS

## Project Overview

This is a **game statistics extraction system** that automatically parses post-match screenshots from a mobile/PC game and stores player statistics in a structured database. The system exposes a REST API for Discord bot integration and statistics queries.

### Core Workflow

```
Screenshot Upload → Image Processing → OCR → Database → API Query → Discord Bot
```

### Technology Stack

- **Language**: Python 3.10+
- **Web Framework**: FastAPI (async)
- **Database**: PostgreSQL (production) / SQLite (development)
- **ORM**: SQLAlchemy 2.0+
- **Image Processing**: OpenCV (cv2)
- **OCR Engine**: Tesseract (pytesseract)
- **Validation**: Pydantic v2
- **Configuration**: YAML files

---

## Project Structure

```
Squad STATS/
├── app/
│   ├── parser/           # Image processing & OCR pipeline
│   │   ├── preprocessor.py    # Image normalization
│   │   ├── detector.py        # Row/column detection
│   │   ├── ocr.py             # OCR utilities
│   │   ├── hero_matcher.py    # Hero portrait matching
│   │   └── pipeline.py        # Main orchestrator
│   ├── core/             # Configuration & utilities
│   │   ├── field_config.py    # YAML config loader
│   │   ├── config.py          # Application settings
│   │   └── database.py        # DB connection
│   ├── models/           # SQLAlchemy ORM models
│   ├── schemas/          # Pydantic schemas
│   ├── api/              # FastAPI endpoints
│   └── services/         # Business logic
├── config/               # YAML configuration files
│   ├── field_extraction.yaml  # Which fields to extract
│   ├── column_mapping.yaml    # Column pixel coordinates
│   └── heroes.yaml            # Hero database
├── tools/                # Development scripts
│   ├── phase1_debug_mapping.py   # Visualize row/column detection
│   ├── phase2_debug_ocr.py       # Test OCR extraction
│   └── phase3_test_api.py        # API testing
├── tests/                # Unit and integration tests
└── docs/                 # Documentation
```

---

## Core Concepts

### 1. Three-Phase Development

**Phase 1: Image Mapping (Current)**
- Goal: Detect player rows and column boundaries
- Output: Visual debug images showing detected regions
- Tool: `python tools/phase1_debug_mapping.py <screenshot.png>`
- No OCR yet - just validate that boxes align with data

**Phase 2: OCR Processing**
- Goal: Extract text and numbers from detected regions
- Output: JSON with structured match data
- Tool: `python tools/phase2_debug_ocr.py <screenshot.png>`
- Verify OCR accuracy before proceeding

**Phase 3: Backend API**
- Goal: Full system with database and REST API
- Output: Working API server
- Command: `uvicorn app.main:app --reload`
- Discord bot integration ready

### 2. Configuration-Driven Extraction

**Key Insight**: Which fields are extracted is determined by YAML config files, NOT hardcoded in Python.

**config/field_extraction.yaml**:
- Defines all extractable fields (kills, deaths, gold, damage, etc.)
- Each field has `enabled: true/false` flag
- Disabling a field skips OCR for that column
- Add new fields by editing YAML, not Python code

**config/column_mapping.yaml**:
- Defines pixel coordinates for each column as **percentages**
- Example: `player_name: {x_start_pct: 0.08, x_end_pct: 0.22}`
- Coordinates are resolution-independent
- Adjust percentages to align with actual screenshots

**How to add a new stat**:
1. Add field definition to `field_extraction.yaml`
2. Add column coordinates to `column_mapping.yaml`
3. Run Phase 1 tool to verify alignment
4. OCR extraction happens automatically based on field type

### 3. Blue Team Only

**IMPORTANT**: The system only extracts stats for the **blue team** (left side, 5 players).

- Red team (right side) is completely ignored
- Row detection only processes Y-axis region 17%-52% (blue team area)
- Each match stores exactly 5 player records
- Database queries are simpler (no team_side needed)

---

## Code Style & Conventions

### Python Style

```python
# Use type hints everywhere
def crop_column(img: np.ndarray, row: Tuple[int, int], column_def: ColumnDefinition) -> np.ndarray:
    """
    Docstrings for all functions.
    
    Args:
        img: Description
        row: Description
        
    Returns:
        Description
    """
    pass

# Prefer dataclasses for data structures
from dataclasses import dataclass

@dataclass
class PlayerMatchData:
    player_name: str
    hero_id: int
    kills: int
    deaths: int
    assists: int

# Use enums for constants
from enum import Enum

class FieldType(Enum):
    TEXT = "text"
    INTEGER = "integer"
    PERCENTAGE = "percentage"
```

### File Organization

- **One class per file** (except small utility classes)
- **Descriptive names**: `preprocessor.py` not `utils.py`
- **Group by feature**: `app/parser/` contains all parsing logic
- **Separate schemas from models**: Pydantic in `schemas/`, SQLAlchemy in `models/`

### Error Handling

```python
# Be specific with exceptions
try:
    img = load_image(path)
except FileNotFoundError:
    logger.error(f"Image not found: {path}")
    raise
except ValueError as e:
    logger.error(f"Invalid image: {e}")
    raise

# Log at appropriate levels
import logging
logger = logging.getLogger(__name__)

logger.debug("Cell crop coordinates: x={x_start}-{x_end}")
logger.info(f"Match {match_id} processed successfully")
logger.warning(f"Low OCR confidence: {confidence}")
logger.error(f"Failed to detect rows: {error}")
```

---

## Common Tasks for Copilot

### Adding a New Stat Field

**Scenario**: Game added a new "Objective Damage" stat and I want to extract it.

**Steps**:
1. Open `config/field_extraction.yaml`
2. Add new field:
   ```yaml
   objective_damage:
     enabled: true
     type: integer
     ocr_config: "digits"
     required: false
     column_key: "objective_damage"
     validation:
       min: 0
       max: 100000
   ```
3. Open `config/column_mapping.yaml`
4. Add column coordinates (measure from screenshot):
   ```yaml
   objective_damage:
     x_start_pct: 0.85
     x_end_pct: 0.92
     y_offset_pct: 0.25
     height_pct: 0.5
     preprocessing: "binarize"
   ```
5. Run: `python tools/phase1_debug_mapping.py screenshot.png`
6. Verify the new rectangle aligns with the "Objective Damage" column
7. Adjust percentages if needed
8. The parser will automatically extract this field (no code changes!)

### Implementing a New API Endpoint

**Scenario**: Add endpoint to get top 10 players by average damage.

**Steps**:
1. Create `app/api/endpoints/leaderboard.py` (if doesn't exist)
2. Define endpoint:
   ```python
   from fastapi import APIRouter, Depends
   from sqlalchemy.orm import Session
   from app.core.database import get_db
   from app.services.stats_service import get_damage_leaderboard
   
   router = APIRouter(prefix="/leaderboard", tags=["leaderboard"])
   
   @router.get("/damage")
   async def damage_leaderboard(
       limit: int = 10,
       period_days: int = 30,
       db: Session = Depends(get_db)
   ):
       """Get top players by average damage in last N days."""
       return get_damage_leaderboard(db, limit=limit, period_days=period_days)
   ```
3. Implement service logic in `app/services/stats_service.py`:
   ```python
   def get_damage_leaderboard(db: Session, limit: int, period_days: int):
       from datetime import datetime, timedelta
       from app.models.player_match import PlayerMatch
       from app.models.player import Player
       from sqlalchemy import func
       
       cutoff_date = datetime.now() - timedelta(days=period_days)
       
       results = db.query(
           Player.name,
           func.avg(PlayerMatch.damage_dealt).label('avg_damage'),
           func.count(PlayerMatch.id).label('games')
       ).join(PlayerMatch).filter(
           PlayerMatch.created_at >= cutoff_date
       ).group_by(Player.id).order_by(
           func.avg(PlayerMatch.damage_dealt).desc()
       ).limit(limit).all()
       
       return [
           {"player": r.name, "avg_damage": int(r.avg_damage), "games": r.games}
           for r in results
       ]
   ```

### Debugging OCR Failures

**Scenario**: Player names are being OCR'd incorrectly.

**Investigation**:
1. Run Phase 1 tool to verify column alignment:
   ```bash
   python tools/phase1_debug_mapping.py problem_screenshot.png
   ```
2. Check if green rectangle fully covers player name
3. If misaligned, adjust `player_name` in `column_mapping.yaml`
4. If aligned but OCR fails, run Phase 2 tool with debug mode:
   ```bash
   python tools/phase2_debug_ocr.py problem_screenshot.png --save-crops
   ```
5. Inspect saved cell crops in `output/cells/`
6. If text is blurry/low contrast, adjust preprocessing in `preprocessor.py`:
   - Try different binarization thresholds
   - Increase enlargement scale factor
   - Adjust CLAHE parameters

### Adding Hero to Database

**Scenario**: New hero released, need to add to system.

**Steps**:
1. Take clean screenshot of hero portrait (just the circular avatar)
2. Crop to consistent size (e.g., 100x100px)
3. Save to `heroes/portraits/hero_<id>_<name>.png`
4. Add entry to `config/heroes.yaml`:
   ```yaml
   - id: 42
     name: "New Hero Name"
     slug: "new_hero"
     role: "Mage"
     portrait_path: "heroes/portraits/hero_042_new_hero.png"
   ```
5. Run database seed: `python tools/seed_database.py`
6. Hero matching will now recognize this hero automatically

---

## Important Constraints & Assumptions

### Screenshot Format

- **Resolution**: Designed for 1920x1080 but handles other 16:9 resolutions
- **Format**: PNG or JPG
- **Source**: Mobile game post-match screen
- **Required element**: Blue team must be visible (left side)
- **Tabs supported**: Overall (gold), Equipment (K/D/A), DPS, Team

### Data Extraction Rules

1. **Only blue team**: Right team (red) completely ignored
2. **5 players per match**: Always expect exactly 5 player rows
3. **Field-driven**: Only extract fields with `enabled: true` in config
4. **Required fields**: If a required field fails OCR, mark match for manual review
5. **Percentages**: Stored as decimals (0.45 not 45%)

### Performance Expectations

- **Processing time**: 5-15 seconds per screenshot
- **OCR accuracy target**: >95% for numeric fields, >90% for text
- **Database**: Can handle millions of match records
- **API response**: <200ms for simple queries, <1s for complex aggregations

---

## Database Schema

### Key Tables

**matches**:
- Stores match-level data (duration, score, timestamp)
- One row per match

**players**:
- Stores unique player records
- Player name is primary identifier

**player_matches**:
- Junction table linking players to matches
- Stores all per-player stats for that match
- One row per player per match (5 rows per match for blue team)

**heroes**:
- Reference table of all heroes
- Used for hero identification and stats filtering

### Common Queries

```python
# Get player's recent matches
matches = db.query(PlayerMatch).filter(
    PlayerMatch.player_id == player_id
).order_by(PlayerMatch.created_at.desc()).limit(20).all()

# Calculate average KDA
from sqlalchemy import func
avg_kda = db.query(
    func.avg((PlayerMatch.kills + PlayerMatch.assists) / func.nullif(PlayerMatch.deaths, 0))
).filter(PlayerMatch.player_id == player_id).scalar()

# Get winrate
total = db.query(func.count(PlayerMatch.id)).filter(
    PlayerMatch.player_id == player_id
).scalar()
wins = db.query(func.count(PlayerMatch.id)).join(Match).filter(
    PlayerMatch.player_id == player_id,
    Match.winning_side == 'left'  # Assuming player is always on left/blue
).scalar()
winrate = wins / total if total > 0 else 0
```

---

## Testing Guidelines

### Unit Tests

```python
# Test individual functions
def test_detect_player_rows():
    config = get_config()
    img = load_and_normalize("tests/fixtures/sample.png")
    rows = detect_player_rows(img, config)
    
    assert len(rows) == 5, "Should detect 5 blue team rows"
    
    for i, (y_start, y_end) in enumerate(rows):
        assert y_end > y_start, f"Row {i} has invalid coordinates"
        assert (y_end - y_start) >= 40, f"Row {i} too short"
```

### Integration Tests

```python
# Test full pipeline
def test_parse_complete_match():
    result = parse_match("tests/fixtures/complete_match.png")
    
    assert result.match.duration_seconds > 0
    assert len(result.players) == 5
    assert all(p.player_name for p in result.players)
```

---

## Deployment Checklist

- [ ] Environment variables set (`.env` file)
- [ ] Tesseract OCR installed on system
- [ ] PostgreSQL database created
- [ ] Database migrations run: `alembic upgrade head`
- [ ] Hero portraits seeded: `python tools/seed_database.py`
- [ ] Upload directory created and writable: `uploads/`
- [ ] Test upload: `POST /upload-screenshot`
- [ ] Verify API health: `GET /health`

---

## ⚠️ CRITICAL RULE - DO NOT MODIFY

### NEVER CHANGE COLUMN MAPPING FILES

**The column mapping YAML files are manually calibrated and must NEVER be modified:**
- `config/column_mapping.yaml`
- `config/screen1_column_mapping.yaml`  
- `config/screen2_column_mapping.yaml`
- Any `*_column_mapping.yaml` file

**These mappings are PERFECT as-is.** If OCR accuracy is low:
1. ✅ DO: Create dedicated OCR functions with better preprocessing
2. ✅ DO: Adjust OCR parameters (thresholds, margins, tesseract config)
3. ✅ DO: Modify Python code in `app/parser/ocr.py` or `main.py`
4. ❌ DON'T: Change x_start_pct, x_end_pct, y_offset_pct, height_pct coordinates
5. ❌ DON'T: Shrink or expand column boundaries

**Rationale**: The user has manually calibrated these coordinates through visual debugging. Any coordinate change requires re-running phase1_debug_mapping.py and manual verification.

### Data Validation Rules

- **teamfight_participation**: Always 0-99 (max 2 digits). If OCR returns more digits, truncate to first 2.
- **battle_id**: Must be 100% accurate - 18 digit number.

### Accuracy Thresholds - DO NOT MODIFY WORKING CODE

**95%+ Accuracy = DO NOT CHANGE:**
- When a system achieves 95%+ accuracy, DO NOT modify that code
- Only try improving systems that are BELOW 95% accuracy
- If asked to "improve" something at 95%+, explain it's already optimal

**Current Accuracy Status (as of Jan 2026):**
- `screen2` OCR extraction: **95%** ✅ - DO NOT MODIFY `_ocr_damage_stat()`
- `screen1` Item matching: **100%** ✅ - DO NOT MODIFY `ItemMatcher`
- `screen1` Total Gold OCR: **100%** ✅ - DO NOT MODIFY
- `screen1` Individual Rating OCR: **100%** ✅ - IMPROVED (was 22%)
- `screen1` KDA OCR: **100%** ✅ - IMPROVED (was 78%)
- `screen1` Hero Level OCR: **78%** ⚠️ - CAN BE IMPROVED (was 67%)
- `screen1` Hero matching: ~78% ⚠️ - CAN BE IMPROVED
- `screen1` Player Name OCR: ~55% - **NOT IMPORTANT** (do not prioritize)

**Battle ID: MUST BE 100% ACCURATE ON ALL SCREEN TYPES**
- Battle ID is the unique match identifier (18 digits)
- If extraction fails or is inaccurate, the entire match data is useless
- Always validate: exactly 18 digits, no extra/missing characters
- Create dedicated `_extract_battle_id()` function per screen type if needed

**When adding new screen types:**
1. First test with existing OCR functions
2. If accuracy < 95%, create dedicated OCR function for that screen
3. Name it clearly: `_ocr_{screentype}_{field}()`
4. Do NOT modify working functions - create new ones
5. **Always ensure Battle ID extraction is 100% accurate first**

**Improvement Priority Order:**
1. Battle ID (must be 100% on all screens) ✅ COMPLETE
2. Individual Rating OCR ✅ COMPLETE (now 100%)
3. KDA OCR ✅ COMPLETE (now 100%)
4. Hero Level OCR (currently 78%) - needs improvement to 90%
5. Hero matching (currently 78%)
6. Player Name OCR - **LOW PRIORITY** (not important)

**Known Hero Level OCR Issues:**
- Digit "1" is often lost or misread (thin character)
- "12" may appear as "2" (first digit lost)
- "11" may appear as "14" (second "1" misread as "4")
- Multi-pass OCR with inference helps but doesn't fully solve

**Important Distinction:**
- "Confidence" = algorithm's internal belief (can be 100% and still wrong)
- "Accuracy" = actual correctness vs verified data (ground truth)
- Always measure against verified test data, not confidence scores

---

## When User Asks...

**"Add support for extracting [new stat]"**:
→ Guide them to update YAML config files, not write new Python code

**"OCR is failing for [field]"**:
→ Suggest running Phase 1/2 debug tools to diagnose alignment or preprocessing issues

**"How do I query [specific statistic]"**:
→ Provide SQLAlchemy query example using the schema (matches, players, player_matches)

**"Can we track red team too?"**:
→ Explain that current design deliberately ignores red team per user requirement. Would need significant refactoring.

**"Add new API endpoint for [use case]"**:
→ Create endpoint in `app/api/endpoints/`, implement business logic in `app/services/`, follow FastAPI patterns

**"Hero matching isn't working"**:
→ Check if hero is in `config/heroes.yaml` and portrait exists in `heroes/portraits/`

---

## Quick Reference

### Run Phase 1 (Visual Debug)
```bash
python tools/phase1_debug_mapping.py screenshot.png
```

### Run Phase 2 (OCR Test)
```bash
python tools/phase2_debug_ocr.py screenshot.png
```

### Start API Server
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Run Tests
```bash
pytest tests/
```

### Database Migration
```bash
alembic revision -m "description"
alembic upgrade head
```

---

## Summary

This project extracts game statistics from screenshots using:
1. **OpenCV** for image processing and region detection
2. **Tesseract OCR** for text extraction
3. **YAML configuration** to define what and where to extract
4. **SQLAlchemy** for database persistence
5. **FastAPI** for REST API

The three-phase approach ensures each component works before building on it. Configuration files drive extraction logic, making the system adaptable without code changes.

When helping with this project:
- Respect the three-phase structure
- Prioritize configuration over code for new fields
- Follow the blue-team-only constraint
- Use type hints and clear docstrings
- Test with the provided debug tools
