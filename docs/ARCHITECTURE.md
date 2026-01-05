# System Architecture

## Overview

This document provides a comprehensive architectural design for the Squad STATS system, which automatically extracts game statistics from screenshots using computer vision and OCR.

## Core Design Principles

1. **Separation of Concerns** - Clear boundaries between image processing, data storage, and API layers
2. **Configurability** - Field extraction driven by YAML config files
3. **Testability** - Each phase independently testable
4. **Scalability** - Async processing queue for handling multiple uploads
5. **Maintainability** - Clean code structure optimized for GitHub Copilot assistance

---

## 1. High-Level Architecture

### 1.1 Components

```
┌─────────────────────────────────────────────────────────────┐
│                     CLIENT LAYER                            │
│  Discord Bot | Web UI | Mobile App | Direct API Clients     │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           │ HTTPS
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                   API GATEWAY (FastAPI)                      │
│                                                              │
│  ┌────────────┐  ┌────────────┐  ┌─────────────┐          │
│  │  Upload    │  │  Matches   │  │   Players   │          │
│  │  Endpoint  │  │  Endpoint  │  │   Endpoint  │          │
│  └────────────┘  └────────────┘  └─────────────┘          │
│                                                              │
│  Authentication | Rate Limiting | Input Validation          │
└───────┬──────────────────────────────────┬──────────────────┘
        │                                  │
        │ Store Image                      │ Query Data
        ▼                                  ▼
┌──────────────────┐          ┌────────────────────────────┐
│  Image Storage   │          │    PostgreSQL Database     │
│  (Local/S3)      │          │                            │
│                  │          │  - matches                 │
│  /uploads/       │          │  - players                 │
│  ├─ {match_id}/  │          │  - player_matches          │
│     └─ orig.png  │          │  - heroes                  │
└──────────────────┘          └────────────────────────────┘
        │
        │ Enqueue Job
        ▼
┌─────────────────────────────────────────────────────────────┐
│              PROCESSING QUEUE (Celery/RQ)                    │
│                                                              │
│  Task: process_screenshot(match_id, image_path)             │
└───────┬──────────────────────────────────────────────────────┘
        │
        │ Worker picks up task
        ▼
┌─────────────────────────────────────────────────────────────┐
│                   IMAGE PROCESSOR                            │
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌─────────────────┐  │
│  │ Preprocessor │→ │   Detector   │→ │   OCR Engine    │  │
│  │              │  │              │  │                 │  │
│  │ - Resize     │  │ - Row detect │  │ - Tesseract     │  │
│  │ - Normalize  │  │ - Col segment│  │ - Text extract  │  │
│  │ - Enhance    │  │ - Crop cells │  │ - Number parse  │  │
│  └──────────────┘  └──────────────┘  └─────────────────┘  │
│                                                              │
│  ┌──────────────┐  ┌──────────────────────────────────┐   │
│  │ Hero Matcher │  │   Field Config Loader            │   │
│  │              │  │   (field_extraction.yaml)        │   │
│  │ - Template   │  │   (column_mapping.yaml)          │   │
│  │   matching   │  │                                  │   │
│  │ - Feature    │  │   Drives which fields to extract │   │
│  │   matching   │  └──────────────────────────────────┘   │
│  └──────────────┘                                          │
└───────┬──────────────────────────────────────────────────────┘
        │
        │ Structured Data
        ▼
┌─────────────────────────────────────────────────────────────┐
│                    DATA SERVICE                              │
│                                                              │
│  - Validate extracted data                                  │
│  - Normalize player names                                   │
│  - Check for duplicate matches (idempotency)                │
│  - Create/update player records                             │
│  - Store match and player_match records                     │
│  - Compute derived statistics                               │
└───────┬──────────────────────────────────────────────────────┘
        │
        │ Write to DB
        ▼
┌────────────────────────────────────────────────────────────┐
│                    PostgreSQL                               │
└────────────────────────────────────────────────────────────┘
```

---

## 2. Component Details

### 2.1 API Gateway (FastAPI)

**Responsibility:** HTTP interface for all external interactions

