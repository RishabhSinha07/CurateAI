"""
Seed script for Wellbeing Nutrition products.

Run with: python -m app.db.seed_wellbeing

Data sourced from: https://wellbeingnutrition.com/
"""

import asyncio
from decimal import Decimal

from sqlalchemy import select, text

from app.db.models import Domain, Product
from app.db.session import async_session_factory

# =============================================================================
# DOMAINS - Organized by product format and health goal
# =============================================================================

DOMAINS = [
    # Root: Wellness & Supplements
    {
        "name": "Wellness",
        "slug": "wellness",
        "parent_slug": None,
        "config": {
            "required_slots": ["health_goal"],
            "optional_slots": ["dietary_preference", "budget"],
            "search_filters": ["is_vegan", "is_sugar_free"],
            "safety_disclaimers": [
                "These products are dietary supplements and not intended to diagnose, treat, cure, or prevent any disease.",
                "Consult your healthcare provider before starting any supplement regimen.",
                "Keep out of reach of children.",
            ],
        },
        "system_persona": (
            "You are a knowledgeable wellness consultant specializing in nutritional supplements. "
            "Help users find the right supplements based on their health goals. "
            "Always recommend consulting a healthcare provider for medical conditions."
        ),
    },
    # Child: Melts (Oral Thin Strips)
    {
        "name": "Melts",
        "slug": "melts",
        "parent_slug": "wellness",
        "config": {
            "required_slots": ["health_goal"],
            "optional_slots": ["flavor_preference", "budget"],
            "search_filters": ["is_vegan", "is_sugar_free", "is_allergen_free"],
            "safety_disclaimers": [
                "Oral strips dissolve on the tongue for fast absorption.",
            ],
        },
        "system_persona": (
            "You are a supplement specialist focusing on Melts oral thin strips - "
            "a convenient, fast-absorbing format that's plant-based and sugar-free. "
            "Help users find the right Melts product for their health goals like energy, "
            "sleep, hair health, or vitamin supplementation."
        ),
    },
    # Child: Collagen
    {
        "name": "Collagen",
        "slug": "collagen",
        "parent_slug": "wellness",
        "config": {
            "required_slots": ["skin_concern", "collagen_preference"],
            "optional_slots": ["flavor_preference", "budget"],
            "search_filters": ["collagen_type", "is_vegan"],
            "safety_disclaimers": [
                "Marine collagen is derived from fish. Not suitable for those with fish allergies.",
                "Results may vary. Consistent use for 8-12 weeks recommended.",
            ],
        },
        "system_persona": (
            "You are a beauty and skin health specialist focusing on collagen supplements. "
            "Help users choose between marine collagen and vegan collagen builders based on "
            "their skin goals (anti-aging, hydration, elasticity) and dietary preferences."
        ),
    },
    # Child: Slow Capsules
    {
        "name": "Slow Capsules",
        "slug": "slow-capsules",
        "parent_slug": "wellness",
        "config": {
            "required_slots": ["health_goal", "gender"],
            "optional_slots": ["age_group", "budget"],
            "search_filters": ["target_gender", "health_category"],
            "safety_disclaimers": [
                "Slow-release capsules provide sustained nutrient delivery over 8 hours.",
                "Take with food for best absorption.",
            ],
        },
        "system_persona": (
            "You are a supplement specialist focusing on Slow Capsules - "
            "a sustained-release format that delivers nutrients over 8 hours. "
            "Help users find targeted solutions for gut health, weight management, "
            "multivitamins, and specific health conditions."
        ),
    },
    # Child: Effervescent
    {
        "name": "Effervescent",
        "slug": "effervescent",
        "parent_slug": "wellness",
        "config": {
            "required_slots": ["health_goal"],
            "optional_slots": ["flavor_preference", "budget"],
            "search_filters": ["health_category"],
            "safety_disclaimers": [
                "Dissolve tablet completely in water before drinking.",
            ],
        },
        "system_persona": (
            "You are a supplement specialist focusing on effervescent tablets - "
            "a refreshing, fast-absorbing format that dissolves in water. "
            "Help users find products for immunity, gut health, skin glow, and detox."
        ),
    },
]

# =============================================================================
# PRODUCTS - Wellbeing Nutrition catalog
# =============================================================================

# INR to USD conversion (approximate)
INR_TO_USD = 0.012

# Base URLs for Wellbeing Nutrition
BASE_URL = "https://wellbeingnutrition.com"
CDN_URL = "https://cdn.shopify.com/s/files/1/0444/4288/7884/products"


def inr_to_usd(inr_price: int) -> Decimal:
    """Convert INR to USD, rounded to 2 decimal places."""
    return Decimal(str(round(inr_price * INR_TO_USD, 2)))




