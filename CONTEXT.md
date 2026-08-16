# Snack GPT

Snack GPT records food consumption and reports progress toward nutrition targets while keeping food preparation distinct from consumption.

## Language

**Profile**:
A household member whose consumption entries and daily targets are tracked independently.
_Avoid_: User, account

**Food Reference**:
A reusable description of a food and its nutrition values, portions, preparation state, and provenance. It is not evidence that the food was consumed.
_Avoid_: Food item, ingredient record

**Food Alias**:
A profile-approved phrase or barcode that identifies one exact food reference. Recent choices may influence matching but are not food aliases without explicit approval.
_Avoid_: Learned food, default food

**Meal Draft**:
A named or ad hoc collection of food quantities being assembled before consumption is recorded. It may define a total yield by weight or serving count so that only a consumed portion is recorded.
_Avoid_: Recipe, logged meal

**Draft Yield**:
The final cooked weight or serving count across which a meal draft's total nutrition is distributed.
_Avoid_: Recipe weight, batch size

**Consumption Entry**:
A snapshot of a quantity of food recorded as consumed by a profile at an explicit consumption time. Corrections replace or reverse entries without erasing their history.
_Avoid_: Food log, meal entry

**Pending Consumption**:
A reported quantity of food whose nutrition cannot yet be resolved. It remains excluded from confirmed totals until it becomes a consumption entry.
_Avoid_: Estimated entry, failed lookup

**Confirmed Total**:
The nutrition sum of consumption entries for a profile and period. Pending consumption is excluded, and its presence makes the total explicitly incomplete.
_Avoid_: Estimated total, current macros

**Nutrition Source**:
The authority from which a food reference's nutrition values originated, such as a package label, public dataset, or profile-defined value.
_Avoid_: Provider, database

**Daily Target**:
A profile's effective-dated desired calories, protein, carbohydrates, fat, and fiber against which consumption entries are totaled in the profile's local timezone.
_Avoid_: Macro goal, allowance