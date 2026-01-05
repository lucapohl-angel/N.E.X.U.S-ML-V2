# Screenshot Analysis

This document analyzes the actual game screenshots to determine exact column positions and data extraction requirements.

## Screenshot Set Overview

Based on the provided screenshots, we have **4 different tabs** showing the same match:

### 1. Overall Tab (Image 1 & 5)
**Columns visible:**
- Hero portrait (circular avatar with hero face)
- Player name (e.g., "im too good 4 ranked", "FVL SLASH", "Deepling")
- Total Gold
- Jungle Gold
- Kill Gold
- Minion Gold
- Percentage bars below each gold value

### 2. Equipment Tab (Image 2)
**Columns visible:**
- Hero portrait
- Player name
- K/D/A stats (e.g., "4 0 18", "12 4 7")
- 6 item slots (circular item icons)
- MVP badge/score (gold crossed swords icon with number like "10.9")
- Additional numeric stats next to items

### 3. DPS Tab (Image 3)
**Columns visible:**
- Hero portrait
- Player name
- Hero Damage
- Turret Damage
- Damage Taken
- Teamfight Participation
- Percentage bars below each value

### 4. Team Tab (Image 4)
**Columns visible:**
- Hero portrait
- Player name
- Teamfight Participation
- Crowd Control
- Healing & Shields
- Damage Taken
- Percentage bars below each value

## Key Layout Features

### Fixed Elements Across All Tabs

**Top Section:**
- Score: "37" (left, blue) - "VICTORY" - "15" (right, red)
- Duration: "16:14" (top right corner)

**Bottom Section:**
- BattleID: "4999977047029505564" (bottom left)
- Tab buttons: Equipment, Overall, DPS, Team, Farm (bottom center)
- Quit button (bottom right)

### Player Row Structure

**IMPORTANT**: Only the **blue team (left side, 5 players)** stats are extracted. Red team is ignored.

Each blue team player row contains:
- **Left column**: Hero portrait (~80-100px circular image)
- **Next to portrait**: Player name (variable length, can overflow)
- **Hero level**: Small number overlaid on portrait (e.g., "15", "13")
- **Country flag**: Small flag icon next to portrait (UK, Brazil, Germany, Japan)
- **Rank badge**: Icon next to player name (showing rank/tier)
- **Multiple stat columns**: Varies by tab
- **Percentage bars**: Color-coded bars below numeric values

### Team Separation

- **Left team (Blue)**: Rows 1-5, darker blue background
- **Right team (Red)**: Rows 6-10, darker red background
- Clear visual separator between teams

## Annotated Screenshot Analysis (Image 6)

The red boxes in the annotated image show the column boundaries for the **Overall tab (Gold statistics)**:

### Measured Column Positions (approximate percentages from left edge):

**Left Team Columns:**
1. **Hero Portrait**: 2% - 8%
2. **Player Name**: 8% - 22% (wide to accommodate long names)
3. **Total Gold**: 22% - 28%
4. **Jungle Gold**: 28% - 34%
5. **Kill Gold**: 34% - 40%
6. **Minion Gold**: 40% - 46%

**Right Team Columns:**
(Mirror layout, starting around 51% from left)
1. **Total Gold (right)**: 53% - 59%
2. **Jungle Gold (right)**: 59% - 65%
3. **Kill Gold (right)**: 65% - 71%
4. **Minion Gold (right)**: 71% - 77%
5. **Player Name (right)**: 77% - 88%
6. **Hero Portrait (right)**: 92% - 98%

### Row Positions (approximate percentages from top):

**Blue Team Only (Left Side):**
- **Header Row**: 13% - 15%
- **Player Row 1**: 17% - 24%
- **Player Row 2**: 24% - 31%
- **Player Row 3**: 31% - 38%
- **Player Row 4**: 38% - 45%
- **Player Row 5**: 45% - 52%

**Red Team**: 54% - 89% (IGNORED - not extracted)

## Data Extraction Strategy

### Challenge: Multiple Tabs, One Match

The game provides **4-5 different views** of the same match. We need to decide:

**Option A: Multi-Upload Required**
- Users must upload all 4 tabs
- System merges data from all tabs
- Pros: Complete data
- Cons: More work for user

**Option B: Single Tab Focus**
- Start with just the "Overall" or "Equipment" tab
- Extract core stats (K/D/A, Gold)
- Pros: Simpler upload process
- Cons: Missing some stats

