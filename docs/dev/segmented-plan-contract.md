# Segmented Plan Contract

This note defines the M9 boundary for matches that appear contiguous to a
reader but span multiple PDF text objects or font resources.

## Current Contract

The current `pdf-mutation-plan` schema may report split candidates, but it must
not apply them. Split candidates remain `patchable: false` and are refused by
`--apply-plan`.

For each split candidate, the planner records:

- `split_kind`: one of `cross_text_object`, `cross_font`, or
  `cross_text_object_and_font`
- `segments`: ordered spans with text object index, stream object, font
  resource, glyph start/end offsets, replacement glyph availability, and a
  missing replacement glyph count
- `blockers`: font-specific reasons that prevent a future segmented apply
  plan, without including literal search or replacement text

Same-object, same-font matches remain patchable when the active font can encode
every replacement glyph and the existing exact-plan constraints are satisfied.

## Future Segmented Plan Type

Cross-object or cross-font mutation needs a separate reviewed plan type before
implementation. That future plan should use a distinct schema or plan kind, for
example `pdf-mutation-segmented-plan`, instead of overloading the exact
same-object plan.

A segmented plan must define at least:

- per-segment source fingerprints and glyph spans
- per-segment replacement CIDs already available in that segment's active font
- an explicit ordering contract across text objects and streams
- a layout contract for preserving existing text matrices and advances, or a
  refusal reason when that cannot be done deterministically
- an apply-time validation rule that checks all planned old CIDs before writing
  any output PDF

Until those rules exist, split candidates are audit and planning evidence only.
