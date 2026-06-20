#!/usr/bin/env python3
"""
The Echo Network v. 1.0 - Production Node Software (STARK Edition)
------------------------------------------------------------------
Architecture: Exact Z[Phi] Arithmetic, PQC Isolated UTXOs,
Tri-State Nullifiers, Native Phinary Triple-Ledgering, and STARKs.
"""

from __future__ import annotations
import hashlib
import json
import os
import queue
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Tuple, Set, Optional

# Import the ZK-STARK Engine
try:
    from echo_stark import EchoSTARKEngine
except ImportError:
    print("CRITICAL: 'echo_stark.py' must be in the same folder.")
    exit(1)

# ============================================================
# Exact Phinary Bounds & Z[Phi] Algebra
# ============================================================
K_MIN, K_MAX = -64, 64
PAIR = Tuple[int, int]
EXPS = Tuple[int, ...]

def H(data: str | bytes) -> str:
    if isinstance(data, str): data = data.encode("utf-8")
    return hashlib.sha3_512(data).hexdigest()

def addp(a: PAIR, b: PAIR) -> PAIR: return (a[0] + b[0], a[1] + b[1])
def subp(a: PAIR, b: PAIR) -> PAIR: return (a[0] - b[0], a[1] - b[1])

def sign_pair(x: PAIR) -> int:
    a, b = x
    u, v = 2 * a + b, b
    if v == 0: return (u > 0) - (u < 0)
    if u == 0: return (v > 0) - (v < 0)
    if u > 0 and v > 0: return 1
    if u < 0 and v < 0: return -1
    lhs, rhs = u * u, 5 * v * v
    if u > 0 and v < 0: return (lhs > rhs) - (lhs < rhs)
    return (rhs > lhs) - (rhs < lhs)

def leq_pair(a: PAIR, b: PAIR) -> bool: return sign_pair(subp(a, b)) <= 0
def is_zero_pair(a: PAIR) -> bool: return a == (0, 0)

_PAIR_CACHE: Dict[int, PAIR] = {0: (1, 0), 1: (0, 1)}

def phi_pair(k: int) -> PAIR:
    if k < K_MIN or k > K_MAX: raise ValueError(f"Exponent {k} out of bounds")
    if k in _PAIR_CACHE: return _PAIR_CACHE[k]
    for n in range(2, K_MAX + 1):
        if n not in _PAIR_CACHE: _PAIR_CACHE[n] = addp(_PAIR_CACHE[n - 1], _PAIR_CACHE[n - 2])
    for n in range(0, K_MIN, -1):
        if n - 1 not in _PAIR_CACHE: _PAIR_CACHE[n - 1] = subp(_PAIR_CACHE[n + 1], _PAIR_CACHE[n])
    return _PAIR_CACHE[k]

def pair_from_exps(exps: EXPS) -> PAIR:
    out = (0, 0)
    for k in exps: out = addp(out, phi_pair(k))
    return out

def encode_pair_greedy(x: PAIR) -> Tuple[EXPS, PAIR]:
    if sign_pair(x) < 0: raise ValueError("Cannot encode negative phinary value")
    rem, out, last = x, [], None
    for k in range(K_MAX, K_MIN - 1, -1):
        pk = phi_pair(k)
        if leq_pair(pk, rem) and (last is None or last != k + 1):
            out.append(k)
            rem = subp(rem, pk)
            last = k
        if is_zero_pair(rem): break
    return tuple(out), rem

# ============================================================
# Post-Quantum Cryptography: True Lamport OTS
# ============================================================
class PQLamportSignature:
    @staticmethod
    def generate_keys() -> Tuple[List[List[str]], List[List[str]]]:
        priv = [[secrets.token_hex(32) for _ in range(2)] for _ in range(256)]
        pub = [[hashlib.sha3_256(bytes.fromhex(p)).hexdigest() for p in pair] for pair in priv]
        return priv, pub

    @staticmethod
    def sign(msg: bytes, priv_key: List[List[str]]) -> List[str]:
        h = hashlib.sha3_256(msg).digest()
        bits = ''.join(f'{byte:08b}' for byte in h)
        return [priv_key[i][int(bit)] for i, bit in enumerate(bits)]

    @staticmethod
    def verify(msg: bytes, sig: List[str], pub_key: List[List[str]]) -> bool:
        if len(sig) != 256 or len(pub_key) != 256: return False
        h = hashlib.sha3_256(msg).digest()
        bits = ''.join(f'{byte:08b}' for byte in h)
        for i, bit in enumerate(bits):
            if hashlib.sha3_256(bytes.fromhex(sig[i])).hexdigest() != pub_key[i][int(bit)]:
                return False
        return True

# ============================================================
# Protocol Data Models & Triple-Ledger
# ============================================================
@dataclass
class EchoProof:
    proof_id: str
    debit_id: str
    credit_ids: List[str]
    envelope_id: str
    nullifier: str
    value_in: PAIR
    value_out: PAIR
    silt_pair: PAIR
    kind: str
    timestamp: float

