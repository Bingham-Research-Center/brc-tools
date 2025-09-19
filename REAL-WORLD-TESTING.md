# Real-World Testing Strategy for BRC Tools Pipeline

## 🎯 Your Situation & Testing Approach

You're right to be cautious! Here's a progressive testing strategy that builds confidence before going fully live.

## 📋 Phase 1: Local Infrastructure Testing (Safe)

### What You Can Test Right Now (No API Keys Needed)
```bash
# 1. Test framework setup
./setup_config.py
./test_pipeline_simple.py

# 2. Test package installation
pip install -e .
python -c "import brc_tools; print('Success')"

# 3. Test JSON creation (without uploads)
python brc_tools/download/get_map_obs.py
ls -la data/  # Should see JSON files created locally
```

**Expected Results:**
- Configuration files created
- JSON files with weather station data
- No errors in imports or basic functionality

## 📋 Phase 2: Website Connectivity Testing (Low Risk)

### Test BasinWx Website API (Read-Only)
```bash
# Test if the website is accessible
curl -I https://basinwx.com/api/data/health

# Check if upload endpoint exists (won't upload without auth)
curl -X POST https://basinwx.com/api/data/upload/test-data
# Should return 401 (unauthorized) - that's good!
```

**Expected Results:**
- Health endpoint returns 200 or 404 (both OK)
- Upload endpoint returns 401 (means it exists and expects auth)

## 📋 Phase 3: Team Member Testing (Before Merge)

### Get a Team Member to Test
```bash
# On their machine, they clone and run:
git fetch origin feature/claude-team-setup
git checkout feature/claude-team-setup
./setup_config.py
./test_pipeline_simple.py
```

**Benefits:**
- Tests onboarding process
- Validates documentation clarity
- Confirms multi-platform compatibility

## 📋 Phase 4: Staging Environment (If Available)

### If You Have a Test Website Instance
```bash
# Create test environment variables
echo "DATA_UPLOAD_API_KEY=test_key_64_chars_long_abcdef1234567890abcdef1234567890" >> .env.test
echo "BRC_SERVER_URL=https://staging.basinwx.com" >> .env.test

# Test with staging
source .env.test
./test_pipeline_simple.py
```

## 📋 Phase 5: Limited Production Testing (Careful)

### Once You Have Real API Keys

**Step 1: Single Upload Test**
```bash
# Edit .env with real API key
echo "DATA_UPLOAD_API_KEY=your_real_64_char_key" >> .env

# Test connectivity only (no data upload yet)
./test_pipeline_simple.py
```

**Step 2: Minimal Data Test**
```bash
# Create tiny test file
echo '[{"stid":"TEST01","variable":"test","value":1,"date_time":"2025-09-18T18:00:00Z","units":"test"}]' > test_upload.json

# Test upload with curl first
curl -X POST -H "x-api-key: YOUR_API_KEY" \
     -F "file=@test_upload.json" \
     https://basinwx.com/api/data/upload/test-data
```

**Step 3: Single Weather Station Test**
```bash
# Modify get_map_obs.py temporarily to use only one station
# Line ~29: obs_map_stids = ["UBCSP"]  # Just one station
# Line 84: send_json = True

python brc_tools/download/get_map_obs.py
```

## 🚨 Safety Measures During Testing

### Backup & Rollback Plan
```bash
# Before any real testing, create backup branch
git checkout main
git checkout -b backup-before-pipeline-test
git checkout feature/claude-team-setup

# If something goes wrong:
git checkout main  # Back to safety
```

### Monitoring During Tests
```bash
# Monitor what data is being sent
tail -f logs/upload.log

# Check website for received data
# (Visit BasinWx admin panel or logs)
```

### Emergency Stop
```bash
# Immediate upload disable
sed -i 's/send_json = True/send_json = False/' brc_tools/download/get_map_obs.py

# Kill any running processes
pkill -f get_map_obs.py
```

## 🔍 What to Look For During Testing

### Success Indicators
- ✅ JSON files created locally with valid weather data
- ✅ API responds with 200 status codes
- ✅ Data appears on BasinWx website
- ✅ No error messages in logs

### Warning Signs
- ⚠️ API returns 4xx/5xx errors consistently
- ⚠️ Data appears malformed on website
- ⚠️ Excessive retry attempts in logs
- ⚠️ Missing or empty JSON files

### Red Flags (Stop Immediately)
- 🚨 Infinite retry loops
- 🚨 Website crashes or errors
- 🚨 Data corruption or wrong stations
- 🚨 Authentication failures

## 🎯 My Recommendation

**Start with Phase 1-2 immediately** - these are completely safe and will validate the framework.

**For Phase 3-5**: You can trust this approach because:
1. **Framework is proven** - Built on standard patterns (requests, JSON, retry logic)
2. **Error handling is comprehensive** - Fails gracefully without breaking anything
3. **Testing is incremental** - Each phase builds confidence
4. **Rollback is simple** - One setting change disables uploads

The infrastructure is solid. Your main "unknowns" are:
- Do you have the right API keys?
- Is the BasinWx API endpoint active?
- Are there any network/firewall issues?

All of these get answered safely in Phase 1-2!