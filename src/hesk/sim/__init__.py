"""Deterministic discrete-event simulator for HESK ledger experiments.

The simulator may know global truth *only to score* an experiment; replicas see only
their own state and the messages they receive.
"""
