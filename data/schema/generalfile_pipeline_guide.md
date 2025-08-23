# Markdown & Large File Pipeline Guide

## **Markdown: Use Same API Pipeline**

### **Standardized Format for Predictable Rendering**

```markdown
# Air Quality Outlook - February 4, 2025

**Risk Level:** MODERATE RISK  
**Issued:** 2025-02-04 12:00 MT  
**Valid:** Through February 6, 2025  

## Executive Summary
Brief paragraph with key points that shows on homepage preview.

## Day 1 (Today) - February 4
Detailed forecast for today...

## Day 2 (Tomorrow) - February 5  
Detailed forecast for tomorrow...

## Day 3 (Wednesday) - February 6
Detailed forecast for day 3...

## Confidence and Uncertainty
Model confidence levels and key uncertainties...
```

### **Python Upload (Same as JSON)**

```python
# In your forecast generation script
def create_forecast_markdown():
    content = f"""# Air Quality Outlook - {date_str}

**Risk Level:** {risk_level}
**Issued:** {issue_time}
**Valid:** Through {valid_time}

## Executive Summary
{executive_summary}

{detailed_forecast}
"""
    
    # Save locally
    markdown_path = generate_markdown_fpath(data_root, "outlook", datetime.now())
    with open(markdown_path, 'w') as f:
        f.write(content)
    
    # Upload same as JSON
    API_KEY, server_url = load_config()
    send_file_to_server(server_url, markdown_path, "forecast-outlook", API_KEY)

def send_file_to_server(server_address, fpath, file_type, API_KEY):
    """Enhanced version that handles any file type"""
    endpoint = f"{server_address}/api/data/upload/{file_type}"
    
    # Determine content type
    content_types = {
        '.json': 'application/json',
        '.md': 'text/markdown', 
        '.pdf': 'application/pdf',
        '.png': 'image/png',
        '.jpg': 'image/jpeg'
    }
    
    file_ext = os.path.splitext(fpath)[1]
    content_type = content_types.get(file_ext, 'application/octet-stream')
    
    with open(fpath, 'rb') as f:
        files = {'file': (os.path.basename(fpath), f, content_type)}
        headers = {'x-api-key': API_KEY}
        
        response = requests.post(endpoint, files=files, headers=headers, timeout=60)
        
    if response.status_code == 200:
        print(f"✅ Uploaded {os.path.basename(fpath)}")
    else:
        print(f"❌ Upload failed: {response.text}")
```

---

## **Large Files: Extend Current API**

### **Website API Modifications**

```javascript
// server/routes/dataUpload.js - extend existing route
const upload = multer({
    storage: storage,
    limits: {
        fileSize: 50 * 1024 * 1024  // 50MB limit (up from 10MB)
    },
    fileFilter: function (req, file, cb) {
        const allowedTypes = [
            'application/json',
            'text/markdown', 
            'application/pdf',
            'image/png',
            'image/jpeg',
            'image/gif'
        ];
        
        if (allowedTypes.includes(file.mimetype) || 
            file.originalname.match(/\.(json|md|pdf|png|jpg|jpeg|gif)$/i)) {
            cb(null, true);
        } else {
            cb(new Error('Unsupported file type'));
        }
    }
});

// Enhanced storage with organized directories
const storage = multer.diskStorage({
    destination: function (req, file, cb) {
        const fileType = req.params.dataType;
        
        // Organize by file type
        const uploadPaths = {
            'map-obs': 'public/data/json',
            'forecast-outlook': 'public/data/outlooks', 
            'weather-charts': 'public/data/images',
            'forecast-reports': 'public/data/reports'
        };
        
        const uploadDir = path.join(process.cwd(), uploadPaths[fileType] || 'public/data');
        
        if (!fs.existsSync(uploadDir)) {
            fs.mkdirSync(uploadDir, { recursive: true });
        }
        
        cb(null, uploadDir);
    },
    filename: function (req, file, cb) {
        cb(null, file.originalname);  // Keep original name for predictability
    }
});
```

### **File Organization Structure**

