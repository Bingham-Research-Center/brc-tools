"""ADS-B / Mode-S message decoder.

Moved 2026-08-10 from brc-knowledge scholarium/active-projects/ads-b-meteo/
(knowledge repo holds prose, not code). Companion project notes live there;
sample output can be regenerated from the FlightAware-fed receiver.
"""
import signal
import inspect
import time
from collections import defaultdict

import pyModeS as pms
from pyModeS.extra.tcpclient import TcpClient
import pandas as pd
import numpy as np

class TimeoutException(Exception):
    pass

def _alarm_handler(signum, frame):
    raise TimeoutException()

# Build function dictionaries more comprehensively
ADSB_FUNCS = {
    # Basic info
    'callsign': pms.adsb.callsign,
    'category': pms.adsb.category,

    # Position
    'altitude': pms.adsb.altitude,
    'oe_flag': pms.adsb.oe_flag,

    # Velocity
    'velocity': pms.adsb.velocity,
    'speed_heading': pms.adsb.speed_heading,
    'airborne_velocity': pms.adsb.airborne_velocity,
    'altitude_diff': pms.adsb.altitude_diff,

    # Uncertainty/accuracy
    'version': pms.adsb.version,
    'nuc_p': pms.adsb.nuc_p,
    'nuc_v': pms.adsb.nuc_v,
    'nac_p': pms.adsb.nac_p,
    'nac_v': pms.adsb.nac_v,
    'nic_s': pms.adsb.nic_s,
    'nic_a_c': pms.adsb.nic_a_c,
    'nic_b': pms.adsb.nic_b,
    'sil': pms.adsb.sil,

    # Target state (TC=29)
    'selected_altitude': pms.adsb.selected_altitude,
    'selected_heading': pms.adsb.selected_heading,
    'baro_pressure_setting': pms.adsb.baro_pressure_setting,
    'autopilot': pms.adsb.autopilot,
    'vnav_mode': pms.adsb.vnav_mode,
    'altitude_hold_mode': pms.adsb.altitude_hold_mode,
    'approach_mode': pms.adsb.approach_mode,
    'tcas_operational': pms.adsb.tcas_operational,
    'lnav_mode': pms.adsb.lnav_mode,

    # Emergency
    'emergency_state': pms.adsb.emergency_state,
    'emergency_squawk': pms.adsb.emergency_squawk,
    'is_emergency': pms.adsb.is_emergency,
}

# BDS flags
BDS_FLAGS = {
    'bds10': pms.bds.bds10,
    'bds17': pms.bds.bds17,
    'bds20': pms.bds.bds20,
    'bds30': pms.bds.bds30,
    'bds40': pms.bds.bds40,
    'bds44': pms.bds.bds44,
    'bds45': pms.bds.bds45,
    'bds50': pms.bds.bds50,
    'bds60': pms.bds.bds60,
}

# Comm-B decoders
COMMB_FUNCS = {
    # BDS 1,0 - Data link capability
    'ovc10': pms.commb.ovc10,

    # BDS 1,7 - GICB capability
    'cap17': pms.commb.cap17,

    # BDS 2,0 - Aircraft ID
    'cs20': pms.commb.cs20,

    # BDS 4,0 - Selected vertical intention
    'selalt40_mcp': pms.commb.selalt40mcp,
    'selalt40_fms': pms.commb.selalt40fms,
    'p40_baro': pms.commb.p40baro,

    # BDS 4,4 - Meteorological routine
    'wind44': pms.commb.wind44,
    'temp44': pms.commb.temp44,
    'p44': pms.commb.p44,
    'hum44': pms.commb.hum44,

    # BDS 4,5 - Meteorological hazard
    'turb45': pms.commb.turb45,
    'ws45': pms.commb.ws45,
    'mb45': pms.commb.mb45,
    'ic45': pms.commb.ic45,
    'wv45': pms.commb.wv45,
    'temp45': pms.commb.temp45,
    'p45': pms.commb.p45,
    'rh45': pms.commb.rh45,

    # BDS 5,0 - Track and turn
    'roll50': pms.commb.roll50,
    'trk50': pms.commb.trk50,
    'gs50': pms.commb.gs50,
    'rtrk50': pms.commb.rtrk50,
    'tas50': pms.commb.tas50,

    # BDS 6,0 - Heading and speed
    'hdg60': pms.commb.hdg60,
    'ias60': pms.commb.ias60,
    'mach60': pms.commb.mach60,
    'vr60_baro': pms.commb.vr60baro,
    'vr60_ins': pms.commb.vr60ins,
}

