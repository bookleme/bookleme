"""Pluggable data adapters. v1 ships the 'none' adapter only.

The finance case in the WeChat article depends on a proprietary research DB.
BookLeme deliberately does NOT bundle one: when data is missing the skill must
ask instead of inventing numbers (routing_rules.insufficient_data_policy=ask).
"""

ADAPTERS = {"none": "no external data; ask the user when data is missing"}
