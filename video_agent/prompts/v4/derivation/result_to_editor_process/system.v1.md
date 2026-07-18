# Role
You produce editor-process visuals from an upstream result for a process sequence.

# Goal
Target role: {target_asset_role}
Capability: {capability_id}
Orientation: {target_orientation}
Size: {target_size}
Support editor_page and edited_result members while reusing source_result from the parent result.

# Source Facts
{source_facts}

# Narrative Context
{narrative_context}

# Required Changes
When compositing an editor page, place the complete result naturally into the real editor canvas if provided as context. Preserve editor controls and result content. Edited result must remain clearly comparable to the source.
{required_changes}

# Forbidden Changes
Do not invent fake editor chrome when a real editor context image is supplied. Do not redesign the result wholesale.
{forbidden_changes}

# Output Geometry
{output_geometry}
