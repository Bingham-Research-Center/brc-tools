# Claude Code Workflow Guide

## 🚀 Quick Start for Developers

This guide helps both humans and Claude Code work together effectively on the BRC Tools project.

---

## For Your First Session with Claude Code

### 1. Start Here (Context Files)
Claude Code reads these automatically to understand your project:
```
CLAUDE.md          → Project overview & conventions
CLAUDE-INDEX.md    → Navigation to all knowledge
WISHLIST-TASKS.md  → Current priorities
```

### 2. Tell Claude Code What You Need
Be specific about your goal:
```
❌ "Fix the data pipeline"
✅ "The station COOPDINU1 isn't showing data on the website map"

❌ "Improve the code"  
✅ "Add retry logic to the Synoptic API calls in download_funcs.py"
```

### 3. Claude Code Will Use These Tools
- **Read files** to understand context
- **Search** for relevant code
- **Edit** files precisely
- **Run commands** to test changes
- **Track progress** with todo lists

---

## 📥 Input: How to Give Information to Claude Code

### Best Practices

#### 1. Persistent Knowledge → `reference/` folder
```
reference/
├── PYTHON-DEVELOPER-TODO.md    # Specific tasks
├── BRC-TOOLS-SETUP.md         # Q&A context
└── FLIGHTAWARE-API.md          # API documentation
```
These survive between sessions!

#### 2. Current Tasks → `WISHLIST-TASKS.md`
```markdown
- [ ] Add retry logic to API calls
- [ ] Fix PM_25_concentration variable name
```
Claude Code checks this for priorities.

#### 3. Inline TODOs in Code
```python
# TODO: Add exponential backoff here
# TODO: Validate API key before making request
```
Claude Code finds these during exploration.

#### 4. Direct Instructions
```
"Please add the three missing COOP stations to lookups.py"
"Create a config.py file to centralize our settings"
```

### What NOT to Do
- ❌ Long unstructured text dumps
- ❌ Information only in commit messages  
- ❌ Files over 1000 lines (Claude may not read fully)
- ❌ Vague requests without context

---

## 📤 Output: What Claude Code Creates (Useful for Humans Too!)

### Documentation Claude Code Generates

#### 1. `CLAUDE-INDEX.md` - Master Navigation
- Quick links to everything
- Current priorities
- Key commands
- Useful for onboarding new team members!

#### 2. `docs/` folder - Team Knowledge
```
docs/
├── ENVIRONMENT-SETUP.md      # How to set up Python env
├── PIPELINE-ARCHITECTURE.md  # How data flows
└── API-REFERENCE.md          # API documentation
```
These help your whole team, not just Claude!

#### 3. `WISHLIST-TASKS.md` - Living Todo List
- Prioritized tasks
- Complexity levels
- Dependencies mapped
- Great for project management!

#### 4. Code Comments & Docstrings
Claude Code adds helpful documentation:
```python
def retry_with_backoff(func, max_attempts=3):
    """Execute function with exponential backoff retry.
    
    Args:
        func: Function to execute
        max_attempts: Maximum retry attempts (default: 3)
    
    Returns:
        Function result if successful
        
    Raises:
        Last exception if all retries fail
    """
```

---

## 🔄 Typical Workflow

### Starting a New Feature
1. **Human**: "I need to add aviation data from FlightAware"
2. **Claude Code**: 
   - Creates todo list
   - Explores existing code
   - Asks clarifying questions
   - Implements step by step
   - Updates documentation

### Fixing a Bug
1. **Human**: "Station COOPDINU1 shows 'Data missing' on the map"
2. **Claude Code**:
   - Checks if station is in lookups.py
   - Verifies API calls include it
   - Tests data pipeline
   - Fixes issue
   - Documents the fix

### Code Review/Improvement
1. **Human**: "Review the AQM code in in_progress/ and consolidate it"
2. **Claude Code**:
   - Analyzes all AQM files
   - Identifies common patterns
   - Creates consolidated module
   - Preserves working functionality
   - Documents changes

---

## 💡 Pro Tips

### 1. Let Claude Code Track Progress
It automatically creates todo lists for complex tasks. This helps both of you stay organized.

### 2. Review Generated Documentation
The docs Claude creates are meant for humans too! Check `docs/` and `WISHLIST-TASKS.md` regularly.

### 3. Be Specific About Conventions
```
"Use American English spelling"
"Prefer Polars over Pandas"
"Follow our WORD-WORD.md naming for docs"
```

### 4. Provide Examples
```
"The JSON should look like this: {example}"
"Follow the same pattern as download_funcs.py"
```

### 5. Ask for Explanations
```
"Explain what ruff and mypy do"
"Why use exponential backoff?"
```

---

## 🎯 Where to Start Each Session

### For New Features
1. Check `WISHLIST-TASKS.md` for priorities
2. Tell Claude Code which feature to work on
3. Provide any additional context needed

### For Bug Fixes
1. Describe the bug specifically
2. Share error messages if available
3. Point to relevant files if known

### For Code Review
1. Point to specific files/directories
2. Explain what concerns you
3. Ask for specific improvements

### For Documentation
1. Ask Claude to document existing code
2. Request guides for team members
3. Have it create examples

---

## 📊 What's Most Useful for Humans

### Claude Code's Best Outputs for Your Team

1. **Environment Setup Guides** (`docs/ENVIRONMENT-SETUP.md`)
   - Perfect for onboarding
   - Explains venv, pip, conda
   - Troubleshooting included

2. **Architecture Documentation** (`docs/PIPELINE-ARCHITECTURE.md`)
   - Shows data flow
   - Explains design decisions
   - Maps dependencies

3. **Task Management** (`WISHLIST-TASKS.md`)
   - Project roadmap
   - Priority tracking
   - Complexity estimates

4. **API Integration Code**
   - Working examples
   - Error handling
   - Retry logic

5. **Test Suites**
   - Unit tests
   - Integration tests
   - Test documentation

---

## 🔧 Maintenance

### Keep These Updated
- `CLAUDE.md` - When project scope changes
- `WISHLIST-TASKS.md` - Mark completed tasks
- `reference/*` - Add new specifications

### Regular Reviews
- Check generated documentation for accuracy
- Update priorities in WISHLIST-TASKS.md
- Archive completed reference docs

---

## 🆘 Getting Help

### If Claude Code seems confused:
1. Check if it has the right context files
2. Be more specific about your request
3. Point to example code that's similar
4. Break complex tasks into steps

### If output isn't useful:
1. Ask for different format
2. Request more explanation
3. Ask for examples
4. Specify your team's skill level

---

## Example First Message to Claude Code

```
"Hi! I'm working on the BRC Tools project. Please check CLAUDE.md and 
WISHLIST-TASKS.md to understand the project. Today I want to work on 
adding retry logic to our API calls. The code is in brc_tools/download/. 
Please use exponential backoff and add proper logging."
```

---

*Remember: Claude Code's documentation is designed to help your whole team, not just the AI. Review and share the generated guides!*