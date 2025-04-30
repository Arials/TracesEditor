# Custom Protocol Plugins — `backend/protocols/`

This README is the **definitive guide** for adding new packet‑anonymization
plug‑ins (e.g., **BACnet**, **DICOM**) to the backend.

> Keep this file at `backend/protocols/README.md`.  
> Copy/paste elsewhere if you like, but maintain the canonical copy here.

---

## 1  Folder layout

```
backend/
├─ anonymizer.py          # core pcap workflow (already exists)
└─ protocols/             # ← plugin root
   ├─ __init__.py         # auto‑discovers sub‑packages
   ├─ bacnet/             # example plugin (future)
   │   ├─ __init__.py
   │   ├─ handler.py
   │   └─ tests/
   │       └─ test_bacnet.py
   └─ dicom/              # example plugin (future)
       ├─ __init__.py
       ├─ handler.py
       └─ tests/
           └─ test_dicom.py
```

* **One sub‑package per protocol.**
* Each sub‑package **must** export a `ProtocolHandler` class
  in `handler.py`.

---

## 2  `ProtocolHandler` contract

```python
# handler.py (skeleton)
from typing import List
from scapy.packet import Packet

class ProtocolHandler:
    """Base interface every plugin must implement."""

    name  = "BACnet"   # plugin identifier — use folder name
    layer = "BACnet"   # Scapy layer string

    def applies(self, pkt: Packet) -> bool:
        """Return True if `pkt` carries this protocol's layer."""
        ...

    def anonymize_packet(self, pkt: Packet) -> Packet:
        """
        • Receives a Scapy packet containing `self.layer`
        • MUST return a **new** packet with sensitive fields anonymized
        • MUST reset/recalculate checksums you modify
        """
        ...
```

### Check‑sum reset cheat‑sheet

| Layer     | What to reset (`None`) |
|-----------|------------------------|
| Ethernet  | `pkt[Ether].crc` (if present) |
| IPv4      | `pkt[IP].chksum` |
| IPv6      | handled automatically |
| TCP       | `pkt[TCP].chksum` |
| UDP       | `pkt[UDP].chksum` |
| ICMP/ICMPv6 | `pkt[ICMP].chksum` |

After editing, rebuild the packet with  
`pkt = pkt.__class__(bytes(pkt))` so Scapy recalculates everything.

---

## 3  Auto‑discovery & registration

`backend/protocols/__init__.py` lazily scans sub‑folders and registers
all plugins:

```python
# protocols/__init__.py
import importlib, pkgutil, pathlib

handlers = {}

def _discover():
    pkg_path = pathlib.Path(__file__).resolve().parent
    for mod in pkgutil.walk_packages([str(pkg_path)]):
        if not mod.ispkg:
            continue
        m = importlib.import_module(f"{__name__}.{mod.name}")
        ph_cls = getattr(getattr(m, "handler", None), "ProtocolHandler", None)
        if ph_cls:
            handlers[ph_cls.name.lower()] = ph_cls()

_discover()
```

`anonymizer.py` simply imports `from protocols import handlers`
and, during the packet loop:

```python
for ph in protocols.handlers.values():
    if ph.applies(pkt):
        pkt = ph.anonymize_packet(pkt)
        break
```

---

## 4  Unit tests

Place tests in `<protocol>/tests/`. Example:

```python
# tests/test_bacnet.py
from scapy.all import rdpcap
from backend.protocols.bacnet.handler import ProtocolHandler

def test_bacnet_anon():
    raw = rdpcap("samples/bacnet_sample.pcap")[0]
    new = ProtocolHandler().anonymize_packet(raw.copy())
    assert len(raw) == len(new)               # length preserved
    assert raw != new                         # content changed
```

Run all tests:

```bash
pytest -q backend/protocols/**/tests/
```

---

## 5  Workflow to add a new protocol

1. `mkdir backend/protocols/<protocol_name>`
2. Add `__init__.py` and `handler.py` implementing `ProtocolHandler`
3. Add sample pcaps + tests
4. `pytest` until green
5. No edits in `anonymizer.py` needed 🚀

---

## 6  Coding standards

* **Pure‑Python** only (no deps beyond Scapy + stdlib)
* **Stateless**: avoid globals; rely on packet fields
* **Fail‑safe**: if plugin errors, log & return original packet
* **Black + Ruff** formatting: `ruff check` / `black .`

---

Happy anonymizing! ✨