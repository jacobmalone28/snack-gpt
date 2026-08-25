# Snack-GPT

Snack-GPT is a personal food-logging context for recording one person's food consumption and summarizing it over time. Nutrition coaching and food recommendations are outside this context.

## Language

**Consumption Event**:
A distinct record that the person consumed a specified quantity of a food on a calendar day. Voice creation assigns the current local day; repeated consumption remains separate, and each event retains the food's nutrition at the time of recording. Its food, quantity, or day may be corrected through the web interface, and it may be removed there.
_Avoid_: Food, meal, log entry

**Nutrition Snapshot**:
The calories, protein, carbohydrates, and fat attributed to a Consumption Event when it is recorded.
_Avoid_: Food lookup data, live nutrition

**Food Quantity**:
The consumed amount expressed in grams or a recognized food measure, such as a cup or an egg.
_Avoid_: Amount, serving size

**Consumption Report**:
A single submission containing one or more Consumption Events for the same calendar day. Either every event in the report is recorded or none are.
_Avoid_: Utterance, request, batch

**Calendar Week**:
A Monday-through-Sunday period containing Consumption Events according to their calendar day, using the operating system's current local timezone.
_Avoid_: Rolling week, last seven days

**Weekly Nutrition Totals**:
The descriptive sums of calories, protein, carbohydrates, and fat from Consumption Events in a Calendar Week. They are not targets or recommendations.
_Avoid_: Weekly goals, macro targets