**Technologies:**
- FastAPI (async Python web framework)
- Pydantic for request/response validation
- JWT or API key authentication
- Rate limiting via slowapi

**Key Endpoints:**

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/upload-screenshot` | POST | Accept screenshot file, enqueue processing |
| `/match/{match_id}` | GET | Retrieve full match details |
| `/player/{player_name}/summary` | GET | Aggregate player statistics |
| `/player/{player_name}/matches` | GET | List player's recent matches |
| `/leaderboard/{metric}` | GET | Top players by stat (damage, winrate, etc.) |
| `/health` | GET | Health check for monitoring |

**Features:**
- Multipart file upload handling
- Async processing (doesn't block on OCR)
- Job status polling
- Error handling with proper HTTP codes
- OpenAPI/Swagger documentation

---

### 2.2 Image Processor

**Responsibility:** Transform screenshot → structured data

#### 2.2.1 Preprocessor Module (`parser/preprocessor.py`)

Normalizes images to consistent format for reliable detection and OCR.

**Steps:**
1. **Load Image** - Read with OpenCV/PIL
2. **Aspect Ratio Check** - Validate image is roughly 16:9
3. **Resize** - Scale to reference resolution (1920x1080)
4. **Grayscale Conversion** - Simplify for edge detection
5. **Noise Reduction** - Bilateral filter or Gaussian blur
6. **Contrast Enhancement** - CLAHE (Contrast Limited Adaptive Histogram Equalization)
7. **Binarization** - Adaptive thresholding for OCR

**Output:** Normalized image ready for analysis

---

#### 2.2.2 Detector Module (`parser/detector.py`)

Finds player rows and segments columns.

**Row Detection Algorithm:**

```
1. Apply Canny edge detection
2. Use morphological closing to connect edges
3. Detect horizontal lines with HoughLinesP
4. Cluster lines into rows (typically 10 rows for 10 players)
5. Sort rows top to bottom
6. Classify into left team (rows 1-5) and right team (rows 6-10)
```

**Column Segmentation:**

Instead of detecting columns dynamically (which fails when text overflows), we use **fixed percentage-based coordinates**:

```yaml
# Example: For 1920x1080 reference resolution
columns:
  hero_portrait:
    x_start_pct: 0.02    # 2% from left = 38px
    x_end_pct: 0.08      # 8% from left = 154px
  
  player_name:
    x_start_pct: 0.08
    x_end_pct: 0.22      # Wide enough to capture long names
  
  kills:
    x_start_pct: 0.22
    x_end_pct: 0.26
  
  deaths:
    x_start_pct: 0.26
    x_end_pct: 0.30
  
  # ... and so on for all columns
```

**Critical Insight:** By using fixed column regions, we avoid the "player name spills into gold column" problem. Each column is a predetermined rectangle, and OCR extracts whatever text appears in that rectangle.

**Output:** List of cropped cell images, one per (row, column) combination

---

#### 2.2.3 OCR Module (`parser/ocr.py`)

Extracts text from cropped cell images.

**Tesseract Configuration:**

Different columns need different OCR settings:

```python
# For player names (text, letters, numbers, spaces)
TEXT_CONFIG = "--psm 7 --oem 3 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_ "

# For numeric stats (digits only)
DIGIT_CONFIG = "--psm 7 --oem 3 -c tessedit_char_whitelist=0123456789"

# For percentages (digits + %)
PERCENT_CONFIG = "--psm 7 --oem 3 -c tessedit_char_whitelist=0123456789.%"
```

**Post-Processing:**
- Strip whitespace
- Replace common OCR errors:
  - `O` → `0` (when expecting number)
  - `l` → `1` (when expecting number)
  - Remove stray characters
- Validate format (e.g., K/D/A should be "X/Y/Z")

**Functions:**

```python
def ocr_text(img: np.ndarray) -> str:
    """Extract general text (player names)."""

def ocr_integer(img: np.ndarray) -> int:
    """Extract and parse integer value."""

def ocr_percentage(img: np.ndarray) -> float:
    """Extract percentage value (e.g., "45.2%" → 0.452)."""