**Option C: Smart Tab Detection**
- Auto-detect which tab is shown
- Extract available fields
- Support partial data
- Pros: Flexible, user-friendly
- Cons: More complex logic

**Recommendation**: Start with **Option C** - detect the active tab by looking at column headers, then extract appropriate fields.

### Tab Detection Method

Look for header text at the top of player area:

- **Overall Tab**: Headers say "Total Gold", "Jungle Gold", "Kill Gold", "Minion Gold"
- **Equipment Tab**: No gold headers, items visible
- **DPS Tab**: Headers say "Hero Damage", "Turret Damage", "Damage Taken"
- **Team Tab**: Headers say "Teamfight Participation", "Crowd Control", "Healing & Shields"
- **Farm Tab**: (Not shown in examples, but likely similar to Overall)

### Critical Fields by Tab

**Equipment Tab (Highest Priority)**
- K/D/A (most important stat)
- Player name
- Hero (from portrait)
- MVP badge + score
- Items (Phase 4)

**Overall Tab**
- Total Gold, Jungle Gold, Kill Gold, Minion Gold
- Gold percentages

**DPS Tab**
- Hero Damage, Turret Damage, Damage Taken
- Teamfight Participation %

**Team Tab**
- Crowd Control, Healing & Shields
- Additional Teamfight Participation and Damage Taken

### Extraction Priority

**Phase 1 - MVP:**
- Player name
- Hero identification
- K/D/A
- Total gold
- Damage dealt

**Phase 2 - Extended:**
- All gold sources
- Damage taken
- Teamfight participation
- MVP badge/score

**Phase 3 - Complete:**
- Crowd control
- Healing & shields
- Turret damage
- Items

## Special Considerations

### 1. Hero Portrait Matching

The hero portraits are **circular images** with distinct artwork. They appear consistent across matches, making template/feature matching viable.

**Heroes visible in screenshots:**
- Row 1 (Left): Female character with dark hair
- Row 2 (Left): Elf-like character with white/blue hair (FVL SLASH)
- Row 3 (Left): Hamster/animal character with goggles (Deepling)
- Row 4 (Left): Male character with dark hair (SHORI)
- Row 5 (Left): Character with orange/brown tones (Oh My Gord)
- Row 1 (Right): Female character (Jesusito)
- Row 2 (Right): Female character with purple/pink (Time's Up, Miwa...)
- Row 3 (Right): Character with red/orange (MOSTER)
- Row 4 (Right): Male character (X.mTraw)
- Row 5 (Right): Character with brown tones (Omimar)

### 2. Player Name Challenges

Player names have **variable lengths**:
- Short: "SHORI" (6 chars)
- Long: "im too good 4 ranked" (21 chars)
- Very long: "Time's Up, Miwa..." (appears truncated with "...")

**Solution**: Allocate wide column region (8%-22% = 14% of width) for names.

### 3. MVP Badge

The MVP badge appears as a **gold crossed-swords icon** with a numeric rating (e.g., 10.9, 10.7, 10.0, 9.3).

Located: 
- **Equipment tab only**
- Between player rows and item display
- Clearly visible gold icon for winners

### 4. Percentage Bars

Colored percentage bars appear below each numeric stat:
- **Red/Pink bars**: Gold percentage, Damage percentage
- **Yellow/Orange bars**: Jungle gold %, Turret damage %
- **Blue bars**: Kill gold %, Damage taken %
- **Green bars**: Minion gold %, Teamfight participation %

These percentages are **additional data points** we can extract.

### 5. Flag Icons

Country flags visible next to hero portraits:
- UK flag (🇬🇧)
- Brazil flag (🇧🇷)
- Germany flag (🇩🇪)
- Japan flag (🇯🇵)
- Spain flag (🇪🇸) (likely)

These could be extracted in Phase 4 for player region tracking.

## Updated Implementation Plan

Based on these screenshots, the implementation should:

1. **Phase 1**: Focus on detecting rows and columns for the **Equipment tab** (has K/D/A + MVP)
2. **Phase 2**: Add OCR for Equipment tab + Overall tab (gold stats)
3. **Phase 3**: Add DPS and Team tab support
4. **Phase 4**: Add item detection and flag extraction

This provides the most value earliest, as K/D/A and gold are the most important stats.
