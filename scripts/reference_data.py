"""Swedish retail reference data for the synthetic generator."""

REGIONS: dict[str, dict] = {
    "Stockholms län": {"weight": 235, "cities": [
        ("Stockholm", "Stockholm", 59.3293, 18.0686),
        ("Södertälje", "Södertälje", 59.1955, 17.6252),
        ("Norrtälje", "Norrtälje", 59.7580, 18.7050),
        ("Täby", "Täby", 59.4439, 18.0687),
    ]},
    "Västra Götalands län": {"weight": 172, "cities": [
        ("Göteborg", "Göteborg", 57.7089, 11.9746),
        ("Borås", "Borås", 57.7210, 12.9401),
        ("Trollhättan", "Trollhättan", 58.2837, 12.2886),
        ("Skövde", "Skövde", 58.3912, 13.8452),
    ]},
    "Skåne län": {"weight": 136, "cities": [
        ("Malmö", "Malmö", 55.6050, 13.0038),
        ("Helsingborg", "Helsingborg", 56.0465, 12.6945),
        ("Lund", "Lund", 55.7047, 13.1910),
        ("Kristianstad", "Kristianstad", 56.0294, 14.1567),
    ]},
    "Östergötlands län": {"weight": 46, "cities": [
        ("Linköping", "Linköping", 58.4109, 15.6216),
        ("Norrköping", "Norrköping", 58.5877, 16.1924),
    ]},
    "Uppsala län": {"weight": 39, "cities": [
        ("Uppsala", "Uppsala", 59.8586, 17.6389),
        ("Enköping", "Enköping", 59.6358, 17.0776),
    ]},
    "Jönköpings län": {"weight": 35, "cities": [
        ("Jönköping", "Jönköping", 57.7815, 14.1562),
        ("Värnamo", "Värnamo", 57.1861, 14.0439),
    ]},
    "Hallands län": {"weight": 33, "cities": [
        ("Halmstad", "Halmstad", 56.6745, 12.8568),
        ("Varberg", "Varberg", 57.1057, 12.2502),
    ]},
    "Örebro län": {"weight": 30, "cities": [
        ("Örebro", "Örebro", 59.2741, 15.2066),
    ]},
    "Södermanlands län": {"weight": 29, "cities": [
        ("Eskilstuna", "Eskilstuna", 59.3710, 16.5098),
        ("Nyköping", "Nyköping", 58.7530, 17.0088),
    ]},
    "Dalarnas län": {"weight": 28, "cities": [
        ("Falun", "Falun", 60.6065, 15.6355),
        ("Borlänge", "Borlänge", 60.4858, 15.4371),
    ]},
    "Gävleborgs län": {"weight": 28, "cities": [
        ("Gävle", "Gävle", 60.6749, 17.1413),
        ("Sandviken", "Sandviken", 60.6194, 16.7757),
    ]},
    "Värmlands län": {"weight": 27, "cities": [
        ("Karlstad", "Karlstad", 59.4022, 13.5115),
    ]},
    "Västmanlands län": {"weight": 27, "cities": [
        ("Västerås", "Västerås", 59.6099, 16.5448),
    ]},
    "Västerbottens län": {"weight": 27, "cities": [
        ("Umeå", "Umeå", 63.8258, 20.2630),
        ("Skellefteå", "Skellefteå", 64.7507, 20.9528),
    ]},
    "Norrbottens län": {"weight": 25, "cities": [
        ("Luleå", "Luleå", 65.5848, 22.1567),
        ("Piteå", "Piteå", 65.3172, 21.4794),
    ]},
    "Kalmar län": {"weight": 24, "cities": [
        ("Kalmar", "Kalmar", 56.6634, 16.3566),
        ("Västervik", "Västervik", 57.7580, 16.6373),
    ]},
    "Västernorrlands län": {"weight": 24, "cities": [
        ("Sundsvall", "Sundsvall", 62.3908, 17.3069),
        ("Örnsköldsvik", "Örnsköldsvik", 63.2909, 18.7152),
    ]},
    "Kronobergs län": {"weight": 20, "cities": [
        ("Växjö", "Växjö", 56.8777, 14.8091),
    ]},
    "Blekinge län": {"weight": 15, "cities": [
        ("Karlskrona", "Karlskrona", 56.1612, 15.5869),
    ]},
    "Jämtlands län": {"weight": 13, "cities": [
        ("Östersund", "Östersund", 63.1792, 14.6357),
    ]},
    "Gotlands län": {"weight": 6, "cities": [
        ("Visby", "Visby", 57.6348, 18.2948),
    ]},
}

