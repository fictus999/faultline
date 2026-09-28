"""Detector process: owns per-service sliding windows, baselines, severity and alert state.
It is stateful and the single writer for the services it watches.
"""
