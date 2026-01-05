# Squad STATS - Game Statistics Extraction System

A production-grade system for automatically extracting player statistics from game result screenshots, storing them in a database, and exposing them via REST API for Discord bot integration.

## 🎯 Project Overview

This system automates the process of:
1. **Receiving** game result screenshots (from Discord bot or manual upload)
2. **Extracting** all tabular data using computer vision and OCR
3. **Storing** structured match and player statistics in a database
4. **Exposing** data through a REST API for querying and aggregation

## 🏗️ System Architecture

```
┌─────────────────┐
│  Discord Bot    │ ←→ User uploads screenshot
└────────┬────────┘
         │ HTTP POST /upload-screenshot
         ▼
┌─────────────────────────────────────────┐
│         API Gateway (FastAPI)           │
│  - Upload endpoint                      │
│  - Match queries                        │
│  - Player stats                         │
│  - Leaderboard                          │
└────────┬────────────────────┬───────────┘
         │                    │
         ▼                    ▼
┌────────────────┐   ┌────────────────────┐
│ Image Storage  │   │  Processing Queue  │
│ (disk/S3)      │   │  (Celery/RQ)       │
└────────────────┘   └─────────┬──────────┘
                               │
                               ▼
                     ┌─────────────────────┐
                     │  Image Processor    │
                     │  - OpenCV pipeline  │
                     │  - Row detection    │
                     │  - Column extraction│
                     │  - OCR (Tesseract)  │
                     │  - Hero matching    │
                     └──────────┬──────────┘
                                │
                                ▼
                     ┌─────────────────────┐
                     │    Data Service     │
                     │  - Validation       │
                     │  - Normalization    │
                     │  - DB writes        │
                     └──────────┬──────────┘
                                │
                                ▼
                     ┌─────────────────────┐
                     │    PostgreSQL       │
                     │  - matches          │
                     │  - players          │
                     │  - player_matches   │
                     │  - heroes           │
                     └─────────────────────┘
```

## 📊 Data Flow

1. **Screenshot Upload** → API receives image file
2. **Storage** → Save raw image with unique ID
3. **Queue Job** → Push processing task to queue
4. **Preprocessing** → Resize, normalize, enhance contrast
5. **Row Detection** → OpenCV detects player rows (5 per team)
6. **Column Segmentation** → Crop each stat column using configured coordinates
7. **OCR Extraction** → Extract text/numbers from each cell
8. **Hero Identification** → Match hero portrait to database
9. **Data Validation** → Clean and validate extracted data
10. **Database Storage** → Store match + 10 player records
11. **API Response** → Return match ID and summary

## 🗂️ Project Structure

```
Squad STATS/
├── app/
│   ├── api/                    # FastAPI application
│   │   ├── __init__.py
│   │   ├── endpoints/         # API route handlers
│   │   │   ├── upload.py
│   │   │   ├── matches.py
│   │   │   └── players.py
│   │   └── dependencies.py    # DB session, auth, etc.
│   │
│   ├── parser/                # Image processing & OCR
│   │   ├── __init__.py
│   │   ├── preprocessor.py   # Image normalization
│   │   ├── detector.py       # Row/column detection
│   │   ├── ocr.py            # OCR utilities
│   │   ├── hero_matcher.py   # Hero identification
│   │   └── pipeline.py       # Main parsing orchestration
│   │
│   ├── models/               # SQLAlchemy ORM models
│   │   ├── __init__.py
│   │   ├── match.py
│   │   ├── player.py
│   │   └── hero.py
│   │
│   ├── services/             # Business logic
│   │   ├── __init__.py
│   │   ├── match_service.py
│   │   └── stats_service.py
│   │
│   ├── schemas/              # Pydantic schemas for validation
│   │   ├── __init__.py
│   │   ├── match.py
│   │   └── player.py
│   │
│   └── core/                 # Config, DB, utilities
│       ├── __init__.py
│       ├── config.py         # Settings management
│       ├── database.py       # DB connection
│       └── field_config.py   # Field extraction config loader
│
├── config/
│   ├── field_extraction.yaml  # Configurable field definitions
│   ├── column_mapping.yaml    # Column coordinate mappings
│   └── heroes.yaml            # Hero database
│
├── tools/                     # Development & debug scripts
│   ├── phase1_debug_mapping.py    # Visualize row/column detection
│   ├── phase2_debug_ocr.py        # Test OCR extraction
│   ├── phase3_test_api.py         # API testing utilities
│   └── seed_database.py           # Initialize DB with heroes
│
├── tests/
│   ├── test_parser/
│   ├── test_api/
│   └── fixtures/              # Sample screenshots for testing
│
├── migrations/                # Alembic database migrations
│   └── versions/
│
├── heroes/                    # Hero portrait reference images
│   └── portraits/
│
├── uploads/                   # Uploaded screenshot storage
│
├── output/                    # Debug output images
│
├── .github/
│   └── copilot-instructions.md   # GitHub Copilot guidance
│
├── requirements.txt
├── requirements-dev.txt
├── docker-compose.yml
├── Dockerfile
├── .env.example
└── README.md
```

## 🚀 Development Phases