PRODUCTS = [
    # =========================================================================
    # MELTS - Oral Thin Strips
    # =========================================================================
    {
        "domain_slug": "melts",
        "sku": "WBN-MELTS-B12",
        "name": "Vitamin B12 Melts",
        "brand": "Wellbeing Nutrition",
        "description": (
            "Fast-dissolving oral strips with Vitamin B12, Folate, Brahmi, and Curcumin. "
            "Boosts energy levels, reduces fatigue, and enhances nerve function. "
            "Plant-based, vegan, and sugar-free formula that dissolves on your tongue "
            "for rapid absorption without water."
        ),
        "price": inr_to_usd(479),
        "inventory_count": 200,
        "attributes": {
            "format": "oral_strips",
            "health_goal": ["energy", "fatigue_reduction", "nerve_health"],
            "key_ingredients": ["Vitamin B12", "Folate", "Brahmi", "Curcumin"],
            "is_vegan": True,
            "is_sugar_free": True,
            "is_allergen_free": True,
            "pack_size": 30,
            "dosage": "1 strip daily",
        },
    },
    {
        "domain_slug": "melts",
        "sku": "WBN-MELTS-D3",
        "name": "Natural Vitamin D3 Melts",
        "brand": "Wellbeing Nutrition",
        "description": (
            "Plant-based Vitamin D3 oral strips for bone health and immune support. "
            "Sourced from lichen, making it 100% vegan. Dissolves instantly on tongue "
            "for superior absorption compared to traditional tablets."
        ),
        "price": inr_to_usd(479),
        "inventory_count": 180,
        "attributes": {
            "format": "oral_strips",
            "health_goal": ["bone_health", "immunity", "calcium_absorption"],
            "key_ingredients": ["Vitamin D3 (from Lichen)"],
            "is_vegan": True,
            "is_sugar_free": True,
            "is_allergen_free": True,
            "pack_size": 30,
            "dosage": "1 strip daily",
        },
    },
    {
        "domain_slug": "melts",
        "sku": "WBN-MELTS-SLEEP",
        "name": "Restful Sleep Melts",
        "brand": "Wellbeing Nutrition",
        "description": (
            "Melatonin-infused oral strips (10mg) for natural, restful sleep. "
            "Helps regulate sleep cycle, reduces time to fall asleep, and improves "
            "sleep quality. Non-habit forming formula with no morning grogginess."
        ),
        "price": inr_to_usd(479),
        "inventory_count": 150,
        "attributes": {
            "format": "oral_strips",
            "health_goal": ["sleep", "relaxation", "jet_lag"],
            "key_ingredients": ["Melatonin 10mg"],
            "is_vegan": True,
            "is_sugar_free": True,
            "is_allergen_free": True,
            "pack_size": 30,
            "dosage": "1 strip 30 mins before bed",
        },
    },
    {
        "domain_slug": "melts",
        "sku": "WBN-MELTS-ENERGY",
        "name": "Instant Energy Melts",
        "brand": "Wellbeing Nutrition",
        "description": (
            "Natural caffeine from green tea combined with B-vitamins for steady, "
            "reliable energy without jitters or crash. Contains Vitamins B5, B6, B12, "
            "and Vitamin E. Perfect for afternoon slumps or pre-workout boost."
        ),
        "price": inr_to_usd(479),
        "inventory_count": 220,
        "attributes": {
            "format": "oral_strips",
            "health_goal": ["energy", "focus", "alertness"],
            "key_ingredients": ["Green Tea Caffeine", "Vitamin B5", "Vitamin B6", "Vitamin B12", "Vitamin E"],
            "is_vegan": True,
            "is_sugar_free": True,
            "is_allergen_free": True,
            "caffeine_mg": 50,
            "pack_size": 30,
            "dosage": "1 strip as needed",
        },
    },
    {
        "domain_slug": "melts",
        "sku": "WBN-MELTS-HAIR",
        "name": "Healthy Hair Melts",
        "brand": "Wellbeing Nutrition",
        "description": (
            "Biotin-enriched oral strips for stronger, healthier hair. Supports keratin "
            "production and nutrient absorption for visibly thicker hair. Also supports "
            "nail strength and skin health."
        ),
        "price": inr_to_usd(479),
        "inventory_count": 170,
        "attributes": {
            "format": "oral_strips",
            "health_goal": ["hair_health", "nail_strength", "biotin_supplement"],
            "key_ingredients": ["Biotin", "Zinc", "Selenium"],
            "is_vegan": True,
            "is_sugar_free": True,
            "is_allergen_free": True,
            "pack_size": 30,
            "dosage": "1 strip daily",
        },
    },
    {
        "domain_slug": "melts",
        "sku": "WBN-MELTS-HAIRFALL",
        "name": "Hair Fall Control Melts",
        "brand": "Wellbeing Nutrition",
        "description": (
            "Advanced formula with Cynatine® Keratin to increase collagen thickness "
            "and reduce hair fall. Strengthens hair follicles from within. "
            "Clinically studied ingredients for visible results in 8 weeks."
        ),
        "price": inr_to_usd(479),
        "inventory_count": 160,
        "attributes": {
            "format": "oral_strips",
            "health_goal": ["hair_fall", "hair_strength", "hair_growth"],
            "key_ingredients": ["Cynatine Keratin", "Biotin", "Zinc", "Iron"],
            "is_vegan": True,
            "is_sugar_free": True,
            "is_allergen_free": True,
            "pack_size": 30,
            "dosage": "1 strip daily",
        },
    },
    {
        "domain_slug": "melts",
        "sku": "WBN-MELTS-CALM",
        "name": "Calm & Relaxation Melts",
        "brand": "Wellbeing Nutrition",
        "description": (
            "Suntheanine® L-Theanine and Magnesium for stress relief and calm focus. "
            "Promotes relaxation without drowsiness. Perfect for high-stress days "
            "or when you need to unwind naturally."
        ),
        "price": inr_to_usd(479),
        "inventory_count": 140,
        "attributes": {
            "format": "oral_strips",
            "health_goal": ["stress_relief", "calm", "relaxation", "focus"],
            "key_ingredients": ["Suntheanine L-Theanine", "Magnesium"],
            "is_vegan": True,
            "is_sugar_free": True,
            "is_allergen_free": True,
            "pack_size": 30,
            "dosage": "1 strip as needed",
        },
    },
    {
        "domain_slug": "melts",
        "sku": "WBN-MELTS-IRON",
        "name": "Vital Iron Melts",
        "brand": "Wellbeing Nutrition",
        "description": (
            "Gentle iron supplementation for hemoglobin production and anemia prevention. "
            "Nano-iron technology for maximum absorption without stomach upset. "
            "Ideal for women, vegetarians, and those with iron deficiency."
        ),
        "price": inr_to_usd(479),
        "inventory_count": 190,
        "attributes": {
            "format": "oral_strips",
            "health_goal": ["iron_supplement", "anemia_prevention", "energy"],
            "key_ingredients": ["Nano Iron", "Vitamin C", "Folic Acid"],
            "is_vegan": True,
            "is_sugar_free": True,
            "is_allergen_free": True,
            "target_audience": ["women", "vegetarians"],
            "pack_size": 30,
            "dosage": "1 strip daily",
        },
    },
    {
        "domain_slug": "melts",
        "sku": "WBN-MELTS-TESTO",
        "name": "Testo Power Melts",
        "brand": "Wellbeing Nutrition",
        "description": (
            "Natural testosterone support with Testofen® fenugreek extract. "
            "Enhances vitality, strength, and energy in men. Botanical support "
            "for healthy testosterone levels and overall male wellness."
        ),
        "price": inr_to_usd(479),
        "inventory_count": 130,
        "attributes": {
            "format": "oral_strips",
            "health_goal": ["testosterone_support", "vitality", "strength", "male_wellness"],
            "key_ingredients": ["Testofen Fenugreek", "Ashwagandha", "Zinc"],
            "is_vegan": True,
            "is_sugar_free": True,
            "is_allergen_free": True,
            "target_gender": "male",
            "pack_size": 30,
            "dosage": "1 strip daily",
        },
    },
    {
        "domain_slug": "melts",
        "sku": "WBN-MELTS-MULTI",
        "name": "Multivitamin Melts",
        "brand": "Wellbeing Nutrition",
        "description": (
            "Complete daily multivitamin in a convenient oral strip format. "
            "Contains essential vitamins and minerals for overall health. "
            "Easy to take, no water needed, perfect for busy lifestyles."
        ),
        "price": inr_to_usd(479),
        "inventory_count": 250,
        "attributes": {
            "format": "oral_strips",
            "health_goal": ["daily_nutrition", "immunity", "energy", "overall_health"],
            "key_ingredients": ["Vitamin A", "Vitamin C", "Vitamin D", "Vitamin E", "B-Complex", "Zinc"],
            "is_vegan": True,
            "is_sugar_free": True,
            "is_allergen_free": True,
            "pack_size": 30,
            "dosage": "1 strip daily",
        },
    },
    {
        "domain_slug": "melts",
        "sku": "WBN-MELTS-GUT",
        "name": "Healthy Gut Melts",
        "brand": "Wellbeing Nutrition",
        "description": (
            "Probiotic oral strips for digestive health and gut balance. "
            "Supports healthy gut flora, aids digestion, and boosts immunity. "
            "Convenient alternative to refrigerated probiotic supplements."
        ),
        "price": inr_to_usd(479),
        "inventory_count": 145,
        "attributes": {
            "format": "oral_strips",
            "health_goal": ["gut_health", "digestion", "immunity", "bloating_relief"],
            "key_ingredients": ["Probiotics", "Prebiotics", "Digestive Enzymes"],
            "is_vegan": True,
            "is_sugar_free": True,
            "is_allergen_free": True,
            "pack_size": 30,
            "dosage": "1 strip daily",
        },
    },

    # =========================================================================
    # COLLAGEN - Marine and Vegan
    # =========================================================================
    {
        "domain_slug": "collagen",
        "sku": "WBN-COL-PURE",
        "name": "Pure Korean Marine Collagen Peptides",
        "brand": "Wellbeing Nutrition",
        "description": (
            "Premium unflavored marine collagen peptides sourced from Korean deep-sea fish. "
            "Type I & III collagen for skin firmness, elasticity, and hydration. "
            "Low molecular weight for superior absorption. Combat signs of aging naturally."
        ),
        "price": inr_to_usd(1439),
        "inventory_count": 100,
        "attributes": {
            "format": "powder",
            "collagen_type": "marine",
            "skin_concern": ["anti_aging", "firmness", "elasticity", "hydration"],
            "key_ingredients": ["Type I Collagen", "Type III Collagen", "Hyaluronic Acid"],
            "flavor": "unflavored",
            "is_vegan": False,
            "contains_fish": True,
            "serving_size": "10g",
            "servings_per_pack": 25,
        },
    },
    {
        "domain_slug": "collagen",
        "sku": "WBN-COL-GLOW-TROPICAL",
        "name": "Glow Korean Marine Collagen Peptides - Tropical Bliss",
        "brand": "Wellbeing Nutrition",
        "description": (
            "Delicious tropical-flavored marine collagen for radiant, glowing skin. "
            "Enhanced with Vitamin C and Hyaluronic Acid for maximum collagen synthesis. "
            "Promotes skin hydration, elasticity, and a youthful glow."
        ),
        "price": inr_to_usd(1599),
        "inventory_count": 85,
        "attributes": {
            "format": "powder",
            "collagen_type": "marine",
            "skin_concern": ["glow", "hydration", "elasticity", "radiance"],
            "key_ingredients": ["Marine Collagen", "Vitamin C", "Hyaluronic Acid"],
            "flavor": "tropical_bliss",
            "is_vegan": False,
            "contains_fish": True,
            "serving_size": "10g",
            "servings_per_pack": 25,
        },
    },
    {
        "domain_slug": "collagen",
        "sku": "WBN-COL-BEAUTY-MANGO",
        "name": "Beauty Korean Marine Collagen - Mango Peach",
        "brand": "Wellbeing Nutrition",
        "description": (
            "Beauty-focused collagen with a refreshing mango peach flavor. "
            "Supports skin health, reduces fine lines, and promotes hair and nail strength. "
            "Korean marine collagen with added biotin for complete beauty nutrition."
        ),
        "price": inr_to_usd(1599),
        "inventory_count": 90,
        "attributes": {
            "format": "powder",
            "collagen_type": "marine",
            "skin_concern": ["fine_lines", "skin_health", "hair_nails", "beauty"],
            "key_ingredients": ["Marine Collagen", "Biotin", "Vitamin E"],
            "flavor": "mango_peach",
            "is_vegan": False,
            "contains_fish": True,
            "serving_size": "10g",
            "servings_per_pack": 25,
        },
    },
    {
        "domain_slug": "collagen",
        "sku": "WBN-COL-GLOW-GLUTA",
        "name": "Glow Marine Collagen with Glutathione & Vitamin C",
        "brand": "Wellbeing Nutrition",
        "description": (
            "Advanced skin glow formula combining marine collagen with liposomal glutathione "
            "and Vitamin C. Brightens skin tone, reduces pigmentation, and provides "
            "antioxidant protection. Valencia orange flavor."
        ),
        "price": inr_to_usd(1599),
        "inventory_count": 75,
        "attributes": {
            "format": "powder",
            "collagen_type": "marine",
            "skin_concern": ["brightening", "pigmentation", "antioxidant", "glow"],
            "key_ingredients": ["Marine Collagen", "Liposomal Glutathione", "Vitamin C"],
            "flavor": "valencia_orange",
            "is_vegan": False,
            "contains_fish": True,
            "serving_size": "10g",
            "servings_per_pack": 25,
        },
    },
    {
        "domain_slug": "collagen",
        "sku": "WBN-COL-MATCHA",
        "name": "Matcha Collagen",
        "brand": "Wellbeing Nutrition",
        "description": (
            "Unique blend of marine collagen with Japanese matcha green tea. "
            "Combines skin benefits of collagen with antioxidant power of matcha. "
            "Supports skin health while providing calm, focused energy."
        ),
        "price": inr_to_usd(1359),
        "inventory_count": 60,
        "attributes": {
            "format": "powder",
            "collagen_type": "marine",
            "skin_concern": ["antioxidant", "skin_health", "energy"],
            "key_ingredients": ["Marine Collagen", "Japanese Matcha", "L-Theanine"],
            "flavor": "matcha",
            "is_vegan": False,
            "contains_fish": True,
            "caffeine_mg": 30,
            "serving_size": "10g",
            "servings_per_pack": 25,
        },
    },
    {
        "domain_slug": "collagen",
        "sku": "WBN-COL-BEAUTY-STRAW",
        "name": "Beauty Collagen - Strawberry Watermelon",
        "brand": "Wellbeing Nutrition",
        "description": (
            "Refreshing strawberry watermelon flavored collagen for beauty enhancement. "
            "Supports skin elasticity, reduces wrinkles, and promotes a youthful appearance. "
            "Perfect summer drink for your beauty routine."
        ),
        "price": inr_to_usd(1599),
        "inventory_count": 80,
        "attributes": {
            "format": "powder",
            "collagen_type": "marine",
            "skin_concern": ["wrinkles", "elasticity", "youthful_skin"],
            "key_ingredients": ["Marine Collagen", "Vitamin C", "Hyaluronic Acid"],
            "flavor": "strawberry_watermelon",
            "is_vegan": False,
            "contains_fish": True,
            "serving_size": "10g",
            "servings_per_pack": 25,
        },
    },
    {
        "domain_slug": "collagen",
        "sku": "WBN-COL-VEGAN-BERRY",
        "name": "Vegan Pro Collagen Builder - Mixed Berries",
        "brand": "Wellbeing Nutrition",
        "description": (
            "Plant-based collagen builder for vegans and vegetarians. "
            "Contains collagen-boosting amino acids, Vitamin C, and plant extracts "
            "that stimulate your body's natural collagen production. 100% vegan formula."
        ),
        "price": inr_to_usd(1259),
        "inventory_count": 95,
        "attributes": {
            "format": "powder",
            "collagen_type": "vegan_builder",
            "skin_concern": ["collagen_boost", "skin_health", "anti_aging"],
            "key_ingredients": ["Plant Amino Acids", "Vitamin C", "Bamboo Silica", "Amla Extract"],
            "flavor": "mixed_berries",
            "is_vegan": True,
            "contains_fish": False,
            "serving_size": "10g",
            "servings_per_pack": 25,
        },
    },
    {
        "domain_slug": "collagen",
        "sku": "WBN-COL-VEGAN-LEMON",
        "name": "Vegan Pro Collagen Builder - Lemon Lime",
        "brand": "Wellbeing Nutrition",
        "description": (
            "Zesty lemon lime flavored vegan collagen builder. "
            "Stimulates natural collagen production with plant-based ingredients. "
            "Perfect for those who want collagen benefits without animal products."
        ),
        "price": inr_to_usd(1439),
        "inventory_count": 70,
        "attributes": {
            "format": "powder",
            "collagen_type": "vegan_builder",
            "skin_concern": ["collagen_boost", "skin_health", "hydration"],
            "key_ingredients": ["Plant Amino Acids", "Vitamin C", "Hyaluronic Acid", "Silica"],
            "flavor": "lemon_lime",
            "is_vegan": True,
            "contains_fish": False,
            "serving_size": "10g",
            "servings_per_pack": 25,
        },
    },

    # =========================================================================
    # SLOW CAPSULES - Sustained Release
    # =========================================================================
    {
        "domain_slug": "slow-capsules",
        "sku": "WBN-SLOW-MAG",
        "name": "Triple Magnesium Complex Slow",
        "brand": "Wellbeing Nutrition",
        "description": (
            "Three forms of highly bioavailable magnesium in sustained-release capsules. "
            "Supports muscle function, nerve health, sleep quality, and stress management. "
            "8-hour slow release for optimal absorption without digestive discomfort."
        ),
        "price": inr_to_usd(1119),
        "inventory_count": 120,
        "attributes": {
            "format": "slow_capsules",
            "health_goal": ["muscle_function", "nerve_health", "sleep", "stress"],
            "key_ingredients": ["Magnesium Glycinate", "Magnesium Taurate", "Magnesium Citrate"],
            "target_gender": "unisex",
            "capsules_per_pack": 60,
            "dosage": "1 capsule twice daily",
            "release_hours": 8,
        },
    },
    {
        "domain_slug": "slow-capsules",
        "sku": "WBN-SLOW-MULTI-HER",
        "name": "Multi + Omega for Her Slow",
        "brand": "Wellbeing Nutrition",
        "description": (
            "Complete women's multivitamin with Omega-3 in slow-release formula. "
            "Tailored for women's nutritional needs including iron, calcium, and folate. "
            "Supports energy, hormonal balance, skin health, and overall vitality."
        ),
        "price": inr_to_usd(1119),
        "inventory_count": 110,
        "attributes": {
            "format": "slow_capsules",
            "health_goal": ["womens_health", "energy", "hormonal_balance", "skin_health"],
            "key_ingredients": ["Multivitamins", "Omega-3", "Iron", "Calcium", "Folate", "Evening Primrose"],
            "target_gender": "female",
            "capsules_per_pack": 60,
            "dosage": "1 capsule twice daily",
            "release_hours": 8,
        },
    },
    {
        "domain_slug": "slow-capsules",
        "sku": "WBN-SLOW-MULTI-HIM",
        "name": "Multi + Omega for Him Slow",
        "brand": "Wellbeing Nutrition",
        "description": (
            "Complete men's multivitamin with Omega-3 in slow-release formula. "
            "Formulated for men's health with zinc, selenium, and lycopene. "
            "Supports energy, muscle function, heart health, and prostate wellness."
        ),
        "price": inr_to_usd(1119),
        "inventory_count": 105,
        "attributes": {
            "format": "slow_capsules",
            "health_goal": ["mens_health", "energy", "muscle_function", "heart_health"],
            "key_ingredients": ["Multivitamins", "Omega-3", "Zinc", "Selenium", "Lycopene"],
            "target_gender": "male",
            "capsules_per_pack": 60,
            "dosage": "1 capsule twice daily",
            "release_hours": 8,
        },
    },
    {
        "domain_slug": "slow-capsules",
        "sku": "WBN-SLOW-PROBIOTIC",
        "name": "Daily Probiotic Slow",
        "brand": "Wellbeing Nutrition",
        "description": (
            "Multi-strain probiotic with 50 billion CFU in delayed-release capsules. "
            "Survives stomach acid for delivery to the intestines. "
            "Supports digestive health, immunity, and gut-brain connection."
        ),
        "price": inr_to_usd(1119),
        "inventory_count": 95,
        "attributes": {
            "format": "slow_capsules",
            "health_goal": ["gut_health", "immunity", "digestion", "bloating"],
            "key_ingredients": ["50 Billion CFU Probiotics", "Prebiotics", "Lactobacillus", "Bifidobacterium"],
            "target_gender": "unisex",
            "capsules_per_pack": 60,
            "dosage": "1 capsule daily",
            "cfu_count": "50 billion",
        },
    },
    {
        "domain_slug": "slow-capsules",
        "sku": "WBN-SLOW-BURN",
        "name": "Burn Slow",
        "brand": "Wellbeing Nutrition",
        "description": (
            "Natural weight management support with green tea extract and L-carnitine. "
            "Boosts metabolism, supports fat burning, and provides sustained energy. "
            "Slow-release formula for all-day metabolic support."
        ),
        "price": inr_to_usd(1119),
        "inventory_count": 85,
        "attributes": {
            "format": "slow_capsules",
            "health_goal": ["weight_management", "metabolism", "fat_burning", "energy"],
            "key_ingredients": ["Green Tea Extract", "L-Carnitine", "Garcinia Cambogia", "CLA"],
            "target_gender": "unisex",
            "capsules_per_pack": 60,
            "dosage": "1 capsule twice daily",
            "release_hours": 8,
        },
    },
    {
        "domain_slug": "slow-capsules",
        "sku": "WBN-SLOW-HSN",
        "name": "Hair, Skin & Nails Slow",
        "brand": "Wellbeing Nutrition",
        "description": (
            "Comprehensive beauty supplement with biotin, collagen peptides, and keratin. "
            "Supports hair growth, skin elasticity, and nail strength. "
            "Slow-release for sustained nutrient delivery throughout the day."
        ),
        "price": inr_to_usd(1119),
        "inventory_count": 100,
        "attributes": {
            "format": "slow_capsules",
            "health_goal": ["hair_health", "skin_health", "nail_strength", "beauty"],
            "key_ingredients": ["Biotin", "Collagen Peptides", "Keratin", "Vitamin E", "Zinc"],
            "target_gender": "unisex",
            "capsules_per_pack": 60,
            "dosage": "1 capsule twice daily",
            "release_hours": 8,
        },
    },
    {
        "domain_slug": "slow-capsules",
        "sku": "WBN-SLOW-OMEGA3",
        "name": "4x Strength Omega 3 Fish Oil",
        "brand": "Wellbeing Nutrition",
        "description": (
            "High-potency Omega-3 with 4x concentration of EPA and DHA. "
            "Supports heart health, brain function, joint mobility, and eye health. "
            "Enteric coated to prevent fishy burps and improve absorption."
        ),
        "price": inr_to_usd(1119),
        "inventory_count": 90,
        "attributes": {
            "format": "slow_capsules",
            "health_goal": ["heart_health", "brain_health", "joint_health", "eye_health"],
            "key_ingredients": ["EPA", "DHA", "Fish Oil"],
            "target_gender": "unisex",
            "capsules_per_pack": 60,
            "dosage": "1 capsule daily",
            "is_vegan": False,
            "contains_fish": True,
        },
    },
    {
        "domain_slug": "slow-capsules",
        "sku": "WBN-SLOW-PCOS",
        "name": "PCOS Balance Slow",
        "brand": "Wellbeing Nutrition",
        "description": (
            "Specialized formula for women with Polycystic Ovary Syndrome. "
            "Contains Myo-inositol, D-chiro-inositol, and chromium to support "
            "hormonal balance, insulin sensitivity, and menstrual regularity."
        ),
        "price": inr_to_usd(1119),
        "inventory_count": 75,
        "attributes": {
            "format": "slow_capsules",
            "health_goal": ["pcos_support", "hormonal_balance", "insulin_sensitivity", "menstrual_health"],
            "key_ingredients": ["Myo-Inositol", "D-Chiro-Inositol", "Chromium", "Folate"],
            "target_gender": "female",
            "health_condition": "pcos",
            "capsules_per_pack": 60,
            "dosage": "1 capsule twice daily",
            "release_hours": 8,
        },
    },
    {
        "domain_slug": "slow-capsules",
        "sku": "WBN-SLOW-LIVER",
        "name": "Liver Detox Slow",
        "brand": "Wellbeing Nutrition",
        "description": (
            "Natural liver support with milk thistle, NAC, and artichoke extract. "
            "Supports liver detoxification, reduces oxidative stress, and promotes "
            "healthy liver function. Ideal for those with lifestyle-related liver concerns."
        ),
        "price": inr_to_usd(979),
        "inventory_count": 80,
        "attributes": {
            "format": "slow_capsules",
            "health_goal": ["liver_health", "detox", "antioxidant"],
            "key_ingredients": ["Milk Thistle", "NAC", "Artichoke Extract", "Dandelion Root"],
            "target_gender": "unisex",
            "capsules_per_pack": 60,
            "dosage": "1 capsule twice daily",
            "release_hours": 8,
        },
    },
    {
        "domain_slug": "slow-capsules",
        "sku": "WBN-SLOW-DIABETES",
        "name": "Diabetes Care Slow",
        "brand": "Wellbeing Nutrition",
        "description": (
            "Blood sugar management support with berberine, chromium, and bitter melon. "
            "Helps maintain healthy blood glucose levels and supports insulin function. "
            "Slow-release for consistent blood sugar support throughout the day."
        ),
        "price": inr_to_usd(979),
        "inventory_count": 70,
        "attributes": {
            "format": "slow_capsules",
            "health_goal": ["blood_sugar", "diabetes_support", "insulin_function"],
            "key_ingredients": ["Berberine", "Chromium", "Bitter Melon", "Fenugreek"],
            "target_gender": "unisex",
            "health_condition": "diabetes",
            "capsules_per_pack": 60,
            "dosage": "1 capsule twice daily",
            "release_hours": 8,
        },
    },

    # =========================================================================
    # EFFERVESCENT TABLETS
    # =========================================================================
    {
        "domain_slug": "effervescent",
        "sku": "WBN-EFF-PROBIO",
        "name": "Probiotic + Prebiotic Effervescent",
        "brand": "Wellbeing Nutrition",
        "description": (
            "Fizzy probiotic tablets with prebiotics for complete gut health. "
            "Refreshing orange flavor makes gut health enjoyable. "
            "Supports digestion, reduces bloating, and boosts immunity."
        ),
        "price": inr_to_usd(559),
        "inventory_count": 130,
        "attributes": {
            "format": "effervescent",
            "health_goal": ["gut_health", "digestion", "bloating", "immunity"],
            "key_ingredients": ["Probiotics", "Prebiotics", "Digestive Enzymes"],
            "flavor": "orange",
            "tablets_per_pack": 20,
            "dosage": "1 tablet daily in water",
        },
    },
    {
        "domain_slug": "effervescent",
        "sku": "WBN-EFF-GREENS",
        "name": "Daily Greens Effervescent",
        "brand": "Wellbeing Nutrition",
        "description": (
            "Supergreens powder in convenient effervescent form. "
            "Contains spirulina, chlorella, wheatgrass, and 39+ ingredients. "
            "Alkalizes body, boosts energy, and provides daily vegetable nutrition."
        ),
        "price": inr_to_usd(439),
        "inventory_count": 115,
        "attributes": {
            "format": "effervescent",
            "health_goal": ["daily_nutrition", "energy", "detox", "alkaline"],
            "key_ingredients": ["Spirulina", "Chlorella", "Wheatgrass", "Barley Grass"],
            "flavor": "lemon_mint",
            "is_vegan": True,
            "tablets_per_pack": 15,
            "dosage": "1 tablet daily in water",
        },
    },
    {
        "domain_slug": "effervescent",
        "sku": "WBN-EFF-GLUTA",
        "name": "Glutathione Skin Fuel Effervescent",
        "brand": "Wellbeing Nutrition",
        "description": (
            "Master antioxidant glutathione with Vitamin C for radiant skin. "
            "Reduces pigmentation, brightens skin tone, and provides cellular protection. "
            "Japanese glutathione technology for maximum absorption."
        ),
        "price": inr_to_usd(539),
        "inventory_count": 100,
        "attributes": {
            "format": "effervescent",
            "health_goal": ["skin_brightening", "pigmentation", "antioxidant", "glow"],
            "key_ingredients": ["Glutathione", "Vitamin C", "Alpha Lipoic Acid"],
            "flavor": "orange",
            "tablets_per_pack": 15,
            "dosage": "1 tablet daily in water",
        },
    },
    {
        "domain_slug": "effervescent",
        "sku": "WBN-EFF-ACV",
        "name": "Apple Cider Vinegar with Garcinia Effervescent",
        "brand": "Wellbeing Nutrition",
        "description": (
            "Apple cider vinegar with mother, enhanced with Garcinia and Pomegranate. "
            "Supports weight management, digestion, and metabolism. "
            "All the benefits of ACV without the harsh taste."
        ),
        "price": inr_to_usd(349),
        "inventory_count": 140,
        "attributes": {
            "format": "effervescent",
            "health_goal": ["weight_management", "digestion", "metabolism", "detox"],
            "key_ingredients": ["Apple Cider Vinegar", "Garcinia Cambogia", "Pomegranate", "Vitamin B6"],
            "flavor": "pomegranate",
            "tablets_per_pack": 15,
            "dosage": "1 tablet daily in water",
        },
    },
    {
        "domain_slug": "effervescent",
        "sku": "WBN-EFF-VITC",
        "name": "Organic Vitamin C + Zinc Effervescent",
        "brand": "Wellbeing Nutrition",
        "description": (
            "Plant-based Vitamin C from Amla with Zinc for immunity support. "
            "1000mg Vitamin C per tablet for powerful antioxidant protection. "
            "Supports immune function, skin health, and iron absorption."
        ),
        "price": inr_to_usd(319),
        "inventory_count": 160,
        "attributes": {
            "format": "effervescent",
            "health_goal": ["immunity", "antioxidant", "skin_health"],
            "key_ingredients": ["Vitamin C 1000mg", "Zinc", "Amla Extract"],
            "flavor": "orange",
            "is_vegan": True,
            "tablets_per_pack": 20,
            "dosage": "1 tablet daily in water",
        },
    },
]