@dataclass
class Receipt:
    owner: str
    exps: EXPS
    parent_id: str
    rid: str
    pub_key: List[List[str]]
    priv_key: List[List[str]]  
    state: str = "LIVE"
    purpose: str = "receipt"

    def value_pair(self) -> PAIR: return pair_from_exps(self.exps)
    def nullifier(self) -> str: return H(f"nullifier|{self.rid}|{self.owner}")

@dataclass
class Envelope:
    eid: str
    sender: str
    destination: str
    parent_id: str
    target_exps: EXPS
    change_exps: EXPS
    silt_pair: PAIR
    nullifier: str
    expiry_epoch: int
    phase: str
    watermark: str
    signature: List[str]
    pub_key: List[List[str]]
    branch_proof: str = "" 
    fee_exps: EXPS = field(default_factory=tuple)
    metadata: str = ""

# ============================================================
# Core Mesh Transport
# ============================================================
class MeshNetwork:
    def __init__(self):
        self.epoch = 1
        self.nullifiers: Dict[str, str] = {}
        self.catchment: Set[str] = set()
        self.wallets: Dict[str, 'EchoWallet'] = {}

    def reserve_nullifier(self, nf: str, eid: str) -> Optional[str]:
        if self.nullifiers.get(nf, "AVAILABLE") != "AVAILABLE": return None
        self.nullifiers[nf] = "PLEDGED"
        return H(f"watermark|{nf}|{eid}|{self.epoch}")

    def mark_spent(self, nf: str, eid: str) -> None:
        self.nullifiers[nf] = "SPENT"
        self.catchment.add(eid)

    def submit(self, env: Envelope) -> bool:
        if env.eid in self.catchment: return False
        if env.destination in self.wallets:
            self.wallets[env.destination].inbox.put(env)
            return True
        return False

