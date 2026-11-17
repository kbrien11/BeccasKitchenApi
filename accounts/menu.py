"""Server-side copy of the menu prices so order totals are never trusted from the client.

Mirrors beccaskitchen-ui/src/data/meals.ts. Replace with a Meal model once meals live in the DB.
"""
from decimal import Decimal

MENU = {
    1: {"name": "Sunny Sweet Potato", "price": Decimal("5.50")},
    2: {"name": "Garden Pea & Mint", "price": Decimal("5.50")},
    3: {"name": "Apple Cinnamon Oats", "price": Decimal("6.00")},
    4: {"name": "Harvest Chicken Bowl", "price": Decimal("7.00")},
    5: {"name": "Little Lentil Stew", "price": Decimal("6.50")},
    6: {"name": "Rainbow Soft Bites", "price": Decimal("7.00")},
}

FREE_DELIVERY_MINIMUM = Decimal("50.00")
DELIVERY_FEE = Decimal("5.00")
