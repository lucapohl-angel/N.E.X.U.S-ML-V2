# Setup Guide - Squad STATS

This guide walks you through setting up the Squad STATS project on your local machine step-by-step.

## Prerequisites

Before you begin, ensure you have:

- **Windows 10/11** (or Linux/Mac with minor adjustments)
- **Python 3.10 or higher** installed
- **VS Code** with GitHub Copilot installed
- **Git** for version control
- Basic command line knowledge

---

## Step 1: Install System Dependencies

### 1.1 Python

Check if Python is installed:

```powershell
python --version
```

If not installed, download from: https://www.python.org/downloads/

**Important**: During installation, check "Add Python to PATH"

### 1.2 Tesseract OCR

Tesseract is the OCR engine that reads text from images.

**Windows:**
1. Download installer from: https://github.com/UB-Mannheim/tesseract/wiki
2. Run the installer (`tesseract-ocr-w64-setup-5.3.3.20231005.exe` or similar)
3. Install to default location: `C:\Program Files\Tesseract-OCR`
4. **Add to PATH**:
   - Search "Environment Variables" in Windows
   - Edit "Path" under System Variables
   - Add: `C:\Program Files\Tesseract-OCR`
   - Click OK

**Verify installation:**

```powershell
tesseract --version
```

You should see version information.

**Linux (Ubuntu/Debian):**

```bash
sudo apt-get update
sudo apt-get install tesseract-ocr
```

**macOS:**

```bash
brew install tesseract
```

### 1.3 PostgreSQL (Optional - for production)

For development, we'll use SQLite (built into Python). For production:

**Windows:**
1. Download from: https://www.postgresql.org/download/windows/
2. Run installer
3. Remember your postgres user password
4. Default port: 5432

**Linux:**

```bash
sudo apt-get install postgresql postgresql-contrib
```

**macOS:**

```bash
brew install postgresql
```

---

## Step 2: Clone and Setup Project

### 2.1 Navigate to Project Folder

Open PowerShell and navigate to your project:

```powershell
cd "C:\Users\K0B0i\Documents\Squad STATS"
```

### 2.2 Create Virtual Environment

A virtual environment keeps project dependencies isolated.

```powershell
python -m venv venv
```

This creates a `venv` folder.

### 2.3 Activate Virtual Environment

**Windows PowerShell:**

```powershell
venv\Scripts\Activate.ps1
```

If you get an error about execution policy:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

Then try activating again.

**Windows Command Prompt:**

```cmd
venv\Scripts\activate.bat
```

**Linux/macOS:**

```bash
source venv/bin/activate
```

You should see `(venv)` in your prompt.

### 2.4 Install Python Dependencies

```powershell
pip install --upgrade pip
pip install -r requirements.txt
```

This will install:
- OpenCV (image processing)
- pytesseract (OCR)
- FastAPI (web framework)
- SQLAlchemy (database)
- and all other dependencies

For development tools:

```powershell
pip install -r requirements-dev.txt
```

---

## Step 3: Configure Environment

### 3.1 Create .env File

Copy the example environment file:

```powershell
copy .env.example .env
```

### 3.2 Edit .env File

Open `.env` in VS Code and update:

```env
# For development, use SQLite
DATABASE_URL=sqlite:///./squad_stats.db

# Generate a secret key
SECRET_KEY=<press Tab, let Copilot suggest or use: python -c "import secrets; print(secrets.token_hex(32))">

# Tesseract path (Windows example)
TESSERACT_CMD=C:/Program Files/Tesseract-OCR/tesseract.exe

# Or if in PATH, just:
# TESSERACT_CMD=tesseract

# Development settings
ENVIRONMENT=development
LOG_LEVEL=DEBUG
```

Save the file.

### 3.3 Verify Tesseract Path

Test if pytesseract can find Tesseract:

```powershell
python -c "import pytesseract; print(pytesseract.get_tesseract_version())"
```

If this fails, update `TESSERACT_CMD` in `.env`.

---

## Step 4: Create Necessary Directories

```powershell
# Create directories if they don't exist
New-Item -ItemType Directory -Force -Path uploads
New-Item -ItemType Directory -Force -Path output
New-Item -ItemType Directory -Force -Path logs
New-Item -ItemType Directory -Force -Path heroes\portraits
New-Item -ItemType Directory -Force -Path tests\fixtures
```

---

## Step 5: Test Phase 1 - Image Mapping

This phase tests that the system can detect rows and columns correctly.

### 5.1 Place Test Screenshots

Save one of your provided screenshots to:

```
tests/fixtures/sample_screenshot.png
```

### 5.2 Run Phase 1 Debug Tool

```powershell
python tools/phase1_debug_mapping.py tests/fixtures/sample_screenshot.png
```

**Expected output:**

```
====================================
PHASE 1: IMAGE MAPPING DEBUG TOOL
====================================

Processing: tests/fixtures/sample_screenshot.png

1. Loading configuration...
   Reference resolution: 1920x1080
   Expected rows: 5

2. Loading and normalizing image...
   Image size: 1920x1080

3. Detecting player rows (blue team only)...
   ✓ Detected 5 rows

4. Drawing debug visualizations...
   ✓ Saved annotated image to: output/debug_mapping.png

============================================================
DETECTION SUMMARY
============================================================

✓ Detected 5 player rows (expected: 5 for blue team)

Row positions (Y coordinates):
  Row 1: y= 183 to  260 (height: 77px)
  Row 2: y= 260 to  337 (height: 77px)
  Row 3: y= 337 to  414 (height: 77px)
  Row 4: y= 414 to  491 (height: 77px)
  Row 5: y= 491 to  561 (height: 70px)

[... column listings ...]

============================================================

✓ Phase 1 complete!
```

