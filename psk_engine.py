import logging
import urllib.request
import gzip
import csv
from io import BytesIO, StringIO
from typing import List
from dataclasses import dataclass
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

@dataclass
class DigitalSpot:
    rx_call: str
    rx_grid: str
    tx_call: str
    tx_grid: str
    snr: int
    mode: str
    freq_mhz: float
    time_utc: datetime

def fetch_psk_spots(receiver_callsign: str, max_age_minutes: int = 15) -> List[DigitalSpot]:
    """
    Fetches spots received by a specific callsign from PSKReporter.
    
    This interrogates the PSKReporter API using `rxsender=rx` to retrieve spots 
    decoded by the target node. The engine dynamically detects the payload format 
    (handling standard .zip, .gz, or plain CSV) and extracts the CSV data in memory.
    """
    if not receiver_callsign:
        return []
        
    url = f"https://pskreporter.info/cgi-bin/pskdata.pl?adif=0&last_minutes={max_age_minutes}&callsign={receiver_callsign}&rxsender=rx"
    req = urllib.request.Request(url, headers={'User-Agent': 'POTAProp/1.0'})
    spots = []
    
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            content = response.read()
            # PSKReporter returns standard ZIP (PK) or sometimes plain text.
            if content.startswith(b'PK\x03\x04'):
                import zipfile
                with zipfile.ZipFile(BytesIO(content)) as zf:
                    # Usually there is only one file, e.g. psk_data.csv
                    filename = zf.namelist()[0]
                    with zf.open(filename) as f:
                        text = f.read().decode('utf-8', errors='replace')
            elif content.startswith(b'\x1f\x8b'):
                with gzip.GzipFile(fileobj=BytesIO(content)) as gz:
                    text = gz.read().decode('utf-8', errors='replace')
            else:
                text = content.decode('utf-8', errors='replace')
                
            reader = csv.DictReader(StringIO(text, newline=''))
            for row in reader:
                # Fields usually include: sNR, mode, MHz, rxTime, senderCallsign, senderLocator, receiverCallsign, receiverLocator
                if 'sNR' not in row or 'receiverCallsign' not in row or 'senderCallsign' not in row:
                    continue
                    
                rx_call = row['receiverCallsign']
                # We only want spots where our target callsign is the receiver, as that tells us what THEY can hear
                if rx_call.upper() != receiver_callsign.upper():
                    continue
                    
                try:
                    snr = int(row['sNR'])
                    freq = float(row['MHz'])
                    dt = datetime.strptime(row['rxTime'], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                    
                    spots.append(DigitalSpot(
                        rx_call=rx_call,
                        rx_grid=row.get('receiverLocator', ''),
                        tx_call=row['senderCallsign'],
                        tx_grid=row.get('senderLocator', ''),
                        snr=snr,
                        mode=row.get('mode', ''),
                        freq_mhz=freq,
                        time_utc=dt
                    ))
                except (ValueError, KeyError) as e:
                    logger.debug(f"Skipping row due to error: {e}")
                    continue
                    
    except Exception as e:
        logger.error(f"Failed to fetch PSKReporter data: {e}")
        
    return spots

def fetch_activator_psk_spots(activator_callsign: str, max_age_minutes: int = 30) -> List[DigitalSpot]:
    """
    Fetches spots where a specific callsign is the SENDER from PSKReporter.
    
    This uses `rxsender=tx` to interrogate PSKReporter for all instances where 
    the targeted activator's signal was decoded worldwide. Payload formats (.zip, .gz) 
    are dynamically decompressed in memory.
    """
    if not activator_callsign:
        return []
        
    url = f"https://pskreporter.info/cgi-bin/pskdata.pl?adif=0&last_minutes={max_age_minutes}&callsign={activator_callsign}&rxsender=tx"
    req = urllib.request.Request(url, headers={'User-Agent': 'POTAProp/1.0'})
    spots = []
    
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            content = response.read()
            if content.startswith(b'PK\x03\x04'):
                import zipfile
                with zipfile.ZipFile(BytesIO(content)) as zf:
                    filename = zf.namelist()[0]
                    with zf.open(filename) as f:
                        text = f.read().decode('utf-8', errors='replace')
            elif content.startswith(b'\x1f\x8b'):
                with gzip.GzipFile(fileobj=BytesIO(content)) as gz:
                    text = gz.read().decode('utf-8', errors='replace')
            else:
                text = content.decode('utf-8', errors='replace')
                
            reader = csv.DictReader(StringIO(text, newline=''))
            for row in reader:
                if 'sNR' not in row or 'receiverCallsign' not in row or 'senderCallsign' not in row:
                    continue
                    
                tx_call = row['senderCallsign']
                if tx_call.upper() != activator_callsign.upper():
                    continue
                    
                try:
                    snr = int(row['sNR'])
                    freq = float(row['MHz'])
                    dt = datetime.strptime(row['rxTime'], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                    
                    spots.append(DigitalSpot(
                        rx_call=row['receiverCallsign'],
                        rx_grid=row.get('receiverLocator', ''),
                        tx_call=tx_call,
                        tx_grid=row.get('senderLocator', ''),
                        snr=snr,
                        mode=row.get('mode', ''),
                        freq_mhz=freq,
                        time_utc=dt
                    ))
                except (ValueError, KeyError) as e:
                    continue
                    
    except Exception as e:
        logger.error(f"Failed to fetch activator PSKReporter data for {activator_callsign}: {e}")
        
    return spots

def get_nearest_rbn_node(home_grid: str) -> str:
    """
    Finds a nearby active RBN/PSK node callsign based on the user's home grid.
    Since active node lists are massive, we return a highly active 'super-node' 
    in the same continent/region as a fallback.
    """
    if not home_grid or len(home_grid) < 2:
        return "W1AW"
        
    field = home_grid[:2].upper()
    
    # Simple hardcoded fallback dictionary of massive, always-on multi-band monitoring stations
    super_nodes = {
        # North America East Coast
        "FN": "W3LPL, K1TTT, N4ZR",
        "FM": "N4ZR, W3LPL, K3LR",
        "EL": "N4ZR, K4RO, W3LPL",
        
        # North America Midwest/Central
        "EN": "K3LR, W9SU, N4ZR",
        "EM": "K3LR, K0VH, N4ZR",
        
        # North America West Coast
        "DN": "K7AR, VE7CC, N6TV",
        "DM": "K7AR, W6YX, N6TV",
        "CN": "VE7CC, K7AR, W6YX",
        "CM": "W6YX, N6TV, K7AR",
        
        # Europe
        "JO": "SK3W, DF9IC, G0KSC",
        "JN": "DF9IC, EA1AST, SK3W",
        "IO": "G0KSC, DF9IC, EA1AST",
        "IN": "EA1AST, DF9IC, G0KSC",
        
        # Oceania
        "QF": "VK4CT, ZL2IFB",
        
        # Asia
        "PM": "JA1ZLO, BA4TB",
        "QM": "JA1ZLO, BA4TB",
    }
    
    return super_nodes.get(field, "W1AW, W3LPL, K3LR")


def get_live_local_rbn_nodes(home_lat: float, home_lon: float, max_distance_miles: float = 200.0) -> list[str]:
    """
    Scrapes the live Reverse Beacon Network skimmers list and returns active 
    nodes within max_distance_miles of the user's home location.
    Raises an Exception if the network request or parsing fails.
    """
    import urllib.request
    import re
    from propagation_engine import maidenhead_to_latlon, calculate_distance_and_bearing
    
    local_nodes = []
    
    url = "https://www.reversebeacon.net/cont_includes/status.php?t=skt"
    req = urllib.request.Request(url, headers={"User-Agent": "POTA-Prop/1.0"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        html = resp.read().decode("utf-8")
        
    matches = re.findall(r"c=([A-Z0-9/]+)&t=de\".*?<td>([A-Z]{2}[0-9]{2}[A-Z]{0,2})</td>", html, re.IGNORECASE | re.DOTALL)
    
    if not matches:
        raise ValueError("Failed to parse Reverse Beacon Network HTML.")
    
    for call, grid in matches:
        call = call.strip().upper()
        grid = grid.strip().upper()
        if not grid or len(grid) < 4:
            continue
            
        r_lat, r_lon = maidenhead_to_latlon(grid)
        if r_lat is not None and r_lon is not None:
            d_km, _ = calculate_distance_and_bearing(home_lat, home_lon, r_lat, r_lon)
            dist_mi = d_km * 0.621371
            if dist_mi <= max_distance_miles:
                local_nodes.append(call)
                
    return list(set(local_nodes))
