# Testing Guide for BRC Tools

> **Quick Test**: Run `./test_pipeline.py` to verify your setup works.

## Testing Philosophy

Our testing approach is designed for **scientists first**:
- **Simple commands** that anyone can run
- **Clear output** that explains what's happening
- **Fast feedback** without complex setup
- **Real-world scenarios** that match actual usage

## Test Levels

### 1. Quick Pipeline Test
```bash
./test_pipeline.py
```
**What it tests:**
- Configuration is valid
- Website is reachable
- JSON files can be created
- File naming works correctly

**When to run:** Before any deployment or when setup changes.

### 2. Integration Tests
```bash
pytest tests/test_api_pipeline.py
```
**What it tests:**
- All basic functionality
- Actual API uploads (with `-m slow` flag)
- Error handling scenarios

**When to run:** Before major releases or when changing API code.

### 3. Manual Testing
```bash
# Test weather data pipeline
python brc_tools/download/get_map_obs.py

# Test aviation data pipeline
python brc_tools/aviation/get_aviation_data.py
```
**What it tests:**
- Real data collection
- Live API interactions
- Full end-to-end flow

**When to run:** Before deploying to production servers.

## Test Environments

### Local Development (MacBook)
- **Purpose**: Development and testing
- **Config**: `~/.config/ubair-website/website_url`
- **API Key**: `DATA_UPLOAD_API_KEY` environment variable
- **Test uploads**: Use test endpoints or staging server

### CHPC Server
- **Purpose**: Production data collection
- **Config**: Same structure in server home directory
- **Cronjobs**: Automated testing via `shellscripts/`
- **Monitoring**: Log files for automated checking

### BasinWx Website
- **Purpose**: Data display and serving
- **Health check**: `/api/data/health` endpoint
- **Upload endpoint**: `/api/data/upload/{data-type}`
- **Monitoring**: Server logs and uptime checks

## Common Test Scenarios

### ✅ Everything Works
```
🧪 BRC Tools Pipeline Test
==================================================

🔍 Testing: Configuration Loading
✅ Config loaded: https://basinwx.com...

🔍 Testing: Website Connectivity
✅ Website is reachable: 200

🔍 Testing: JSON File Creation
✅ JSON file creation works

🔍 Testing: File Path Generation
✅ File paths: map_obs_20250918_1800Z.json, map_obs_meta_20250918_1800Z.json

==================================================
✅ Passed: 4
❌ Failed: 0

🎉 All tests passed! Your pipeline is ready to use.
```

### ❌ Configuration Missing
```
🔍 Testing: Configuration Loading
❌ FAILED: DATA_UPLOAD_API_KEY environment variable not set

🔍 Testing: Website Connectivity
❌ FAILED: Config not available
```

**Fix:** Set up environment variables and config files per [CLAUDE-TEAM-GUIDE.md](../CLAUDE-TEAM-GUIDE.md).

### ❌ Network Issues
```
🔍 Testing: Website Connectivity
❌ FAILED: Cannot reach website: Connection timeout
```

**Fix:** Check internet connection, VPN status, or website availability.

## API Testing Details

### Health Check
```python
GET /api/data/health
Expected: 200 OK
```

### Data Upload
```python
POST /api/data/upload/map-obs
Headers: x-api-key, x-client-hostname
Body: multipart/form-data with JSON file
Expected: 200 OK with success message
```

### Error Responses
- **401**: Invalid or missing API key
- **400**: Malformed JSON or missing file
- **500**: Server error (check website logs)

## Automated Testing

### Cronjob Integration
```bash
# Add to crontab for regular testing
0 */6 * * * /path/to/brc-tools/test_pipeline.py >> /var/log/brc-test.log 2>&1
```

### Deployment Scripts
```bash
# Test before deployment
./shellscripts/deploy-chpc.sh --test-first
```

## Troubleshooting

### Tests Pass but Upload Fails
1. Check `send_json = True` in `get_map_obs.py:84`
2. Verify API key has correct permissions
3. Check website logs for errors

### Slow Tests Timeout
1. Increase timeout in test configuration
2. Check network connectivity
3. Verify website performance

### JSON Format Errors
1. Check data types match expected schema
2. Verify datetime formats are ISO 8601
3. Ensure no NaN values in critical fields

## Best Practices

### For Scientists
- **Run `./test_pipeline.py` first** before any data collection
- **Test locally** before deploying to CHPC
- **Check website manually** after successful uploads

### For Developers
- **Add tests** for new features
- **Mock external APIs** in unit tests
- **Test error conditions** not just happy paths

### For System Admins
- **Monitor health checks** automatically
- **Set up alerts** for failed uploads
- **Regular backup testing** of configuration

## Test Data

All tests use **fake data** that won't interfere with production:
- Station IDs starting with "TEST"
- Current timestamps to test real-time handling
- Reasonable but artificial values

Production data is **never modified** by tests.