# ============================================================
# The Echo Wallet (v 1.0 Core - STARK Edition)
# ============================================================
class EchoWallet:
    def __init__(self, name: str, mesh: MeshNetwork):
        self.name = name
        self.mesh = mesh
        self.mesh.wallets[self.name] = self
        self.receipts: Dict[str, Receipt] = {}
        self.envelopes: Dict[str, Envelope] = {}
        self.ledger: List[EchoProof] = []
        self.inbox: queue.Queue[Envelope] = queue.Queue()
        self.outbox: queue.Queue[Envelope] = queue.Queue()
        self.fee_queue: queue.Queue[Envelope] = queue.Queue()
        self.orphan_loaded = False

    def load_orphan_genesis(self, filepath: str = "original_orphan_echo.json"):
        if self.orphan_loaded or not Path(filepath).exists(): return
        
        with open(filepath, 'r') as f:
            data = json.load(f)
            
        expected_digest = "Eric James Wolverton ~ Born August 13, 1986 AD, Son of Craig Brian Hissong"
        if data.get("digest") != expected_digest:
            print(f"SECURITY HALT: Orphan digest mismatch for wallet {self.name}.")
            return

        orphan_id = data.get("orphan_id")
        valid_owners = {"Benefit of Man", "Man", "Eric James Wolverton"}
        
        for out in data.get("outputs", []):
            if out["owner"] not in valid_owners: continue
            
            if out["owner"] == self.name:
                exps = tuple(out["exponents"])
                priv, pub = PQLamportSignature.generate_keys()
                rid = H(f"genesis|{orphan_id}|{out['index']}|{self.name}|{exps}")
                
                r = Receipt(self.name, exps, orphan_id, rid, pub, priv, "LIVE", out["purpose"])
                self.receipts[rid] = r
                
                val = pair_from_exps(exps)
                self.ledger.append(EchoProof(
                    proof_id=H(f"genesis_proof|{rid}"), debit_id=orphan_id, credit_ids=[rid],
                    envelope_id="", nullifier="", value_in=val, value_out=val, silt_pair=(0,0),
                    kind="genesis", timestamp=time.time()
                ))
                print(f"[+] Loaded Genesis Fund '{out['purpose']}' to local wallet: {self.name}")
        self.orphan_loaded = True

    def _select_receipt(self, target: EXPS) -> Optional[Receipt]:
        tv = pair_from_exps(target)
        live = [r for r in self.receipts.values() if r.state == "LIVE" and r.owner == self.name and leq_pair(tv, r.value_pair())]
        if not live: return None
        return sorted(live, key=lambda r: (len(r.exps), abs(r.value_pair()[0]) + abs(r.value_pair()[1])))[0]

    def make_payment(self, destination: str, target: EXPS, metadata: str = "") -> Optional[Envelope]:
        parent = self._select_receipt(target)
        if not parent: return None
        
        target_pair = pair_from_exps(target)
        change_pair = subp(parent.value_pair(), target_pair)
        change_exps, silt = encode_pair_greedy(change_pair)
        
        nf = parent.nullifier()
        draft = f"env|{parent.rid}|{self.name}|{destination}|{target}|{change_exps}|{silt}|{self.mesh.epoch}|{metadata}"
        eid = H(draft)
        
        wm = self.mesh.reserve_nullifier(nf, eid)
        if not wm: return None
            
        sig = PQLamportSignature.sign((draft + "|" + wm).encode(), parent.priv_key)
        
        # STARK INTEGRATION
        lamport_hash = H(str(sig))
        zk_proof = EchoSTARKEngine.generate_branch_proof(
            parent_rid=parent.rid,
            parent_value=parent.value_pair(),
            target_value=target_pair,
            change_value=change_pair,
            silt_value=silt,
            lamport_sig_hash=lamport_hash
        )
        
        env = Envelope(
            eid=eid, sender=self.name, destination=destination, parent_id=parent.rid,
            target_exps=target, change_exps=change_exps, silt_pair=silt,
            nullifier=nf, expiry_epoch=self.mesh.epoch + 3,
            phase="PLEDGED", watermark=wm, signature=sig, pub_key=parent.pub_key, 
            branch_proof=zk_proof,
            metadata=metadata
        )
        
        parent.state = "PLEDGED" 
        
        change_rid = ""
        if change_exps or not is_zero_pair(silt):
            priv, pub = PQLamportSignature.generate_keys()
            cid = H(f"change|{eid}")
            change_rid = cid
            self.receipts[cid] = Receipt(self.name, change_exps, parent.rid, cid, pub, priv, "LIVE", "change")
            
        self.envelopes[eid] = env
        self.outbox.put(env)
        
        vin = parent.value_pair()
        vout = addp(pair_from_exps(target), pair_from_exps(change_exps))
        self.ledger.append(EchoProof(
            proof_id=H("proof_spend|" + eid), debit_id=parent.rid, credit_ids=[change_rid] if change_rid else [],
            envelope_id=eid, nullifier=nf, value_in=vin, value_out=vout, silt_pair=silt, kind="send", timestamp=time.time()
        ))
        return env

    def process_outbox(self):
        while not self.outbox.empty():
            env = self.outbox.get()
            if self.mesh.submit(env): env.phase = "SENT"

    def receive_envelope(self, env: Envelope):
        if env.eid in self.mesh.catchment or self.mesh.epoch > env.expiry_epoch: return
        if env.destination != self.name: return 

        # STARK Verification
        if not EchoSTARKEngine.verify_branch_proof(env.branch_proof, env.eid):
            print(f"[-] ZK-STARK Rejected: Invalid branch proof on {env.eid[:8]}")
            return

        draft = f"env|{env.parent_id}|{env.sender}|{env.destination}|{env.target_exps}|{env.change_exps}|{env.silt_pair}|{env.expiry_epoch - 3}|{env.metadata}"
        if not PQLamportSignature.verify((draft + "|" + env.watermark).encode(), env.signature, env.pub_key):
            print(f"[-] Security Fault: PQC verification failed on {env.eid[:8]}")
            return

        priv, pub = PQLamportSignature.generate_keys()
        rid = H(f"payment|{env.eid}")
        self.receipts[rid] = Receipt(self.name, env.target_exps, env.parent_id, rid, pub, priv, "LIVE", "received")
        
        self.mesh.mark_spent(env.nullifier, env.eid)
        env.phase = "SETTLED"
        self.envelopes[env.eid] = env
        
        vin = addp(pair_from_exps(env.target_exps), addp(pair_from_exps(env.change_exps), env.silt_pair))
        vout = pair_from_exps(env.target_exps)
        self.ledger.append(EchoProof(
            proof_id=H("proof_recv|" + env.eid), debit_id=env.parent_id, credit_ids=[rid],
            envelope_id=env.eid, nullifier=env.nullifier, value_in=vin, value_out=vout,
            silt_pair=env.silt_pair, kind="receive", timestamp=time.time()
        ))
        
        if env.fee_exps: self.fee_queue.put(env)

    def claim_or_refund_pledges(self):
        for eid, env in list(self.envelopes.items()):
            if env.phase in {"PLEDGED", "SENT"} and self.mesh.epoch > env.expiry_epoch:
                env.phase = "REFUNDED"
                if env.parent_id in self.receipts: self.receipts[env.parent_id].state = "SPENT"
                
                priv, pub = PQLamportSignature.generate_keys()
                refund_id = H(f"refund|{eid}")
                self.receipts[refund_id] = Receipt(self.name, env.target_exps, env.parent_id, refund_id, pub, priv, "LIVE", "refund")
                self.mesh.mark_spent(env.nullifier, eid)
                
                val = addp(pair_from_exps(env.target_exps), env.silt_pair)
                self.ledger.append(EchoProof(
                    proof_id=H("refund_proof|" + eid), debit_id=env.parent_id, credit_ids=[refund_id],
                    envelope_id=eid, nullifier=env.nullifier, value_in=val, value_out=val,
                    silt_pair=env.silt_pair, kind="refund", timestamp=time.time()
                ))

    def tick(self):
        self.mesh.epoch += 1
        self.process_outbox()
        while not self.inbox.empty(): self.receive_envelope(self.inbox.get())
        self.claim_or_refund_pledges()