CATEGORIES: dict[str, list[str]] = {
    "Ljud & Bild": ["Hörlurar", "Högtalare", "TV", "Ljudanläggningar", "Bilstereo"],
    "Hem & Kök": ["Kaffebryggare", "Köksmaskiner", "Dammsugare", "Belysning"],
    "Dator & Mobil": ["Bärbara datorer", "Mobiltelefoner", "Surfplattor", "Datortillbehör"],
    "Sport & Fritid": ["Träningsutrustning", "Cyklar", "Utomhusliv", "Vintersport"],
    "Skönhet & Hälsa": ["Hårvård", "Personvård"],
    "Barn & Leksaker": ["Byggleksaker", "Sällskapsspel", "Babyprodukter"],
}

# Deliberately too few competing brands, so k-anonymity suppression (§11.3) actually fires.
THIN_SUBCATEGORY = "Vintersport"

SUPPLIERS: dict[str, list[str]] = {
    "Nordström Audio AB": ["Nordström", "Vidar"],
    "Lagerkvist Hem AB": ["Lagerkvist", "Bruksbo"],
    "Svea Elektronik AB": ["Svea", "Norrsken"],
    "Bergqvist Sport AB": ["Bergqvist"],
    "Lumia Nordic AB": ["Lumia", "Kvist"],
    "Falkenberg Beauty AB": ["Falkenberg"],
    "Trolle Leksaker AB": ["Trolle", "Klätter"],
    "Aurora Kök AB": ["Aurora", "Tindra"],
}

# The supplier the demo logs in as - whose dashboard is shown in the video.
DEMO_SUPPLIER = "Nordström Audio AB"

BRAND_SUBCATEGORIES: dict[str, list[str]] = {
    "Hörlurar":            ["Nordström", "Vidar", "Svea", "Norrsken", "Lumia", "Kvist"],
    "Högtalare":           ["Nordström", "Vidar", "Svea", "Lumia", "Bruksbo"],
    "TV":                  ["Nordström", "Svea", "Norrsken", "Lumia", "Kvist"],
    "Ljudanläggningar":    ["Nordström", "Vidar", "Svea", "Norrsken", "Bruksbo"],
    "Bilstereo":           ["Vidar", "Svea", "Norrsken", "Lumia", "Kvist"],
    "Kaffebryggare":       ["Aurora", "Tindra", "Lagerkvist", "Bruksbo", "Kvist"],
    "Köksmaskiner":        ["Aurora", "Tindra", "Lagerkvist", "Bruksbo", "Lumia"],
    "Dammsugare":          ["Lagerkvist", "Bruksbo", "Aurora", "Svea", "Kvist"],
    "Belysning":           ["Lumia", "Kvist", "Lagerkvist", "Bruksbo", "Tindra"],
    "Bärbara datorer":     ["Svea", "Norrsken", "Lumia", "Nordström", "Kvist"],
    "Mobiltelefoner":      ["Svea", "Norrsken", "Lumia", "Kvist", "Vidar"],
    "Surfplattor":         ["Svea", "Norrsken", "Lumia", "Kvist", "Nordström"],
    "Datortillbehör":      ["Svea", "Norrsken", "Nordström", "Vidar", "Lumia", "Kvist"],
    "Träningsutrustning":  ["Bergqvist", "Klätter", "Kvist", "Lumia", "Bruksbo"],
    "Cyklar":              ["Bergqvist", "Klätter", "Bruksbo", "Kvist", "Lagerkvist"],
    "Utomhusliv":          ["Bergqvist", "Klätter", "Trolle", "Bruksbo", "Lagerkvist"],
    "Vintersport":         ["Bergqvist", "Klätter", "Bruksbo"],
    "Hårvård":             ["Falkenberg", "Tindra", "Aurora", "Lumia", "Kvist"],
    "Personvård":          ["Falkenberg", "Tindra", "Aurora", "Bruksbo", "Kvist"],
    "Byggleksaker":        ["Trolle", "Klätter", "Bergqvist", "Tindra", "Kvist"],
    "Sällskapsspel":       ["Trolle", "Klätter", "Tindra", "Bruksbo", "Kvist"],
    "Babyprodukter":       ["Trolle", "Klätter", "Tindra", "Aurora", "Falkenberg"],
}

