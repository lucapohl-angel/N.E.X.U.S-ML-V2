<p align="center">
  <h1 align="center">🎮 N.E.X.U.S-ML</h1>
  <h3 align="center">Neural Extraction for Unified Squads - Mobile Legends</h3>
  <p align="center">
    <strong>AI-Powered Match Statistics Extraction Engine</strong>
  </p>
  <p align="center">
    <img src="https://img.shields.io/badge/Python-3.10+-blue.svg" alt="Python">
    <img src="https://img.shields.io/badge/OpenCV-4.8+-green.svg" alt="OpenCV">
    <img src="https://img.shields.io/badge/Tesseract-OCR-orange.svg" alt="Tesseract">
    <img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License">
  </p>
</p>

---

## 📖 Overview

**N.E.X.U.S-ML** is an intelligent extraction engine that processes Mobile Legends post-game screenshots and converts them into structured JSON data. Using computer vision and OCR technology, it accurately extracts player statistics, hero information, items, and match metrics.

### ✨ Key Features

- 🎯 **High Accuracy OCR** - Custom-tuned text extraction for each screen type
- 🦸 **Hero Recognition** - Template matching for 100+ hero portraits
- ⚔️ **Item Detection** - Identifies equipped items from icon matching
- 📊 **Multi-Screen Support** - Processes 5 different post-game screens
- 🔄 **Clean Pipeline** - Input image → Process → JSON output
- 🚀 **Production Ready** - No file clutter, returns clean data

---

## 🖼️ Supported Screen Types

| Screen | Data Extracted |
|--------|---------------|
| `screen1` | KDA, items, medals, MVP ratings, hero portraits |
| `screen2` | Damage dealt, damage taken, turret damage, teamfight % |
| `screen3` | Gold earned, gold per minute, turret gold |
| `screen4` | Battle spells, participation rates |
| `screen5` | Gold breakdown (total, jungle, kill, minion gold) |

---

## 📁 Project Structure

```
N.E.X.U.S-ML/
│
├── main.py                 # 🚀 Main extraction engine
│
├── app/                    # Core application modules
│   ├── __init__.py
│   ├── core/
│   │   └── field_config.py # Configuration loader
│   └── parser/
│       ├── detector.py     # Player row detection
│       ├── hero_matcher.py # Hero portrait matching
│       ├── item_matcher.py # Item icon matching
│       ├── ocr.py          # Text extraction
│       └── preprocessor.py # Image preprocessing
│
├── config/                 # Screen mapping configurations
│   ├── field_extraction.yaml
│   ├── heroes.yaml
│   ├── screen1_column_mapping.yaml
│   ├── screen2_column_mapping.yaml
│   ├── screen3_column_mapping.yaml
│   ├── screen4_column_mapping.yaml
│   └── screen5_column_mapping.yaml
│
├── heroes/                 # Hero portrait database
│   └── portraits/          # Hero images for matching
│
├── items/                  # Item database
│   ├── icons/              # Item images for matching
│   └── items_metadata_validated.json
│
└── requirements.txt        # Python dependencies
```

---

## 🛠️ Installation

### Prerequisites

- **Python 3.10+**
- **Tesseract OCR** (system installation required)

### Step 1: Install Tesseract OCR

**Windows:**
1. Download from [UB-Mannheim/tesseract](https://github.com/UB-Mannheim/tesseract/wiki)
2. Install to default location: `C:\Program Files\Tesseract-OCR`
3. Add to PATH environment variable

**Linux:**
```bash
sudo apt-get install tesseract-ocr
```

**macOS:**
```bash
brew install tesseract
```

### Step 2: Clone Repository

```bash
git clone https://github.com/yourusername/NEXUS-ML.git
cd NEXUS-ML
```

### Step 3: Create Virtual Environment

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# Linux/macOS
source venv/bin/activate
```

### Step 4: Install Dependencies

```bash
pip install -r requirements.txt
```

---

## 🚀 Usage

### Command Line

```bash
python main.py <screenshot_path> <screentype>
```

**Examples:**

```bash
# Extract KDA and items from screen1
python main.py "match_result.png" screen1

# Extract damage statistics from screen2
python main.py "damage_stats.png" screen2

# Extract gold breakdown from screen5
python main.py "gold_stats.png" screen5
```

### Programmatic API

```python
from main import extract

# Extract data from screenshot
result = extract("screenshot.png", "screen1")

# Access the data
print(result["metadata"]["battle_id"])
print(result["allies"][0]["hero"]["hero_name"])
print(result["enemies"][0]["total_gold"]["value"])
```

---

## 📤 Output Format

The engine returns structured JSON data:

```json
{
  "metadata": {
    "screenshot_path": "match_result.png",
    "screentype": "screen1",
    "timestamp": "2026-01-07T12:00:00",
    "resolution": {"width": 1920, "height": 1080},
    "total_players": 10,
    "ally_count": 5,
    "enemy_count": 5,
    "battle_id": "436609948828842102"
  },
  "allies": [
    {
      "player_number": 1,
      "hero": {
        "hero_id": "Fanny",
        "hero_name": "Fanny",
        "confidence": 0.92
      },
      "items": [...],
      "kills": {"value": 12},
      "deaths": {"value": 3},
      "assists": {"value": 8}
    }
  ],
  "enemies": [...],
  "summary": {
    "heroes_detected": 10,
    "total_items_detected": 54,
    "avg_hero_confidence": 0.89,
    "avg_item_confidence": 0.85
  }
}
```

---

## 🔧 How It Works

### Pipeline Flow

```
┌─────────────┐    ┌──────────────┐    ┌─────────────┐    ┌──────────┐
│  Screenshot │───▶│  Row Detect  │───▶│  OCR + Match│───▶│   JSON   │
│    Input    │    │  (5 players) │    │  (per row)  │    │  Output  │
└─────────────┘    └──────────────┘    └─────────────┘    └──────────┘
```

### Step-by-Step Process

1. **Image Loading** - Load and normalize screenshot to reference resolution
2. **Row Detection** - Detect 5 player rows using color analysis (blue team indicator)
3. **Column Mapping** - Apply screen-specific coordinate mappings
4. **Data Extraction** - For each cell:
   - Hero portraits → Template matching
   - Items → Icon matching with similarity scoring
   - Statistics → Multi-pass OCR with voting
5. **JSON Assembly** - Combine all data into structured output

---

## ⚙️ Configuration

Screen mappings are defined in YAML files under `config/`. Each mapping specifies:

- Column positions (as percentages for resolution independence)
- Y-axis offsets within player rows
- Field types for OCR processing

Example mapping:
```yaml
columns:
  kills:
    x_start_pct: 0.45
    x_end_pct: 0.52
    y_offset_pct: 0.15
    height_pct: 0.35
    description: "Player kills count"
```

---

## 📋 Requirements

```
opencv-python>=4.8.0
numpy>=1.24.0
Pillow>=10.0.0
pytesseract>=0.3.10
PyYAML>=6.0
```

**System Requirement:** Tesseract OCR must be installed separately.

---

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 🙏 Acknowledgments

- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) - Open source OCR engine
- [OpenCV](https://opencv.org/) - Computer vision library
- Mobile Legends: Bang Bang by Moonton

---

<p align="center">
  <strong>Built with ❤️ for the Mobile Legends Community</strong>
</p>