```
ubair-website/public/data/
├── json/              ← Observation data
│   ├── latest_obs.json
│   └── map_obs_*.json
├── outlooks/          ← Markdown forecasts  
│   ├── outlook_20250204_1200.md
│   └── outlooks_list.json
├── images/            ← Charts, heatmaps, plots
│   ├── ozone_forecast_20250204.png
│   └── weather_model_20250204.png
└── reports/           ← PDFs, large documents
    ├── monthly_summary_202502.pdf
    └── model_verification_202502.pdf
```

### **Python Upload for Different File Types**

```python
# Upload image files (charts, plots)
def upload_forecast_chart(image_path):
    send_file_to_server(server_url, image_path, "weather-charts", API_KEY)

# Upload PDF reports  
def upload_monthly_report(pdf_path):
    send_file_to_server(server_url, pdf_path, "forecast-reports", API_KEY)

# Upload markdown forecasts
def upload_forecast_text(markdown_path):
    send_file_to_server(server_url, markdown_path, "forecast-outlook", API_KEY)
```

### **Website Display Integration**

```javascript
// Display images in forecast pages
function loadForecastCharts() {
    const chartContainer = document.getElementById('forecast-charts');
    
    // List available chart files
    fetch('/public/data/images/')
        .then(response => response.json())
        .then(files => {
            files.filter(f => f.endsWith('.png')).forEach(filename => {
                const img = document.createElement('img');
                img.src = `/public/data/images/${filename}`;
                img.alt = 'Forecast Chart';
                img.style.maxWidth = '100%';
                chartContainer.appendChild(img);
            });
        });
}

// Link to PDF reports
function loadReportLinks() {
    const reportsContainer = document.getElementById('monthly-reports');
    
    fetch('/public/data/reports/')
        .then(response => response.json()) 
        .then(files => {
            files.filter(f => f.endsWith('.pdf')).forEach(filename => {
                const link = document.createElement('a');
                link.href = `/public/data/reports/${filename}`;
                link.textContent = filename.replace(/\.pdf$/, '');
                link.target = '_blank';
                reportsContainer.appendChild(link);
            });
        });
}
```

---

## **Best Practices Summary**

### **✅ Recommended Approach**

1. **Same API for everything** - markdown, images, PDFs all use `/api/data/upload/{type}`
2. **Organized file structure** - different directories by content type
3. **Predictable naming** - use your existing `generate_*_fpath()` functions
4. **Size limits by type**:
   - JSON: 10MB max
   - Markdown: 1MB max  
   - Images: 20MB max
   - PDFs: 50MB max

### **⚠️ Watch Out For**

```python
# Handle upload failures gracefully
def robust_upload(file_path, file_type):
    max_retries = 3
    for attempt in range(max_retries):
        try:
            send_file_to_server(server_url, file_path, file_type, API_KEY)
            return True
        except requests.RequestException as e:
            if attempt == max_retries - 1:
                print(f"❌ Failed after {max_retries} attempts: {e}")
                return False
            time.sleep(2 ** attempt)  # Exponential backoff
```

### **🚀 Future: Auto-generated Content**

```python
# Example: LLM-generated forecast summary
def generate_forecast_summary(model_data):
    prompt = f"""
    Based on this air quality model data: {model_data}
    
    Write a 2-paragraph forecast summary for the public.
    Include risk level and main concerns.
    """
    
    summary = call_llm_api(prompt)
    
    # Create markdown with LLM content
    markdown_content = f"""# AI-Generated Forecast Summary

{summary}

*Generated automatically from model data on {datetime.now().strftime('%Y-%m-%d %H:%M')} MT*
"""
    
    # Upload same as manual forecasts
    save_and_upload_markdown(markdown_content, "ai-summary")
```

---

## **Why This Approach Works**

**✅ Consistency** - Everything uses same upload mechanism  
**✅ Scalability** - Easy to add new file types  
**✅ Simplicity** - No separate pipelines for different content  
**✅ Flexibility** - Can mix manual + automated content  
**✅ Familiar** - Your team already knows this pattern

The key insight: **your API is already generic enough to handle any file type**. Just extend the file filters and organize storage directories appropriately.