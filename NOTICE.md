# Third-party notices

Nexus Prime includes or derives from the following third-party material.

## free-exercise-db

Exercise text and photos come from [yuhonas/free-exercise-db](https://github.com/yuhonas/free-exercise-db), released under the Unlicense (public domain). The pinned commit is recorded in `scripts/import_free_exercise_db.py`.

## MuscleMap

The body-map outlines come from [melihcolpan/MuscleMap](https://github.com/melihcolpan/MuscleMap), converted from Swift path data to TypeScript. It is released under the MIT licence:

    MIT License

    Copyright (c) 2026 Melih Colpan

    Permission is hereby granted, free of charge, to any person obtaining a copy
    of this software and associated documentation files (the "Software"), to deal
    in the Software without restriction, including without limitation the rights
    to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
    copies of the Software, and to permit persons to whom the Software is
    furnished to do so, subject to the following conditions:

    The above copyright notice and this permission notice shall be included in all
    copies or substantial portions of the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
    IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
    FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
    AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
    LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
    OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
    SOFTWARE.

## openGym

[openGym](https://github.com/DuarteSantos8/openGym) was used as a design reference only. None of its code, data or media is included.

## USDA FoodData Central

Nutrient values and portion weights for foods come from [USDA FoodData Central](https://fdc.nal.usda.gov/): the SR Legacy (April 2018) and Foundation Foods (October 2026) datasets. The data is in the public domain and published under CC0 1.0 Universal; no permission is needed, and the USDA asks users to name FoodData Central as the source. Suggested citation: U.S. Department of Agriculture, Agricultural Research Service, Beltsville Human Nutrition Research Center. FoodData Central. https://fdc.nal.usda.gov/

Nexus keeps a normalised subset (energy, protein, carbohydrate, fat, fibre per 100 g, and household portions); `scripts/import_usda_fdc.py` builds it. The USDA does not endorse Nexus.
