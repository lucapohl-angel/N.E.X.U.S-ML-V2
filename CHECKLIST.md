# Quick Start Checklist

Copy this checklist and check off items as you complete them.

## Initial Setup

- [ ] Python 3.10+ installed and in PATH
- [ ] Git installed
- [ ] VS Code installed
- [ ] GitHub Copilot extension installed in VS Code
- [ ] Tesseract OCR installed (https://github.com/UB-Mannheim/tesseract/wiki)
- [ ] Tesseract added to system PATH

## Project Setup

- [ ] Opened folder in VS Code: `C:\Users\K0B0i\Documents\Squad STATS`
- [ ] Created virtual environment: `python -m venv venv`
- [ ] Activated venv: `venv\Scripts\Activate.ps1`
- [ ] Installed dependencies: `pip install -r requirements.txt`
- [ ] Copied `.env.example` to `.env`
- [ ] Updated `.env` with Tesseract path
- [ ] Created directories: `uploads/`, `output/`, `logs/`, `heroes/portraits/`, `tests/fixtures/`

## Test Phase 1

- [ ] Saved a screenshot to `tests/fixtures/sample_screenshot.png`
- [ ] Ran: `python tools/phase1_debug_mapping.py tests/fixtures/sample_screenshot.png`
- [ ] Verified 5 rows detected
- [ ] Opened `output/debug_mapping.png`
- [ ] Verified rectangles align with data columns
- [ ] Adjusted `config/column_mapping.yaml` if needed
- [ ] Re-tested until alignment is perfect

## Configuration Tuning

- [ ] Reviewed `config/field_extraction.yaml` - enabled fields correct?
- [ ] Reviewed `config/column_mapping.yaml` - coordinates accurate?
- [ ] Tested with multiple screenshots to verify consistency
- [ ] Documented any resolution-specific adjustments

## Ready for Phase 2

- [ ] Phase 1 working reliably
- [ ] All documentation read
- [ ] GitHub Copilot instructions understood
- [ ] Ready to implement OCR extraction

---

## Phase 2 Checklist (Future)

- [ ] Implement `app/parser/ocr.py`
- [ ] Implement `app/parser/hero_matcher.py`
- [ ] Implement `app/parser/pipeline.py`
- [ ] Create `tools/phase2_debug_ocr.py`
- [ ] Test OCR accuracy on multiple screenshots
- [ ] Tune OCR settings for better accuracy

## Phase 3 Checklist (Future)

- [ ] Implement database models in `app/models/`
- [ ] Create database migrations with Alembic
- [ ] Implement API endpoints in `app/api/`
- [ ] Create `app/main.py` FastAPI application
- [ ] Test API with curl/Postman
- [ ] Document API endpoints

---

## Common Issues - Quick Fixes

### Tesseract not found
```powershell
# Check if installed
tesseract --version

# If not found, add to PATH or set in .env:
TESSERACT_CMD=C:/Program Files/Tesseract-OCR/tesseract.exe
```

### Wrong number of rows detected
```yaml
# Edit config/column_mapping.yaml
row_region:
  y_start_pct: 0.17  # Adjust these
  y_end_pct: 0.52
```

### Rectangles misaligned
```yaml
# Edit config/column_mapping.yaml
player_name:
  x_start_pct: 0.08  # Adjust these
  x_end_pct: 0.22
```

### Can't activate venv
```powershell
# Run this first
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
# Then activate
venv\Scripts\Activate.ps1
```

---

## Quick Commands Reference

```powershell
# Activate environment
venv\Scripts\Activate.ps1

# Run Phase 1 debug
python tools/phase1_debug_mapping.py tests/fixtures/sample_screenshot.png

# Test configuration
python app/core/field_config.py

# Test preprocessor
python app/parser/preprocessor.py tests/fixtures/sample_screenshot.png

# Test detector
python app/parser/detector.py tests/fixtures/sample_screenshot.png

# View output
start output/debug_mapping.png

# Deactivate environment
deactivate
```

---

**Current Status**: Phase 1 Ready to Test ✅  
**Next Step**: Run `python tools/phase1_debug_mapping.py tests/fixtures/sample_screenshot.png`
