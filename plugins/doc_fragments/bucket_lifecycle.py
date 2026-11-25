# Copyright: (c) 2026, Geoffrey Burger (@dagoldfish)
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import absolute_import, division, print_function

__metaclass__ = type


class ModuleDocFragment:
    DOCUMENTATION = r"""
options:
  lifecycle_rules:
    description:
      - Reconcile the listed rules by ID. Each present entry defines the complete rule for that ID.
      - Omitted IDs are preserved. An empty list leaves all rules untouched.
    type: list
    elements: dict
    suboptions:
      id: {description: Unique lifecycle rule ID., type: str, required: true}
      state: {description: Create or replace the rule or remove it by ID., type: str, choices: [present, absent], default: present}
      enabled: {description: Activate this rule., type: bool, default: true}
      prefix: {description: Match keys starting with this prefix. Empty matches all keys., type: str, default: ''}
      expiration_days: {description: Expire current objects after this many days., type: int}
      noncurrent_expiration_days: {description: Expire versions this many days after they become noncurrent., type: int}
      newer_noncurrent_versions: {description: Keep this many newer noncurrent versions when expiring old versions., type: int}
      expired_object_delete_marker: {description: Clean up expired delete markers. Mutually exclusive with expiration_days., type: bool, default: false}
      transition_days: {description: Transition current objects after this many days. Zero allows immediate transition., type: int}
      transition_tier: {description: Name of a configured remote tier. Requires transition_days., type: str}
"""