```

---

#### 2.2.4 Hero Matcher Module (`parser/hero_matcher.py`)

Identifies heroes from portrait images.

**Approach 1: Template Matching**
- Maintain a database of reference hero portraits
- For each cropped hero portrait, compute similarity with all references
- Use normalized cross-correlation
- Return hero with highest match score (if above threshold)

**Approach 2: Feature Matching (More Robust)**
- Use ORB (Oriented FAST and Rotated BRIEF) or SIFT
- Extract keypoints and descriptors from portraits
- Match descriptors using BFMatcher or FLANN
- Count good matches
- Return hero with most matches

**Hero Database Structure:**

```
heroes/portraits/
├── hero_001_warrior.png
├── hero_002_mage.png
├── hero_003_assassin.png
└── ...

config/heroes.yaml:
heroes:
  - id: 1
    name: "Warrior"
    slug: "warrior"
    role: "Tank"
    portrait_path: "heroes/portraits/hero_001_warrior.png"
```

**Fallback:** If no match found, store as "Unknown" and log for manual review.

---

#### 2.2.5 Pipeline Orchestrator (`parser/pipeline.py`)

Coordinates all parsing steps.

**Main Function:**

```python
def parse_match(image_path: str, config: FieldConfig) -> MatchData:
    """
    Complete pipeline from screenshot to structured data.
    
    Returns:
        MatchData object with:
            - match_level fields (duration, score, etc.)
            - list of 10 PlayerMatchData objects
    """
    # 1. Preprocess
    img = preprocessor.load_and_normalize(image_path)
    
    # 2. Detect rows
    rows = detector.detect_player_rows(img)
    
    # 3. For each row, segment columns and OCR
    players = []
    for row_img in rows:
        player_data = {}
        for field in config.enabled_fields:
            cell_img = detector.crop_column(row_img, field.column_mapping)
            
            if field.type == "text":
                player_data[field.name] = ocr.ocr_text(cell_img)
            elif field.type == "integer":
                player_data[field.name] = ocr.ocr_integer(cell_img)
            # ... etc
        
        # 4. Identify hero
        hero_img = detector.crop_column(row_img, config.hero_column)
        player_data["hero_id"] = hero_matcher.identify_hero(hero_img)
        
        players.append(PlayerMatchData(**player_data))
    
    # 5. Extract match-level data (from top/bottom of image)
    match_data = extract_match_metadata(img)
    
    return MatchData(match=match_data, players=players)