async def seed_domains(session) -> dict[str, Domain]:
    """Create domain hierarchy and return slug->domain mapping."""
    slug_to_domain: dict[str, Domain] = {}

    # First pass: create all domains without parent links
    for domain_data in DOMAINS:
        domain = Domain(
            name=domain_data["name"],
            slug=domain_data["slug"],
            config=domain_data["config"],
            system_persona=domain_data["system_persona"],
        )
        session.add(domain)
        slug_to_domain[domain_data["slug"]] = domain

    await session.flush()  # Get IDs assigned

    # Second pass: set parent relationships
    for domain_data in DOMAINS:
        if domain_data["parent_slug"]:
            child = slug_to_domain[domain_data["slug"]]
            parent = slug_to_domain[domain_data["parent_slug"]]
            child.parent_domain_id = parent.id

    await session.flush()
    return slug_to_domain


def generate_slug(name: str) -> str:
    """Generate URL-friendly slug from product name."""
    import re
    slug = name.lower()
    slug = re.sub(r'[^a-z0-9\s-]', '', slug)  # Remove special chars
    slug = re.sub(r'[\s_]+', '-', slug)        # Replace spaces with hyphens
    slug = re.sub(r'-+', '-', slug)            # Remove duplicate hyphens
    return slug.strip('-')


