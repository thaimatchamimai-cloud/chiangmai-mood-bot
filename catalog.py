"""Menu structure and category metadata for the Chiang Mai guide bot."""

from __future__ import annotations


CATEGORIES = {
    "healthy_food": {"label": "🥗 Healthy Food", "position": 10},
    "restaurants": {"label": "🍜 Restaurants", "position": 20},
    "junk_food": {"label": "🍔 Junk Food", "position": 30},
    "croissants": {"label": "🥐 Croissants", "position": 40},
    "coffee": {"label": "☕ Coffee", "position": 50},
    "matcha": {"label": "🍵 Matcha", "position": 60},
    "spa_massage": {"label": "💆 Spa & Massage", "position": 70},
    "beauty": {"label": "💅 Beauty", "position": 80},
    "fitness_wellness": {"label": "🧘 Fitness & Wellness", "position": 90},
    "hotels": {"label": "🏨 Hotels", "position": 100},
    "temples": {"label": "🛕 Temples", "position": 110},
    "nature": {"label": "🌿 Nature Spots", "position": 120},
    "parks": {"label": "🌳 Parks", "position": 130},
    "trekking": {"label": "🥾 Hiking Trails", "position": 140},
    "culture": {"label": "🎨 Culture & Cool Places", "position": 150},
    "markets": {"label": "🛍 Markets", "position": 160},
    "bars_wine": {"label": "🍷 Bars & Wine", "position": 170},
}


COFFEE_AREAS = {
    "old_city": "🛕 Old City",
    "nimman_suthep": "🎨 Nimman & Suthep",
    "santitham_chang_phueak": "🎓 Santitham & Chang Phueak",
    "chang_moi_riverside": "🌊 Chang Moi & Riverside",
    "south_airport": "✈️ South & Airport",
    "east_san_kamphaeng": "🌾 East & San Kamphaeng",
    "hang_dong": "🏡 Hang Dong",
    "outside_city": "🌄 Outside Chiang Mai",
}


COFFEE_AREA_DESCRIPTIONS = {
    "old_city": "Temples & history",
    "nimman_suthep": "Trendy & creative",
    "santitham_chang_phueak": "Local & student vibe",
    "chang_moi_riverside": "Riverside & old shophouses",
    "south_airport": "Markets & local life",
    "east_san_kamphaeng": "Arts & quiet local spots",
    "hang_dong": "Family & countryside",
    "outside_city": "Mountains & day trips",
}


COFFEE_AREA_MENU = [
    "old_city",
    "nimman_suthep",
    "santitham_chang_phueak",
    "chang_moi_riverside",
    "hang_dong",
]


AREA_MENU = [
    "old_city",
    "nimman_suthep",
    "santitham_chang_phueak",
    "chang_moi_riverside",
    "south_airport",
    "east_san_kamphaeng",
    "hang_dong",
    "outside_city",
]


GROUPS = {
    "food": {
        "label": "🍽 Food",
        "title": "🍽 <b>Food in Chiang Mai</b>\n\nWhat are you in the mood for?",
        "categories": ["healthy_food", "restaurants", "junk_food", "croissants"],
    },
    "nature_walks": {
        "label": "🌿 Nature & Walks",
        "title": "🌿 <b>Nature & Walks</b>\n\nChoose a category:",
        "categories": ["nature", "parks", "trekking"],
    },
}


MAIN_MENU = [
    {"group": "food"},
    {"category": "coffee"},
    {"category": "matcha"},
    {"category": "spa_massage"},
    {"category": "beauty"},
    {"category": "fitness_wellness"},
    {"category": "hotels"},
    {"category": "temples"},
    {"group": "nature_walks"},
    {"category": "culture"},
    {"category": "markets"},
    {"category": "bars_wine"},
]


CATEGORY_PARENT = {
    slug: group_slug
    for group_slug, group in GROUPS.items()
    for slug in group["categories"]
}