```

---

### 2.3 Data Service

**Responsibility:** Business logic for data validation and storage

**Key Operations:**

1. **Match Deduplication**
   - Check if match already exists by game_match_id or content hash
   - Prevent duplicate storage of same screenshot

2. **Player Normalization**
   - Handle name variations (e.g., "Player123" vs "player123")
   - Merge duplicate player records
   - Track player aliases

3. **Data Validation**
   - Ensure kills, deaths, assists are non-negative
   - Validate gold values are reasonable
   - Check that team totals make sense

4. **Derived Statistics**
   - Compute KDA ratio: (K + A) / max(D, 1)
   - Compute per-minute stats: damage / (duration_seconds / 60)
   - Update player aggregate statistics

---

### 2.4 Database Layer

**Technology:** PostgreSQL (production) / SQLite (development)

**ORM:** SQLAlchemy with Alembic migrations

**Indexing Strategy:**
- `players.name` - For player lookups
- `matches.played_at` - For time-range queries
- `player_matches.player_id, player_matches.match_id` - For joins
- `player_matches.hero_id` - For hero-specific stats

**Backup Strategy:**
- Daily automated backups
- Point-in-time recovery enabled
- Backup uploaded screenshots separately

---

## 3. Data Models

### 3.1 Match-Level Data

Fields extracted from screenshot:

| Field | Type | Source | Example |
|-------|------|--------|---------|
| `game_match_id` | String | In-game UI | "M2026010112345" |
| `played_at` | DateTime | Upload time or parsed | "2026-01-01 14:30:00" |
| `duration_seconds` | Integer | UI timer | 1245 (20m 45s) |
| `final_score_left` | Integer | Scoreboard | 37 |
| `final_score_right` | Integer | Scoreboard | 15 |
| `winning_side` | Enum | Derived | "left" |
| `game_mode` | String | UI or filename | "ranked" |

### 3.2 Per-Player Data

Fields extracted per player (10 total):

| Field | Type | OCR Type | Column | Example |
|-------|------|----------|--------|---------|
| `team_side` | Enum | - | Derived from row position | "left" |
| `player_name` | String | Text | Name column | "ProGamer99" |
| `hero_id` | Integer | Image match | Hero portrait | 42 |
| `hero_level` | Integer | Digit | Next to portrait | 15 |
| `kills` | Integer | Digit | K column | 12 |
| `deaths` | Integer | Digit | D column | 3 |
| `assists` | Integer | Digit | A column | 18 |
| `total_gold` | Integer | Digit | Total Gold | 12500 |
| `jungle_gold` | Integer | Digit | Jungle Gold | 3200 |
| `kill_gold` | Integer | Digit | Kill Gold | 4500 |
| `minion_gold` | Integer | Digit | Minion Gold | 4800 |
| `damage_dealt` | Integer | Digit | Damage | 45000 |
| `damage_taken` | Integer | Digit | Tank | 32000 |
| `healing_shields` | Integer | Digit | Heal | 8500 |
| `crowd_control` | Integer | Digit | CC | 120 |
| `teamfight_participation` | Float | Percent | TF% | 0.85 |
| `team_gold_pct` | Float | Percent | Gold% | 0.22 |
| `team_damage_pct` | Float | Percent | DMG% | 0.28 |
| `mvp_badge` | String | Text/Image | Badge area | "gold_mvp" |
| `mvp_score` | Float | Digit | MVP rating | 8.7 |

### 3.3 Derived Statistics (Computed)

Not extracted from screenshots, but calculated from stored data:

**Per-Player Aggregates:**
- `total_games` = COUNT(player_matches)
- `wins` = COUNT(player_matches WHERE player's team won)
- `losses` = total_games - wins
- `winrate` = wins / total_games
- `avg_kills` = AVG(kills)
- `avg_deaths` = AVG(deaths)
- `avg_assists` = AVG(assists)
- `avg_kda` = AVG((kills + assists) / MAX(deaths, 1))
- `avg_damage` = AVG(damage_dealt)
- `avg_gold` = AVG(total_gold)
- `avg_damage_per_min` = AVG(damage_dealt * 60 / match.duration_seconds)
- `avg_gold_per_min` = AVG(total_gold * 60 / match.duration_seconds)
- `mvp_count` = COUNT(player_matches WHERE mvp_badge IS NOT NULL)
- `mvp_rate` = mvp_count / total_games

**Per-Hero (for a player):**
- `games_on_hero` = COUNT(player_matches WHERE hero_id = X)
- `winrate_on_hero` = wins on hero / games on hero
- Most played heroes (top 5 by games)
- Best heroes (top 5 by winrate, min 10 games)

**Team/Squad Analysis:**
- Identify recurring player combinations (e.g., players who often play together)
- Win rate when specific players are on same team
- Best team compositions (hero combinations with high winrate)

---

## 4. Configuration System

### 4.1 Field Extraction Config (`config/field_extraction.yaml`)

Defines which fields to extract and how.

```yaml
# General settings
ocr_engine: "tesseract"
ocr_language: "eng"