class BeastDF(TcpClient):
    def __init__(self, host, port, ref_lat=None, ref_lon=None):
        super().__init__(host, port, 'beast')
        self.records = []
        self.position_cache = {}  # {icao: {'even': (msg, ts), 'odd': (msg, ts)}}
        self.msg_counts = defaultdict(int)  # Track message statistics
        self.ref_lat = ref_lat
        self.ref_lon = ref_lon

    def handle_messages(self, messages):
        for raw_bytes, ts in messages:
            # Convert to hex string
            if isinstance(raw_bytes, (bytes, bytearray)):
                msg = raw_bytes.hex()
            else:
                msg = raw_bytes.strip()

            # Basic validation
            if len(msg) != 28:
                continue

            # CRC check
            if pms.crc(msg) != 0:
                self.msg_counts['crc_fail'] += 1
                continue

            df = pms.df(msg)
            icao = pms.icao(msg)

            if not icao:
                continue

            self.msg_counts[f'df{df}'] += 1

            # Base record
            rec = {
                'timestamp': ts,
                'datetime_utc': pd.to_datetime(ts, unit='s', utc=True),
                'msg': msg,  # Store raw message
                'df': df,
                'icao': icao,
            }

            # Process ADS-B messages (DF 17/18)
            if df in [17, 18]:
                tc = pms.adsb.typecode(msg)
                rec['typecode'] = tc
                self.msg_counts[f'tc{tc}'] += 1

                # Decode all available fields
                for fname, func in ADSB_FUNCS.items():
                    try:
                        val = func(msg)
                        if val is not None and val != (None, None):
                            rec[fname] = val
                    except:
                        pass

                # Handle position messages specially
                if tc in range(5, 23):  # All position messages
                    self._handle_position_message(msg, ts, icao, tc, rec)

            # Process Comm-B messages (DF 20/21)
            elif df in [20, 21]:
                # Try to infer BDS code
                try:
                    bds_code = pms.bds.infer(msg, mrar=True)
                    rec['bds'] = bds_code

                    if bds_code:
                        self.msg_counts[f'bds{bds_code}'] += 1
                except:
                    rec['bds'] = None

                # Check all BDS flags
                for bds_name, module in BDS_FLAGS.items():
                    try:
                        fn_name = f'is{bds_name[3:]}'
                        if hasattr(module, fn_name):
                            fn = getattr(module, fn_name)
                            rec[fn_name] = fn(msg)
                    except:
                        pass

                # Decode Comm-B data
                for key, func in COMMB_FUNCS.items():
                    try:
                        val = func(msg)
                        if val is not None:
                            rec[key] = val
                    except:
                        pass

            # Process surveillance altitude (DF 4/5)
            elif df in [4, 5]:
                try:
                    rec['altitude'] = pms.common.altcode(msg)
                except:
                    pass

            # Process all-call replies (DF 11)
            elif df == 11:
                try:
                    rec['capability'] = pms.common.ca(msg)
                except:
                    pass

            self.records.append(rec)

    def _handle_position_message(self, msg, ts, icao, tc, rec):
        """Handle position decoding with even/odd message pairs."""
        if tc not in range(5, 23):
            return

        oe_flag = pms.adsb.oe_flag(msg)
        rec['oe_flag'] = oe_flag

        # Initialize position cache for this aircraft
        if icao not in self.position_cache:
            self.position_cache[icao] = {}

        # Store message based on even/odd flag
        if oe_flag == 0:
            self.position_cache[icao]['even'] = (msg, ts)
        else:
            self.position_cache[icao]['odd'] = (msg, ts)

        # Try to decode position if we have both messages
        if 'even' in self.position_cache[icao] and 'odd' in self.position_cache[icao]:
            even_msg, even_ts = self.position_cache[icao]['even']
            odd_msg, odd_ts = self.position_cache[icao]['odd']

            # Messages should be within 10 seconds
            if abs(even_ts - odd_ts) < 10:
                try:
                    # Surface position (TC 5-8)
                    if 5 <= tc <= 8:
                        if self.ref_lat and self.ref_lon:
                            lat, lon = pms.adsb.surface_position(
                                even_msg, odd_msg, even_ts, odd_ts,
                                self.ref_lat, self.ref_lon
                            )
                            rec['latitude'] = lat
                            rec['longitude'] = lon
                            rec['position_type'] = 'surface'
                    # Airborne position
                    else:
                        lat, lon = pms.adsb.airborne_position(
                            even_msg, odd_msg, even_ts, odd_ts
                        )
                        rec['latitude'] = lat
                        rec['longitude'] = lon
                        rec['position_type'] = 'airborne'
                except:
                    # Could also try position_with_ref if available
                    if self.ref_lat and self.ref_lon:
                        try:
                            lat, lon = pms.adsb.position_with_ref(
                                msg, self.ref_lat, self.ref_lon
                            )
                            rec['latitude'] = lat
                            rec['longitude'] = lon
                            rec['position_type'] = 'with_ref'
                        except:
                            pass

    def get_statistics(self):
        """Return message statistics."""
        return dict(self.msg_counts)

if __name__ == "__main__":
    host = '129.123.91.145'
    port = 30005

    # The location of receiver (Vernal, USU campus)

    ref_lat = 40.46014413068818
    ref_lon = -109.56578602889579

    client = BeastDF(host, port, ref_lat, ref_lon)

    # Set up timeout
    signal.signal(signal.SIGALRM, _alarm_handler)
    n_sec = 15
    signal.alarm(n_sec)

    try:
        client.run()
    except TimeoutException:
        print(f"\n→ {n_sec} seconds elapsed, stopping capture.")
    finally:
        signal.alarm(0)

    # Print statistics
    print("\nMessage Statistics:")
    stats = client.get_statistics()
    for k, v in sorted(stats.items()):
        print(f"  {k}: {v}")

    # Create DataFrame
    data_df = pd.DataFrame(client.records)

    if not data_df.empty:
        # Set multi-index
        data_df = data_df.set_index(['icao', 'datetime_utc']).sort_index()

        # Save to CSV
        data_df.to_csv('example_output_sept2025.csv', index=True)

        print(f"\nTotal records: {len(data_df)}")
        print(f"Unique aircraft: {data_df.index.get_level_values('icao').nunique()}")

        # Show position success rate
        pos_success = data_df['latitude'].notna().sum()
        print(f"Successful position decodes: {pos_success}/{len(data_df)} ({pos_success/len(data_df)*100:.1f}%)")
        