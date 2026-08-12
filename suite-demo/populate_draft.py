# Copyright 2026 SARC Suite Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Populate the paper draft with generated numbers.

SEED = 26313
"""
import json
import re
from pathlib import Path
from typing import Dict


def populate_draft(draft_path: str, slots: Dict[str, str], output_path: str):
    """
    Read draft_path, replace [GENERATED: key] slots with values from slots dict.
    Write to output_path.
    """
    with open(draft_path) as f:
        content = f.read()

    original_content = content
    unfilled = []

    # Find all [GENERATED: key] slots
    slot_pattern = re.compile(r'\[GENERATED:\s*([^\]]+)\]')

    def replace_slot(match):
        key = match.group(1).strip()
        if key in slots:
            return slots[key]
        else:
            unfilled.append(key)
            return match.group(0)  # Leave as-is if not found

    content = slot_pattern.sub(replace_slot, content)

    # Write output
    with open(output_path, "w") as f:
        f.write(content)

    print(f"✓ Populated {len(slots) - len(unfilled)} slots")
    if unfilled:
        print(f"⚠ {len(unfilled)} unfilled slots: {unfilled}")
    else:
        print(f"✓ Zero unfilled slots")

    # Verify that only slots changed
    original_no_slots = slot_pattern.sub("", original_content)
    modified_no_slots = slot_pattern.sub("", content)

    if original_no_slots == modified_no_slots:
        print(f"✓ Diff shows only slot substitutions")
    else:
        print(f"⚠ Diff shows additional changes beyond slots")

    return unfilled
