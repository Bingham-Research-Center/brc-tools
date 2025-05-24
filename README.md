### `brc-tools` - Bingham Research Center (python) Tools

Functions that are general to many packages used by the Bingham Research Center. The wishlist includes:

- [x] Basic setup
- [ ] Visualisations 
- [ ] Data download 
  - NWP
  - Observations
  - Satellites
- [ ] Verification/evaluation
- [ ] Filtering methods for time series
- [ ] Machine learning tools for optimising a model 
- [ ] Develop a coding guideline (e.g., consistency in British or American English for a bloody start)

There should be an easy entry point for acquiring data. "If it is saved to disc, load it; else, download it and save it for next time. Either way, show me documentation of its structure". This makes it quick to ask, how is ozone correlated with wind direction at Vernal, and there is a fixed method of, say, subsetting or post-processing data before saving so it is obvious what is being loaded. Documentation about data structure and function use must be written quickly; consider tests and also little dataframes with the data format and for testing itself. 

John Lawson and Michael Davies, Bingham Research Center, 2025 

This is a list of files that are prime for putting into functions from notebooks.

- [AQM 8-hr ozone in parallel](gemini_parallel-aqm.py)