# Field definitions
fields:
  # Text fields
  player_name:
    enabled: true
    type: text
    ocr_config: "text"
    required: true
    column_key: "player_name"
  
  # Integer fields
  kills:
    enabled: true
    type: integer
    ocr_config: "digits"
    required: true
    column_key: "kills"
    validation:
      min: 0
      max: 100
  
  deaths:
    enabled: true
    type: integer
    ocr_config: "digits"
    required: true
    column_key: "deaths"
    validation:
      min: 0
      max: 100
  
  assists:
    enabled: true
    type: integer
    ocr_config: "digits"
    required: true
    column_key: "assists"
    validation:
      min: 0
      max: 200
  
  total_gold:
    enabled: true
    type: integer
    ocr_config: "digits"
    required: true
    column_key: "total_gold"
    validation:
      min: 0
      max: 50000
  
  # Optional fields (can be disabled)
  jungle_gold:
    enabled: true
    type: integer
    ocr_config: "digits"
    required: false
    column_key: "jungle_gold"
  
  damage_dealt:
    enabled: true
    type: integer
    ocr_config: "digits"
    required: true
    column_key: "damage_dealt"
  
  # Percentage fields
  teamfight_participation:
    enabled: true
    type: percentage
    ocr_config: "percent"
    required: false
    column_key: "teamfight_pct"
    validation:
      min: 0.0
      max: 1.0
  
  # Fields that can be disabled for now
  items:
    enabled: false  # Phase 4 feature
    type: image_array
    note: "Item detection not yet implemented"
```

### 4.2 Column Mapping Config (`config/column_mapping.yaml`)

Defines pixel coordinates for each column.

```yaml
# Reference resolution
reference_resolution:
  width: 1920
  height: 1080

# Row detection settings
rows:
  method: "hough_lines"
  expected_count: 10
  team_split: 5  # First 5 rows = left team, next 5 = right team

# Column definitions (percentage-based for resolution independence)
# Format: x_start and x_end as percentage of image width
columns:
  hero_portrait:
    x_start_pct: 0.02
    x_end_pct: 0.08
    y_offset_pct: 0.0  # Relative to row top
    height_pct: 1.0    # Full row height
  
  player_name:
    x_start_pct: 0.08
    x_end_pct: 0.22
    y_offset_pct: 0.2
    height_pct: 0.6
  
  kills:
    x_start_pct: 0.23
    x_end_pct: 0.27
    y_offset_pct: 0.2
    height_pct: 0.6
  
  deaths:
    x_start_pct: 0.27
    x_end_pct: 0.31
    y_offset_pct: 0.2
    height_pct: 0.6
  
  assists:
    x_start_pct: 0.31
    x_end_pct: 0.35
    y_offset_pct: 0.2
    height_pct: 0.6
  
  total_gold:
    x_start_pct: 0.36
    x_end_pct: 0.42
    y_offset_pct: 0.2
    height_pct: 0.6
  
  jungle_gold:
    x_start_pct: 0.42
    x_end_pct: 0.48
    y_offset_pct: 0.2
    height_pct: 0.6
  
  damage_dealt:
    x_start_pct: 0.55
    x_end_pct: 0.62
    y_offset_pct: 0.2
    height_pct: 0.6
  
  teamfight_pct:
    x_start_pct: 0.70
    x_end_pct: 0.76
    y_offset_pct: 0.2
    height_pct: 0.6

# Match metadata regions
match_metadata:
  match_id:
    x_start_pct: 0.40
    x_end_pct: 0.60
    y_start_pct: 0.05
    y_end_pct: 0.08
  
  duration:
    x_start_pct: 0.45
    x_end_pct: 0.55
    y_start_pct: 0.92
    y_end_pct: 0.96
```

**Key Benefits:**

1. **Resolution Independence** - Percentages work for any resolution
2. **Easy Tuning** - Change coordinates without touching code
3. **Clear Separation** - Non-technical users can update coordinates
4. **Version Control** - Config changes tracked in Git

---

## 5. Processing Queue

**Why Needed:**
- OCR processing takes 5-15 seconds per screenshot
- API should respond immediately, not block on processing
- Handle multiple concurrent uploads

**Technology Options:**

**Option 1: Celery (Recommended)**
- Full-featured task queue
- Supports retries, scheduling, monitoring
- Works with Redis or RabbitMQ as broker

**Option 2: RQ (Redis Queue)**
- Simpler than Celery
- Good for smaller projects
- Redis-only

**Option 3: Background Tasks in FastAPI**
- Built-in simple background tasks
- No external dependencies
- Limited features (no retries, no monitoring)

**Recommended:** Start with FastAPI BackgroundTasks, migrate to Celery if needed.

**Task Flow:**

```python
@app.post("/upload-screenshot")
async def upload_screenshot(
    file: UploadFile,
    background_tasks: BackgroundTasks
):
    # 1. Save file immediately
    match_id = generate_unique_id()
    file_path = save_upload(match_id, file)
    
    # 2. Enqueue processing
    background_tasks.add_task(
        process_screenshot_task,
        match_id=match_id,
        file_path=file_path
    )
    
    # 3. Return immediately
    return {
        "match_id": match_id,
        "status": "processing",
        "poll_url": f"/match/{match_id}"
    }
