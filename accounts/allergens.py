"""Allergens we track. Codes are shared with the UI (beccaskitchen-ui/src/data/allergens.ts)."""

# The nine major food allergens in the US (FASTER Act).
ALLERGENS = {
    "milk": "Milk",
    "egg": "Egg",
    "peanut": "Peanut",
    "tree_nut": "Tree nuts",
    "wheat": "Wheat",
    "soy": "Soy",
    "fish": "Fish",
    "shellfish": "Shellfish",
    "sesame": "Sesame",
}

ALLERGEN_CODES = set(ALLERGENS)
