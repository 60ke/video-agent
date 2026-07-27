# Agent Recovery Policy

The Agent may retry a provider timeout, apply an existing Contract repair, or rerun
the smallest affected downstream tool. It must not silently change copy, voice,
asset relationship, Phrase Anchor, or effect identity.

## Actions

| Condition | Action |
|---|---|
| Provider timeout | Retry the same tool within the configured limit |
| Contract field repairable | Use the existing structured repair path |
| Scene semantic conflict | Replan Scene and preserve frozen speech |
| Website state missing | Call `capture_site` |
| Allowed derivative missing | Call `derive_assets`, register, then resolve again |
| Strict relation missing a parent | Stop or request a real parent asset |
| Anchor mismatch | Stop; never use proportional timing fallback |
| Jianying capability missing | Use a registered group-level fallback or stop |
| Draft serialization failure | Preserve the blueprint and rebuild only the draft |

## Forbidden recovery

- Choosing an unrelated asset to make a scene non-empty.
- Converting a causal workflow into a generic result image.
- Removing an SFX or subtitle merely to hide an anchor error.
- Moving a visual hit to a nearby word by eye.
- Returning a guessed video or draft path.
- Retrying indefinitely.