```

---

## 6. Handling Multiple Screenshots per Match

Some game views show different tabs (overall stats, damage breakdown, farm details).

**Strategy:**

### Option A: Single Upload with Tab Indicator

```python
POST /upload-screenshot
{
    "tab": "overview" | "damage" | "farm",
    "match_id": "optional_existing_match_id"
}
```

- First upload creates match
- Subsequent uploads with same `match_id` append data
- Merge logic combines data from all tabs

### Option B: Batch Upload

```python
POST /upload-screenshots
{
    "files": [overview.png, damage.png, farm.png]
}
```

- Process all tabs together
- Return single match record

**Recommended:** Option A for flexibility (users can upload tab-by-tab).

**Database Support:**
- Add `screenshots` table to track which tabs were uploaded
- Match record has status: "partial" | "complete"

---

## 7. Error Handling & Logging

### 7.1 OCR Failures

- Log cell images that failed OCR
- Mark field as `null` in database
- Provide admin UI to manually correct
- Track OCR confidence scores

### 7.2 Hero Matching Failures

- Store "Unknown" hero
- Save portrait crop for manual labeling
- Add to hero database after manual review

### 7.3 Logging Strategy

```python
# Use Python logging module with structured logs
import logging

logger = logging.getLogger("squad_stats")

# Log levels:
# DEBUG - Cell crops, OCR raw output
# INFO - Match processed successfully
# WARNING - Low OCR confidence, fallback used
# ERROR - Processing failed entirely
```

---

## 8. Security Considerations

1. **Authentication**
   - API key required for uploads
   - Rate limiting: 10 uploads per minute per key
   - Discord bot gets dedicated API key

2. **Input Validation**
   - Max file size: 10MB
   - Allowed formats: PNG, JPG
   - Image dimension limits: 800x600 to 4K

3. **SQL Injection**
   - Use SQLAlchemy ORM (parameterized queries)
   - Never construct raw SQL from user input

4. **Privacy**
   - Player names are public (from game)
   - No personal data stored
   - Option to anonymize players if needed

---

## 9. Scalability Considerations

**Current Design:** Single server, handles ~100 uploads/day

**Future Scaling Options:**

1. **Horizontal Scaling**
   - Run multiple API instances behind load balancer
   - Shared PostgreSQL and Redis
   - Upload files to S3 instead of local disk

2. **Processing Workers**
   - Run multiple Celery workers
   - Distribute across machines

3. **Database**
   - PostgreSQL can handle millions of records
   - Add read replicas for queries
   - Partition large tables by date

4. **Caching**
   - Redis cache for player summaries
   - Cache leaderboard results (update every 5 minutes)

---

## 10. Monitoring & Observability

**Metrics to Track:**

- Uploads per day
- Average processing time
- OCR success rate
- API response times
- Database query times
- Queue depth

**Tools:**

- Prometheus + Grafana (metrics)
- Sentry (error tracking)
- ELK stack (log aggregation)

**Health Check Endpoint:**

```python
@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "database": check_db_connection(),
        "queue": check_queue_connection(),
        "disk_space": check_disk_space()
    }
```

---

## Summary

This architecture provides:

✅ **Clear separation of concerns** - Image processing, storage, API  
✅ **Configurability** - Field extraction driven by YAML  
✅ **Testability** - Each phase independently verifiable  
✅ **Scalability** - Queue-based processing, horizontal scaling ready  
✅ **Maintainability** - Clean code structure, comprehensive documentation  
✅ **Production-ready** - Error handling, logging, monitoring  

The phased implementation plan (Phase 1 → 2 → 3) ensures each component can be validated before moving to the next, reducing risk and enabling rapid iteration.
