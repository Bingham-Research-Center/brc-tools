# Basin Aviation Airports Reference

## Primary Airports

### Uinta Basin Core
| Airport Name | ICAO | IATA | FAA LID | Coordinates | Elevation |
|-------------|------|------|---------|-------------|-----------|
| Vernal Regional | KVEL | VEL | VEL | 40.4409°N, 109.5099°W | 5,278 ft |
| Duchesne Municipal | - | - | U69 | 40.1994°N, 110.3819°W | 5,817 ft |
| Roosevelt Municipal | - | - | 74V | 40.2781°N, 109.9389°W | 5,105 ft |

### Adjacent Airports
| Airport Name | ICAO | FAA LID | Coordinates | Elevation |
|-------------|------|---------|-------------|-----------|
| Heber Valley | KHCR | HCR | 40.4818°N, 111.4288°W | 5,637 ft |
| Wooden Shoe/Peoa | - | UT62 | 40.6951°N, 111.3416°W | 6,250 ft |
| Thunder Ridge | - | UT83 | 40.6500°N, 111.5833°W | 6,600 ft |
| CCR Field | - | UT27 | 40.1633°N, 110.0461°W | 5,320 ft |
| Rangely | - | 4V0 | 40.0947°N, 108.7612°W | 5,280 ft |

## API Coverage Notes

### FlightAware Coverage
- **Full coverage**: KVEL, KHCR (ICAO codes)
- **Limited coverage**: U69, 74V, 4V0 (may have data for IFR flights)
- **Minimal/No coverage**: UT62, UT83, UT27 (private/small fields)

### FlightRadar24 Coverage
- **Good coverage**: KVEL, KHCR (ADS-B equipped aircraft)
- **Variable coverage**: Depends on ADS-B receiver network in area
- **Better for**: GA traffic with ADS-B Out

## Data Categories

### Flight Status Types
1. **Arrivals** - Flights that have landed
2. **Planned Arrivals** - Scheduled/filed flights expected to arrive
3. **Departures** - Flights that have departed
4. **Planned Departures** - Scheduled/filed flights expected to depart

### Time Windows
- **Recent**: Last 2-4 hours
- **Current**: Next 2-4 hours
- **Daily Summary**: 24-hour period

## Implementation Considerations

### Priority Tiers
1. **Tier 1**: KVEL (Vernal) - Main commercial/GA hub
2. **Tier 2**: KHCR (Heber), U69 (Duchesne), 74V (Roosevelt)
3. **Tier 3**: 4V0 (Rangely), UT27, UT62, UT83

### Data Refresh Rates
- **High activity (KVEL, KHCR)**: Every 5-10 minutes
- **Medium activity**: Every 15-30 minutes
- **Low activity**: Every 30-60 minutes