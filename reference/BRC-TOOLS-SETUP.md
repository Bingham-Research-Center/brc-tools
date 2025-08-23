# Question and Answer to set up `brc-tools` with knowledge base 

### Original initialisation summary

I’ve set up your Claude Code environment with:

  Created Files:

- CLAUDE.md - Comprehensive guide for Claude Code interactions with your codebase
- .env.example - Template for environment variables (API keys, paths)
- requirements.txt - Python dependencies list
- pyproject.toml - Modern Python project configuration with ruff/mypy settings
- Updated .gitignore - Comprehensive ignore patterns

  Major Reorganization Suggestions:

- Consolidate AQM code: Move working code from in_progress/aqm/ into brc_tools/models/aqm.py
- Complete stub modules: Implement the empty visualise/verify/ml modules
- Centralize configuration: Create brc_tools/config.py for API endpoints, defaults
- Add error handling: Wrap API calls with retry logic and proper exceptions
- Standardize data pipeline: Create brc_tools/pipeline/ for common fetch→process→push workflows

  Minor Improvements:

- Fix naming inconsistency: Choose "visualize" or "visualise" (not both)
- Add docstrings: Document empty modules with their intended purpose
- Create tests/: Start with simple unit tests for util functions
- Variable mapping: Move the missing variable-mapping.txt file referenced in lookups.py
- Logging: Add structured logging instead of print statements

  Questions for You:

1. What's the target server URL for BasinWX/data uploads?
2. Should I help consolidate the AQM code into the main package?
3. Are you using specific Synoptic/FlightAware API keys I should know about?
4. Which visualization features are highest priority to implement?
5. Should the British/American spelling be standardized? Which do you prefer?

### Human JRL response

We should add goals, corrections, documentation from the “other side” (front end; info on API; etc). We need a science knowledge repository and will eventually create a private `brc-knowledge` markdown-only repository for access by LLMs.

Big picture context:
1. TODOs (usually in-line comments) need collating and put into the appropriate markdown file for Claude Code reference.
2. On that note - do we need an “index” markdown file for Claude Code to more easily branch to find things? I worry the main `claude.md` gets too long. Like a super-level table-of-contents in LLM-optimal manner? However Claude likes it, balanced with human readability and not having too many small files but avoiding massive files.
3. A review of structural efficiency, including the convection we chose of nesting `brc_tools` inside `brc-tools`. I find this difficult to work with at the same time as another package that doesn’t have that higher directory, but the import wouldn’t have worked in python, plus i see people put documentation in the higher, super-parent directory anyway.
4. There is no testing and I don’t like that, but I’ve never tested and the team haven’t. We’d need help. Tests can be complicated when data is going to a website, and we’ll revisit this when I work on current data pipeline documentation.
5. The lookups.py and philosophy of reference material for Python overlaps with a reference base for Claude, so what’s optimal. For example, variables mapping or metadata. How should I format information like that?

Comments:
1. How to structure things? Even as i write this… what is optimal information transfer? I’m a math—stat person and am happy to adapt between numbers and words.
2. Answering a prompt for edits: endure my British English in communication, but always generate American English in code for the good of the team and compatibility with python as a language. I’ll still use it for prose though. it’s up to you as a semi-autonomous AI agent which dialect you prefer for things like commit messages or talking to me.
3. Is my `.gitignore` currently compatible with the fact I like having example data for my schema design and using to test the front-end web-language repo, whose link to this repo I need to document better, I know.
4. Our URL is `www.basinwx.com` but you can also type `basinwx.com` if that helps. It is live and working but no live data is being pushed, and that information will come to help Claude understand what we’re aiming for.

Help:
1. I don’t understand `.env.example` or even a lot about environments outside of using conda; plus I am new to Claude Code. Could you write me a help markdown, following the WORD-WORD.md convention and putting things in the `docs` root folder, for package managing with environments (pip and venv? is that in-built?) and whether this shuts the door on me also using conda or miniforge, as this repo is rather dependent on a lot of science packages.
2. What is ruff and mypy? I don’t understand the content of that block of text, which shows my unfamiliarity with parts of this (things can go in a `SKILL-UNFAMILIARITY.md` due to the suboptimal skills of the team, so help can be given more in those areas, or things put at plainer language?).
3. Explain the centralised configuration idea, as I don’t put packages together usually. i write them for myself. i do want best practices though, and eventually do a proper package.
4. Explain your pipeline stuff in `PIPELINE-SUGGESTIONS.md`.

Answers:
1. Let’s move all the stuff we need into the `aqm` location you suggest, but bear in mind there’s diamonds in the rough within all this work-in-progress code, and I need help combining it all, and some is jupyter notebook format. some isn’t tracked via git and some is. i’m not sure where to hide things or what to track when my git team-mates and AI agents might chip in too. i’ll take suggestions.
2. Visualisation not a big deal yet, but time series and a 2D “matrix” for heatmap generation. This may be done on the website side if using javascript, for instance, so the json of time series may be the last this repo sees of some data.
3. I’m building up the API docs and functions now, and this will help the blocks for the pyramid.


Action Points:
1. Do you have further questions to optimise our paired work?
2. I’m going to give you more about the front-end website codebase, text that Claude Code has made to transfer information.
3. Rename anything that is “visualisation” into “visualization” and similar, unless it is irrelevant prose.
4. Ultimately, anything useful you learn from me in this document, make sure you have access to it.
