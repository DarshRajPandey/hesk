"""Registry of implementations under test (looked up by name so jobs pickle cheaply)."""
from functools import partial
from typing import Callable, Dict

from hesk.sim.replicas import ABLATIONS, LatticeReplica, LegacyReplica, Replica

Factory = Callable[[str], Replica]

LEGACY = ("legacy/gossip/relay", "legacy/reconcile/relay", "legacy/gossip/direct", "legacy/reconcile/direct")
LATTICE = tuple(c.name for c in ABLATIONS)

IMPLS: Dict[str, Factory] = {
    "legacy/gossip/relay": partial(LegacyReplica, mode="gossip", relay=True),
    "legacy/reconcile/relay": partial(LegacyReplica, mode="reconcile", relay=True),
    "legacy/gossip/direct": partial(LegacyReplica, mode="gossip", relay=False),
    "legacy/reconcile/direct": partial(LegacyReplica, mode="reconcile", relay=False),
}
for _cfg in ABLATIONS:
    IMPLS[_cfg.name] = partial(LatticeReplica, cfg=_cfg)



def resolve(name: str):
    """Return (factory, patch_names). ``legacy/<mode>/<relay|direct>+resolver+window+clock`` adds patches."""
    base, *patches = name.split("+")
    if base in IMPLS:
        return IMPLS[base], tuple(patches)
    _, mode, relay = base.split("/")
    return partial(LegacyReplica, mode=mode, relay=(relay == "relay")), tuple(patches)


# the legacy variant that is most favourable to HESK on every axis we model
BEST_LEGACY = "legacy/reconcile/direct"
