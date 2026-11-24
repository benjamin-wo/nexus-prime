# Meal photo eval

Measures how far the photo flow's calorie range is from a weighed reference. It needs your own
photos: this repository is public, and a photo belongs to whoever took it, so none are committed
and none may be copied in from the web (no openGym, no stock or social-media images).

## Target

Start with **30** weighed plates. The research recommends 100 to 200 hawker plates before trusting
the numbers (photo-only estimates miss by about 33 to 47%, and fat is undercounted), so grow it
from there. Cover rice and noodle plates, soups, fried and curry dishes, drinks and desserts.

## How to add a meal

1. Weigh each component on a kitchen scale before eating, and write the weights down.
2. Work out the reference energy from a source you can cite, such as the food's USDA FoodData
   Central entry or the packet label, times the weights. Do not use an app's guess.
3. Photograph the plate from above, in ordinary light, as you would send it to Nexus. Put the
   file in this folder (`src/nexus/evals/meals/`). Do not commit it unless you are happy to
   publish it; `eval-results/` and local copies are git-ignored.
4. Add one entry to `manifest.json`:

```json
{
  "file": "plate-001.jpg",
  "items": ["white rice", "fried egg"],
  "grams": [180, 50],
  "kcal_reference": 420,
  "source": "weighed on a kitchen scale; kcal from USDA FDC per 100 g x grams"
}
```

`items` and `grams` have the same length and say what is on the plate (the scorer does not read
them: they are for you and for checking what the reader saw). `kcal_reference` is the reference
energy of the whole plate in kcal.

## Run

```
python -m nexus.evals.meal_photos            # needs OPENROUTER_API_KEY and a vision model
python -m nexus.evals.meal_photos --check    # only validate the manifest, no model, no cost
```

With no photos listed it prints "no photos yet" and exits cleanly.

## What it reports

For each photo the reader's items go through the same code as a logged meal (food database,
photo estimates of plus or minus 30%). Over all photos:

* **MAPE**: the mean of |point kcal - reference| / reference, as a percentage (lower is better).
* **Coverage**: the share of photos whose reference lies inside the range the user would be
  shown (higher is better; the range is meant to hold about 80%).
* Photos where an item could not be found in the food database are counted and listed, and are
  left out of the two figures.
