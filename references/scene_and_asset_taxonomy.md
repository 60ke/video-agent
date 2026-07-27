# Scene and Asset Taxonomy

Scene classification and material role are independent dimensions.

Typical scene structures include:

```text
single
gallery
parameter_callout_sequence
editor_sequence
reference_result_plan
no_asset_transition
```

Typical asset roles include:

```text
site_home
feature_entry
parameter_panel
result_image
reference_image
editor_page
edited_result
flat_plan
configured_asset
```

Use registered `category_path`, `asset_role`, relationship groups, orientation,
lineage, and evidence metadata. Do not collapse category and role into one tag.

For strict causal scenes, resolve the registered relationship or invoke an allowed
derivation. Do not infer a relationship from similar filenames alone.