async def seed_products(session, slug_to_domain: dict[str, Domain]) -> None:
    """Create products for each domain."""
    for product_data in PRODUCTS:
        domain = slug_to_domain[product_data["domain_slug"]]

        # Auto-generate URLs from product name
        slug = generate_slug(product_data["name"])
        prod_url = product_data.get("product_url") or f"{BASE_URL}/products/{slug}"
        img_url = product_data.get("image_url") or f"{CDN_URL}/{slug}.jpg"

        product = Product(
            domain_id=domain.id,
            sku=product_data["sku"],
            name=product_data["name"],
            brand=product_data.get("brand"),
            description=product_data.get("description"),
            price=product_data.get("price"),
            inventory_count=product_data.get("inventory_count", 0),
            product_url=prod_url,
            image_url=img_url,
            attributes=product_data["attributes"],
        )
        session.add(product)


async def clear_existing_data(session) -> None:
    """Clear all existing data from tables."""
    await session.execute(text("DELETE FROM chat_messages"))
    await session.execute(text("DELETE FROM chat_sessions"))
    await session.execute(text("DELETE FROM products"))
    await session.execute(text("DELETE FROM domains"))
    await session.commit()


async def seed_database() -> None:
    """Main seed function."""
    async with async_session_factory() as session:
        print("Clearing existing data...")
        await clear_existing_data(session)

        print("Seeding Wellbeing Nutrition data...")

        # Seed domains
        print("  Creating domains...")
        slug_to_domain = await seed_domains(session)
        print(f"    Created {len(slug_to_domain)} domains")

        # Seed products
        print("  Creating products...")
        await seed_products(session, slug_to_domain)
        print(f"    Created {len(PRODUCTS)} products")

        await session.commit()
        print("Done!")

        # Print summary
        print("\nDomain hierarchy:")
        for domain_data in DOMAINS:
            prefix = "  └─ " if domain_data["parent_slug"] else ""
            print(f"  {prefix}{domain_data['name']} ({domain_data['slug']})")

        print(f"\nProducts by domain:")
        domain_counts = {}
        for p in PRODUCTS:
            domain_counts[p["domain_slug"]] = domain_counts.get(p["domain_slug"], 0) + 1
        for slug, count in domain_counts.items():
            print(f"  {slug}: {count} products")


if __name__ == "__main__":
    asyncio.run(seed_database())