SUBCATEGORY_PROFILE: dict[str, tuple[str, int, int]] = {
    "Hörlurar":           ("Hörlurar", 399, 3990),
    "Högtalare":          ("Högtalare", 690, 8990),
    "TV":                 ("TV", 3990, 24990),
    "Ljudanläggningar":   ("Ljudsystem", 2990, 17990),
    "Bilstereo":          ("Bilstereo", 990, 6990),
    "Kaffebryggare":      ("Kaffebryggare", 490, 7990),
    "Köksmaskiner":       ("Köksmaskin", 690, 6990),
    "Dammsugare":         ("Dammsugare", 990, 8990),
    "Belysning":          ("Lampa", 149, 2490),
    "Bärbara datorer":    ("Laptop", 5990, 24990),
    "Mobiltelefoner":     ("Mobil", 2490, 15990),
    "Surfplattor":        ("Surfplatta", 1990, 12990),
    "Datortillbehör":     ("Tillbehör", 99, 1990),
    "Träningsutrustning": ("Träningsutrustning", 299, 9990),
    "Cyklar":             ("Cykel", 3490, 29990),
    "Utomhusliv":         ("Friluftsutrustning", 299, 6990),
    "Vintersport":        ("Vinterutrustning", 690, 12990),
    "Hårvård":            ("Hårvårdsprodukt", 89, 899),
    "Personvård":         ("Personvårdsprodukt", 99, 1990),
    "Byggleksaker":       ("Byggsats", 199, 1490),
    "Sällskapsspel":      ("Sällskapsspel", 149, 799),
    "Babyprodukter":      ("Babyprodukt", 199, 4990),
}

MODEL_SUFFIXES = [
    "One", "Two", "Pro", "Max", "Mini", "Air", "Plus", "Studio", "Go", "Home",
    "Sport", "Compact", "Elite", "Classic", "Neo", "Lite", "Ultra", "Duo",
]

SEASONALITY: dict[str, list[float]] = {
    "Ljud & Bild":     [0.85, 0.80, 0.85, 0.85, 0.90, 0.90, 0.75, 0.95, 1.00, 1.05, 1.75, 1.85],
    "Hem & Kök":       [1.05, 0.95, 0.95, 0.95, 1.00, 0.95, 0.80, 1.00, 1.05, 1.05, 1.45, 1.55],
    "Dator & Mobil":   [0.95, 0.85, 0.90, 0.90, 0.90, 0.95, 0.80, 1.30, 1.15, 1.00, 1.55, 1.50],
    "Sport & Fritid":  [1.10, 1.05, 1.05, 1.15, 1.25, 1.20, 1.00, 0.95, 0.90, 0.85, 1.15, 1.20],
    "Skönhet & Hälsa": [1.05, 0.95, 1.00, 1.00, 1.05, 1.05, 0.85, 0.95, 1.00, 1.00, 1.35, 1.45],
    "Barn & Leksaker": [0.75, 0.70, 0.75, 0.80, 0.85, 0.90, 0.80, 0.85, 0.90, 1.00, 1.80, 2.30],
}

FIXED_HOLIDAYS = [
    (1, 1), (1, 6), (5, 1), (6, 6), (12, 24), (12, 25), (12, 26), (12, 31),
]

CAMPAIGNS = [
    ("Black Week", 11, 21, 30, 2.6),
    ("Mellandagsrea", 12, 26, 31, 1.9),
    ("Januarirea", 1, 2, 15, 1.5),
    ("Vårkampanj", 4, 10, 20, 1.3),
    ("Sommarrea", 6, 25, 30, 1.4),
    ("Skolstart", 8, 10, 25, 1.35),
]

CUSTOMER_SEGMENTS = ["Privat", "Företag", "Student", "Senior"]
AGE_BUCKETS = ["18-24", "25-34", "35-44", "45-54", "55-64", "65+"]
LOYALTY_TIERS = ["Ingen", "Brons", "Silver", "Guld"]