### Phase 1: Image Mapping & Visualization
**Goal:** Validate that row and column detection works correctly

- Implement OpenCV-based row detection
- Configure column boundaries
- Create debug visualization tool
- **Output:** Annotated images showing detected regions

### Phase 2: OCR Processing & Verification
**Goal:** Extract text/numbers and verify accuracy

- Implement Tesseract OCR for each column type
- Add hero portrait matching
- Create validation scripts
- **Output:** JSON with parsed match data

### Phase 3: Database & API Integration
**Goal:** Full backend with storage and retrieval

- Implement database schema
- Create FastAPI endpoints
- Add background processing queue
- **Output:** Working REST API

## 📋 Prerequisites

- Python 3.10+
- Tesseract OCR installed on system
- PostgreSQL 14+ (or SQLite for development)
- VS Code with GitHub Copilot

## 🛠️ Quick Start

See [SETUP.md](docs/SETUP.md) for detailed installation instructions.

```bash
# 1. Create virtual environment
python -m venv venv
venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Install Tesseract OCR (Windows)
# Download from: https://github.com/UB-Mannheim/tesseract/wiki
# Add to PATH

# 4. Configure environment
cp .env.example .env
# Edit .env with your database credentials

# 5. Initialize database
python tools/seed_database.py

# 6. Test Phase 1 - Image mapping
python tools/phase1_debug_mapping.py path/to/screenshot.png

# 7. Test Phase 2 - OCR extraction
python tools/phase2_debug_ocr.py path/to/screenshot.png

# 8. Run API server (Phase 3)
uvicorn app.main:app --reload
```

## 📚 Documentation

- [Architecture Design](docs/ARCHITECTURE.md) - Detailed system design
- [Setup Guide](docs/SETUP.md) - Installation and configuration
- [API Documentation](docs/API.md) - REST endpoint reference
- [Parser Documentation](docs/PARSER.md) - Image processing pipeline
- [Configuration Guide](docs/CONFIGURATION.md) - Field and column config
- [Discord Bot Integration](docs/DISCORD_BOT.md) - Bot integration guide
- [Deployment Guide](docs/DEPLOYMENT.md) - Production deployment

## 🔌 API Endpoints

### Upload Screenshot
```http
POST /upload-screenshot
Content-Type: multipart/form-data

Response: { "match_id": "...", "status": "processing" }
```

### Get Match Details
```http
GET /match/{match_id}

Response: { "match": {...}, "players": [...] }
```

### Player Summary
```http
GET /player/{player_name}/summary

Response: { "total_games": 150, "winrate": 0.58, "avg_kda": 3.2, ... }
```

### Leaderboard
```http
GET /leaderboard/damage?period=30d&limit=10

Response: [{ "player": "...", "avg_damage": 45000, ... }]
```

## 🧪 Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=app tests/

# Test specific phase
pytest tests/test_parser/test_phase1_detection.py
```

## 🐳 Docker Deployment

```bash
# Build and run all services
docker-compose up -d

# View logs
docker-compose logs -f api

# Access API at http://localhost:8000
```

## 🤝 Discord Bot Integration

Your Discord bot should:

1. **Upload Screenshot:**
   ```python
   async def upload_screenshot(file_bytes: bytes):
       files = {"file": ("screenshot.png", file_bytes)}
       response = await http_client.post(
           "http://api-url/upload-screenshot",
           files=files
       )
       return response.json()
   ```

2. **Query Player Stats:**
   ```python
   async def get_player_stats(player_name: str):
       response = await http_client.get(
           f"http://api-url/player/{player_name}/summary"
       )
       return response.json()
   ```

See [docs/DISCORD_BOT.md](docs/DISCORD_BOT.md) for complete integration guide.

## 🔧 Configuration

The system uses two main configuration files:

### `config/field_extraction.yaml`
Define which fields to extract:
```yaml
fields:
  player_name:
    enabled: true
    type: text
    ocr_config: "text"
  
  total_gold:
    enabled: true
    type: integer
    ocr_config: "digits"
```

### `config/column_mapping.yaml`
Define column pixel coordinates:
```yaml
resolution: 1920x1080
columns:
  hero_portrait:
    x_start_pct: 0.05
    x_end_pct: 0.10
  player_name:
    x_start_pct: 0.10
    x_end_pct: 0.25
```

## 📈 Roadmap

- [ ] Phase 1: Image mapping validation
- [ ] Phase 2: OCR extraction
- [ ] Phase 3: Backend API
- [ ] Hero portrait database expansion
- [ ] Item icon detection (Phase 4)
- [ ] Team composition analysis
- [ ] Advanced analytics dashboard
- [ ] Mobile app integration

## 🤖 GitHub Copilot Integration

This project includes detailed instructions for GitHub Copilot in [.github/copilot-instructions.md](.github/copilot-instructions.md).

When working on this project, Copilot will understand:
- The three-phase development approach
- Field configuration system
- Parser pipeline architecture
- Database schema relationships
- API endpoint patterns

## 📝 License

MIT

## 🙋 Support

For issues, questions, or contributions, see the [docs/](docs/) folder or open an issue.