### 5.3 Verify Mapping

Open `output/debug_mapping.png` in an image viewer.

**What to look for:**
- Green horizontal lines between each of the 5 blue team rows
- Colored rectangles around each data column
- Rectangles should align perfectly with the data (hero portraits, names, stats)

**If misaligned:**

1. Open `config/column_mapping.yaml`
2. Adjust the percentage values for misaligned columns
3. Re-run Phase 1 tool
4. Repeat until perfect

Example adjustment:

```yaml
# If player names are cut off on the right
player_name:
  x_start_pct: 0.08
  x_end_pct: 0.24  # Increased from 0.22
```

---

## Step 6: Setup Database (Phase 3)

We'll skip Phase 2 (OCR) for now and setup the database structure.

### 6.1 Initialize Database

```powershell
# This will be created in Phase 3
# For now, just verify SQLite works
python -c "import sqlite3; print('SQLite OK')"
```

### 6.2 Create Hero Database

Add hero portrait images to `heroes/portraits/` and update `config/heroes.yaml`.

For testing, you can use placeholder data.

---

## Step 7: Verify Installation

### 7.1 Run Configuration Test

```powershell
python app/core/field_config.py
```

Expected output:

```
Reference resolution: 1920x1080

Enabled player fields (XX):
  - player_name: text (player_name)
  - hero_portrait: image_match (hero_portrait)
  - kills: integer (kills)
  [...]

Enabled match fields (XX):
  - match_id: text (match_id)
  [...]

Columns (XX):
  - hero_portrait: x=[2.0%, 8.0%]
  [...]

Heroes loaded: 5
```

### 7.2 Test Preprocessor

```powershell
python app/parser/preprocessor.py tests/fixtures/sample_screenshot.png
```

Should output:

```
Loading: tests/fixtures/sample_screenshot.png
Normalized size: 1920x1080
Saved to: output/preprocessed.png
```

### 7.3 Test Detector

```powershell
python app/parser/detector.py tests/fixtures/sample_screenshot.png
```

Should output:

```
Loading: tests/fixtures/sample_screenshot.png
Detecting rows...
Detected 5 rows:
  Row 1: y=183 to 260 (height: 77px)
  Row 2: y=260 to 337 (height: 77px)
  [...]

Testing column crop (player_name from row 1)...
  Cropped region size: 269x38
  Saved to: output/test_crop.png
```

---

## Step 8: Next Steps

### ✅ Phase 1 Complete

You now have:
- All dependencies installed
- Configuration files set up
- Row and column detection working
- Debug tools functional

### 🚧 Next: Phase 2 (OCR Implementation)

To continue to Phase 2:

1. **Implement OCR module** (`app/parser/ocr.py`)
2. **Create Phase 2 debug tool** (`tools/phase2_debug_ocr.py`)
3. **Test OCR extraction** on your screenshots
4. **Tune OCR settings** for better accuracy

### 🚧 Then: Phase 3 (Backend API)

After Phase 2:

1. **Create database models** (`app/models/`)
2. **Implement API endpoints** (`app/api/`)
3. **Setup FastAPI server** (`app/main.py`)
4. **Test API** with curl or Postman

---

## Troubleshooting

### Issue: "python: command not found"

**Solution:** Python not in PATH. Reinstall Python and check "Add to PATH" option.

### Issue: "tesseract: command not found"

**Solution:** 
1. Verify Tesseract is installed
2. Add Tesseract folder to PATH
3. Set `TESSERACT_CMD` in `.env` to full path

### Issue: "ModuleNotFoundError: No module named 'cv2'"

**Solution:** OpenCV not installed. Run:

```powershell
pip install opencv-python
```

### Issue: Phase 1 detects wrong number of rows

**Solution:**

1. Open `config/column_mapping.yaml`
2. Adjust `row_region` percentages:
   ```yaml
   row_region:
     y_start_pct: 0.17  # Try adjusting these
     y_end_pct: 0.52
   ```
3. Re-run Phase 1 tool

### Issue: Rectangles don't align with data

**Solution:**

1. Your screenshot might have different resolution
2. Check actual resolution: right-click image → Properties → Details
3. Adjust column percentages in `column_mapping.yaml`
4. The system auto-scales to reference resolution, but percentages may need tweaking

### Issue: Permission denied when activating venv

**Solution (Windows):**

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

Then try activating again.

---

## Getting Help

1. **Check logs**: Look in `logs/squad_stats.log` (if enabled)
2. **Debug output**: All tools save images to `output/` folder
3. **GitHub Copilot**: Ask Copilot for help in VS Code
4. **Documentation**: See `docs/` folder for detailed guides

---

## Summary

You've successfully set up:

✅ Python virtual environment  
✅ All dependencies installed  
✅ Tesseract OCR configured  
✅ Configuration files created  
✅ Phase 1 debug tools working  
✅ Ready for Phase 2 implementation  

**Next command to run:**

```powershell
python tools/phase1_debug_mapping.py tests/fixtures/sample_screenshot.png
```

Happy coding! 🚀
