# Tech Report vs Code: Contradictions Report
**Generated:** 2025-11-23
**Reviewed:** Clyfar v0.9.5 code vs preprint-clyfar-v0p9 LaTeX manuscript

## Critical Contradictions

### 1. MSLP Unit Mismatch ⚠️
**Impact:** HIGH - Affects actual threshold values

- **LaTeX specification** (manuscript-claude-draft.tex:731-733):
  - Units: **Pascals (Pa)**
  - Low: 101,000 Pa (μ=1) to 101,500 Pa (μ=0)
  - Moderate: Trapezoid 101,000 - 101,500 - 103,000 - 103,500 Pa
  - High: 102,500 Pa (μ=0) to 103,500 Pa (μ=1)

- **Python implementation** (clyfar/fis/v0p9.py:254-259):
  - Units: **Hectopascals (hPa)** (despite docstring claiming "Pa")
  - Low: 1010 hPa to 1015 hPa
  - Moderate: Trapezoid 1010 - 1015 - 1030 - 1035 hPa
  - High: 1025 hPa to 1035 hPa

**Resolution needed:** Verify intended units and update either LaTeX or Python code. Values are 100× different.

### 2. Dubois-Prade Inference Method
**Impact:** LOW - Documentation clarity only

- **LaTeX specification**: Uses **Mamdani** fuzzy inference (line 442) with max-min aggregation
- **Python implementation**: Also uses **Mamdani** (scikit-fuzzy default)
- **Finding**: Dubois & Prade cited only for possibility theory foundations, NOT inference method
- **Note**: User may have expected Dubois-Prade based on earlier discussions, but both docs specify Mamdani

## Confirmed Matches ✓

### Ozone Categories (4 categories)
- **Names**: background, moderate, elevated, extreme ✓
- **Thresholds** (all in ppb):
  - Background: [20, 30, 40, 50] ✓
  - Moderate: [40, 50, 60, 70] ✓
  - Elevated: [50, 60, 75, 90] ✓
  - Extreme: [60, 75, 90, 125] ✓

### Other Input Variables
- **Snow depth**: 60-90 mm transition ✓
- **Wind speed**: 2-4 m/s transition ✓
- **Solar radiation**: Low (200-300), Moderate (200-300-500-700), High (500-700 W/m²) ✓

### Methodology
- **Membership functions**: Trapezoidal (multi-category), piecewise-linear (binary) ✓
- **Fuzzy inference**: Mamdani with max aggregation ✓

## Recommendations

1. **Immediate action**: Resolve MSLP unit discrepancy (Pa vs hPa)
2. **Documentation**: Clarify role of Dubois-Prade (possibility theory only, not inference)
3. **Code comment**: Fix misleading docstring at fis/v0p9.py:57 (says "Pa" but values are hPa)

## Cross-Repo Sync

This report exists in:
- `/Users/johnlawson/WebstormProjects/ubair-website/CONTRADICTIONS-REPORT.md`
- `/Users/johnlawson/PycharmProjects/brc-tools/CONTRADICTIONS-REPORT.md`
- `/Users/johnlawson/PycharmProjects/clyfar/CONTRADICTIONS-REPORT.md`
- `/Users/johnlawson/Documents/GitHub/preprint-clyfar-v0p9/CONTRADICTIONS-REPORT.md`

**Keep synchronized:** Any updates to methodology should trigger updates across all 4 repos.
