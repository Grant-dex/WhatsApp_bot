"""
Country identification from phone numbers using ITU-T E.164 country calling codes.
Pure Python — no external dependencies (replaces phonenumbers library).
"""
import logging
import re
from functools import lru_cache

logger = logging.getLogger(__name__)

# ── ITU-T E.164 Country Calling Code → (Country Name, ISO 3166-1 alpha-2 Region) ──
# Covers 60+ countries relevant to the generator export business.
# Ordered from longest code to shortest for correct prefix matching.

_COUNTRY_CODE_MAP: dict[str, tuple[str, str]] = {
    # Zone 1 — North America / Caribbean
    "1": ("United States", "US"),
    "1242": ("Bahamas", "BS"),
    "1246": ("Barbados", "BB"),
    "1264": ("Anguilla", "AI"),
    "1268": ("Antigua and Barbuda", "AG"),
    "1284": ("British Virgin Islands", "VG"),
    "1340": ("US Virgin Islands", "VI"),
    "1345": ("Cayman Islands", "KY"),
    "1441": ("Bermuda", "BM"),
    "1473": ("Grenada", "GD"),
    "1649": ("Turks and Caicos Islands", "TC"),
    "1664": ("Montserrat", "MS"),
    "1671": ("Guam", "GU"),
    "1684": ("American Samoa", "AS"),
    "1721": ("Sint Maarten", "SX"),
    "1758": ("Saint Lucia", "LC"),
    "1767": ("Dominica", "DM"),
    "1784": ("Saint Vincent and the Grenadines", "VC"),
    "1809": ("Dominican Republic", "DO"),
    "1829": ("Dominican Republic", "DO"),
    "1849": ("Dominican Republic", "DO"),
    "1868": ("Trinidad and Tobago", "TT"),
    "1869": ("Saint Kitts and Nevis", "KN"),
    "1876": ("Jamaica", "JM"),
    # Zone 2 — Africa
    "20": ("Egypt", "EG"),
    "211": ("South Sudan", "SS"),
    "212": ("Morocco", "MA"),
    "213": ("Algeria", "DZ"),
    "216": ("Tunisia", "TN"),
    "218": ("Libya", "LY"),
    "220": ("Gambia", "GM"),
    "221": ("Senegal", "SN"),
    "222": ("Mauritania", "MR"),
    "223": ("Mali", "ML"),
    "224": ("Guinea", "GN"),
    "225": ("Côte d'Ivoire", "CI"),
    "226": ("Burkina Faso", "BF"),
    "227": ("Niger", "NE"),
    "228": ("Togo", "TG"),
    "229": ("Benin", "BJ"),
    "230": ("Mauritius", "MU"),
    "231": ("Liberia", "LR"),
    "232": ("Sierra Leone", "SL"),
    "233": ("Ghana", "GH"),
    "234": ("Nigeria", "NG"),
    "235": ("Chad", "TD"),
    "236": ("Central African Republic", "CF"),
    "237": ("Cameroon", "CM"),
    "238": ("Cape Verde", "CV"),
    "239": ("São Tomé and Príncipe", "ST"),
    "240": ("Equatorial Guinea", "GQ"),
    "241": ("Gabon", "GA"),
    "242": ("Congo", "CG"),
    "243": ("DR Congo", "CD"),
    "244": ("Angola", "AO"),
    "245": ("Guinea-Bissau", "GW"),
    "246": ("British Indian Ocean Territory", "IO"),
    "247": ("Ascension Island", "AC"),
    "248": ("Seychelles", "SC"),
    "249": ("Sudan", "SD"),
    "250": ("Rwanda", "RW"),
    "251": ("Ethiopia", "ET"),
    "252": ("Somalia", "SO"),
    "253": ("Djibouti", "DJ"),
    "254": ("Kenya", "KE"),
    "255": ("Tanzania", "TZ"),
    "256": ("Uganda", "UG"),
    "257": ("Burundi", "BI"),
    "258": ("Mozambique", "MZ"),
    "260": ("Zambia", "ZM"),
    "261": ("Madagascar", "MG"),
    "262": ("Réunion", "RE"),
    "263": ("Zimbabwe", "ZW"),
    "264": ("Namibia", "NA"),
    "265": ("Malawi", "MW"),
    "266": ("Lesotho", "LS"),
    "267": ("Botswana", "BW"),
    "268": ("Eswatini", "SZ"),
    "269": ("Comoros", "KM"),
    "27": ("South Africa", "ZA"),
    "290": ("Saint Helena", "SH"),
    "291": ("Eritrea", "ER"),
    "297": ("Aruba", "AW"),
    "298": ("Faroe Islands", "FO"),
    "299": ("Greenland", "GL"),
    # Zone 3 — Europe
    "30": ("Greece", "GR"),
    "31": ("Netherlands", "NL"),
    "32": ("Belgium", "BE"),
    "33": ("France", "FR"),
    "34": ("Spain", "ES"),
    "350": ("Gibraltar", "GI"),
    "351": ("Portugal", "PT"),
    "352": ("Luxembourg", "LU"),
    "353": ("Ireland", "IE"),
    "354": ("Iceland", "IS"),
    "355": ("Albania", "AL"),
    "356": ("Malta", "MT"),
    "357": ("Cyprus", "CY"),
    "358": ("Finland", "FI"),
    "359": ("Bulgaria", "BG"),
    "36": ("Hungary", "HU"),
    "370": ("Lithuania", "LT"),
    "371": ("Latvia", "LV"),
    "372": ("Estonia", "EE"),
    "373": ("Moldova", "MD"),
    "374": ("Armenia", "AM"),
    "375": ("Belarus", "BY"),
    "376": ("Andorra", "AD"),
    "377": ("Monaco", "MC"),
    "378": ("San Marino", "SM"),
    "380": ("Ukraine", "UA"),
    "381": ("Serbia", "RS"),
    "382": ("Montenegro", "ME"),
    "383": ("Kosovo", "XK"),
    "385": ("Croatia", "HR"),
    "386": ("Slovenia", "SI"),
    "387": ("Bosnia and Herzegovina", "BA"),
    "389": ("North Macedonia", "MK"),
    "39": ("Italy", "IT"),
    "40": ("Romania", "RO"),
    "41": ("Switzerland", "CH"),
    "420": ("Czech Republic", "CZ"),
    "421": ("Slovakia", "SK"),
    "423": ("Liechtenstein", "LI"),
    "43": ("Austria", "AT"),
    "44": ("United Kingdom", "GB"),
    "45": ("Denmark", "DK"),
    "46": ("Sweden", "SE"),
    "47": ("Norway", "NO"),
    "48": ("Poland", "PL"),
    "49": ("Germany", "DE"),
    # Zone 5 — Latin America
    "500": ("Falkland Islands", "FK"),
    "501": ("Belize", "BZ"),
    "502": ("Guatemala", "GT"),
    "503": ("El Salvador", "SV"),
    "504": ("Honduras", "HN"),
    "505": ("Nicaragua", "NI"),
    "506": ("Costa Rica", "CR"),
    "507": ("Panama", "PA"),
    "509": ("Haiti", "HT"),
    "51": ("Peru", "PE"),
    "52": ("Mexico", "MX"),
    "53": ("Cuba", "CU"),
    "54": ("Argentina", "AR"),
    "55": ("Brazil", "BR"),
    "56": ("Chile", "CL"),
    "57": ("Colombia", "CO"),
    "58": ("Venezuela", "VE"),
    "590": ("Guadeloupe", "GP"),
    "591": ("Bolivia", "BO"),
    "592": ("Guyana", "GY"),
    "593": ("Ecuador", "EC"),
    "594": ("French Guiana", "GF"),
    "595": ("Paraguay", "PY"),
    "596": ("Martinique", "MQ"),
    "597": ("Suriname", "SR"),
    "598": ("Uruguay", "UY"),
    "599": ("Curaçao", "CW"),
    # Zone 6 — Southeast Asia / Oceania
    "60": ("Malaysia", "MY"),
    "61": ("Australia", "AU"),
    "62": ("Indonesia", "ID"),
    "63": ("Philippines", "PH"),
    "64": ("New Zealand", "NZ"),
    "65": ("Singapore", "SG"),
    "66": ("Thailand", "TH"),
    "670": ("East Timor", "TL"),
    "673": ("Brunei", "BN"),
    "674": ("Nauru", "NR"),
    "675": ("Papua New Guinea", "PG"),
    "676": ("Tonga", "TO"),
    "677": ("Solomon Islands", "SB"),
    "678": ("Vanuatu", "VU"),
    "679": ("Fiji", "FJ"),
    "680": ("Palau", "PW"),
    "682": ("Cook Islands", "CK"),
    "685": ("Samoa", "WS"),
    "686": ("Kiribati", "KI"),
    "687": ("New Caledonia", "NC"),
    "688": ("Tuvalu", "TV"),
    "689": ("French Polynesia", "PF"),
    "691": ("Micronesia", "FM"),
    "692": ("Marshall Islands", "MH"),
    # Zone 7 — Russia / Kazakhstan
    "7": ("Russia", "RU"),
    "76": ("Kazakhstan", "KZ"),
    "77": ("Kazakhstan", "KZ"),
    # Zone 8 — East Asia / Special
    "81": ("Japan", "JP"),
    "82": ("South Korea", "KR"),
    "84": ("Vietnam", "VN"),
    "850": ("North Korea", "KP"),
    "852": ("Hong Kong", "HK"),
    "853": ("Macau", "MO"),
    "855": ("Cambodia", "KH"),
    "856": ("Laos", "LA"),
    "86": ("China", "CN"),
    "880": ("Bangladesh", "BD"),
    "886": ("Taiwan", "TW"),
    # Zone 9 — Middle East / South Asia
    "90": ("Turkey", "TR"),
    "91": ("India", "IN"),
    "92": ("Pakistan", "PK"),
    "93": ("Afghanistan", "AF"),
    "94": ("Sri Lanka", "LK"),
    "95": ("Myanmar", "MM"),
    "960": ("Maldives", "MV"),
    "961": ("Lebanon", "LB"),
    "962": ("Jordan", "JO"),
    "963": ("Syria", "SY"),
    "964": ("Iraq", "IQ"),
    "965": ("Kuwait", "KW"),
    "966": ("Saudi Arabia", "SA"),
    "967": ("Yemen", "YE"),
    "968": ("Oman", "OM"),
    "970": ("Palestine", "PS"),
    "971": ("United Arab Emirates", "AE"),
    "972": ("Israel", "IL"),
    "973": ("Bahrain", "BH"),
    "974": ("Qatar", "QA"),
    "975": ("Bhutan", "BT"),
    "976": ("Mongolia", "MN"),
    "977": ("Nepal", "NP"),
    "98": ("Iran", "IR"),
    "992": ("Tajikistan", "TJ"),
    "993": ("Turkmenistan", "TM"),
    "994": ("Azerbaijan", "AZ"),
    "995": ("Georgia", "GE"),
    "996": ("Kyrgyzstan", "KG"),
    "998": ("Uzbekistan", "UZ"),
}

# Pre-sorted codes: longest first for correct prefix matching
_SORTED_CODES = sorted(_COUNTRY_CODE_MAP.keys(), key=lambda x: (len(x), int(x)), reverse=True)


def _extract_country_code(digits: str) -> str:
    """Extract the country calling code from a digit string (no leading +).

    Tries the longest possible prefix first to handle shared prefixes
    (e.g. 1-xxx vs 1, 76/77 vs 7).
    """
    if not digits:
        return ""
    for code in _SORTED_CODES:
        if digits.startswith(code):
            return code
    return ""


# ── Mapping from country name to electricity/power sector context for AI ───

COUNTRY_POWER_CONTEXT = {
    "Russia": "Russia has a vast power grid with significant gas power generation. Many industrial facilities need reliable gas gensets for backup or prime power due to aging infrastructure and remote locations.",
    "Kazakhstan": "Kazakhstan's oil & gas industry drives strong demand for gas generators. The country is modernizing its power infrastructure, and there's growing interest in gas-fired generation for remote oil fields.",
    "Ukraine": "Ukraine's energy infrastructure faces challenges. There is urgent demand for decentralized power solutions including gas generators for businesses and communities affected by grid instability.",
    "India": "India is rapidly expanding its gas power capacity. With frequent grid outages in many regions, industries rely heavily on gas generators for backup power. The government is pushing for cleaner natural gas solutions.",
    "Pakistan": "Pakistan faces chronic power shortages. Gas generators are critical for textile, manufacturing and commercial sectors. There is strong demand for reliable, cost-effective gas power solutions.",
    "United Arab Emirates": "UAE is investing heavily in energy diversification. While the grid is stable, there's growing demand for gas gensets in construction, offshore marine, and remote industrial applications.",
    "Saudi Arabia": "Saudi Arabia's Vision 2030 is driving massive infrastructure development. Gas generators are in high demand for construction sites, remote facilities, and oil & gas operations.",
    "Turkey": "Turkey's growing industrial sector and energy import dependency drive strong demand for efficient gas power generation. CHP and cogeneration applications are particularly relevant.",
    "Egypt": "Egypt is expanding its gas power capacity significantly. With new industrial zones and frequent summer power cuts, gas generators are in high demand.",
    "Nigeria": "Nigeria has abundant natural gas but an unreliable grid. Gas generators are essential for businesses across all sectors. There's growing interest in gas-to-power solutions.",
    "Brazil": "Brazil's hydropower-dominant grid faces dry season challenges. Natural gas generators are increasingly used as backup and for industrial cogeneration applications.",
    "Indonesia": "Indonesia's archipelagic geography makes centralized power challenging. Gas generators are critical for remote islands, mining operations, and industrial facilities.",
    "Vietnam": "Vietnam is rapidly industrializing with growing power demand. Gas-fired generation is a key part of their energy strategy, with strong demand for industrial gas gensets.",
    "Bangladesh": "Bangladesh faces significant power shortages. Gas generators are critical for the textile industry and other manufacturing sectors. There's growing interest in efficient gas solutions.",
    "Mexico": "Mexico's manufacturing sector relies heavily on gas power. With industrial growth and grid reliability concerns, there's steady demand for gas generators across industries.",
    "Germany": "Germany's Energiewende (energy transition) is driving interest in flexible gas power for grid balancing. There's strong demand for high-efficiency gas gensets with CHP capabilities.",
    "United Kingdom": "UK's energy transition and grid decarbonization create demand for flexible gas generation. There's particular interest in biogas and hydrogen-ready gas engines.",
    "Italy": "Italy has a mature gas power market with strong focus on energy efficiency. Cogeneration and trigeneration with gas engines are widely adopted in industrial applications.",
    "France": "France's nuclear-heavy grid is diversifying. There's growing interest in decentralized gas power for industrial self-generation and emergency backup.",
    "Spain": "Spain's renewable-heavy grid needs flexible gas backup. Industrial cogeneration with gas engines is well-established, and there's growing biogas interest.",
    "Poland": "Poland is transitioning from coal to gas. There's huge demand for gas-fired generation in district heating, industrial CHP, and as coal replacement.",
    "Netherlands": "Netherlands is phasing out natural gas production but maintains strong gas engine expertise. There's interest in biogas and hydrogen-ready gas engine solutions.",
    "Belgium": "Belgium's nuclear phaseout creates opportunities for gas power. There's demand for flexible, fast-start gas engines for grid support and industrial applications.",
    "Czech Republic": "Czech Republic is modernizing its power sector with growing gas generation. Industrial CHP and district heating with gas engines are key growth areas.",
    "Romania": "Romania has significant gas resources and is modernizing its power infrastructure. There's demand for efficient gas generators in industry and agriculture.",
    "South Africa": "South Africa's ongoing energy crisis (load shedding) creates massive demand for gas generators. Businesses urgently need reliable backup and off-grid power solutions.",
    "Kenya": "Kenya's growing economy faces power reliability challenges. Gas generators are important for industries, hotels, and facilities that require stable power supply.",
    "Tanzania": "Tanzania has discovered significant natural gas reserves. There's growing potential for gas-to-power projects and decentralized gas generation.",
    "Ghana": "Ghana's power sector faces reliability challenges. Gas generators are important for industrial and commercial backup power applications.",
    "Morocco": "Morocco is investing in energy diversification. Gas power plays a role in industrial applications and as backup for renewable-heavy grid sections.",
    "Australia": "Australia's remote mining operations heavily depend on gas power. There's also growing interest in gas generators for grid stabilization and remote communities.",
    "Malaysia": "Malaysia has strong oil & gas industry driving demand. Gas generators are widely used in industrial, commercial, and remote area power applications.",
    "Thailand": "Thailand's industrial sector and growing power demand drive gas generator market. There's interest in efficient gas engine solutions for factories and commercial buildings.",
    "Philippines": "Philippines' archipelagic geography makes distributed power essential. Gas generators serve remote islands, industrial facilities, and commercial establishments.",
    "Singapore": "Singapore's limited space and high reliability requirements favor compact, efficient gas power solutions. There's interest in premium gas genset brands for critical facilities.",
    "Japan": "Japan's post-Fukushima energy policy favors gas power. There's demand for high-efficiency, low-emission gas engines for industrial and commercial applications.",
    "South Korea": "South Korea is expanding gas power capacity. Industrial gas generators are in demand, with strong preference for premium, high-efficiency brands.",
    "China": "China's gas power market is growing rapidly. There's strong demand across industrial, commercial, and distributed energy applications, with interest in domestic and international brands.",
    "Argentina": "Argentina's Vaca Muerta shale gas is transforming energy landscape. Growing domestic gas production is driving interest in gas-to-power projects and industrial gas generators.",
    "Chile": "Chile's mining industry is a major gas power consumer. Remote mining operations and grid stability concerns drive demand for reliable gas generator solutions.",
    "Colombia": "Colombia's growing economy and hydropower dependency create demand for gas backup. Industrial and commercial sectors are key markets for gas generators.",
    "Peru": "Peru's mining and industrial sectors drive gas generator demand. Remote operations and grid reliability concerns make gas power essential.",
    "Qatar": "Qatar's massive gas resources and infrastructure development drive demand. Gas generators are used in construction, industrial, and infrastructure projects.",
    "Oman": "Oman's oil & gas and infrastructure sectors drive gas generator demand. There's interest in reliable gas power for remote facilities and industrial applications.",
    "Kuwait": "Kuwait's oil sector and infrastructure development drive gas generator demand. There's preference for premium, high-reliability gas power solutions.",
    "Bahrain": "Bahrain's industrial diversification and infrastructure growth create demand for gas generators in commercial and industrial applications.",
    "Iraq": "Iraq's grid is highly unreliable. Gas generators are essential for businesses, residential compounds, and oil & gas operations across the country.",
    "Jordan": "Jordan imports most of its energy. Gas generators serve as critical backup and prime power for industries and commercial facilities.",
    "Lebanon": "Lebanon's severe electricity crisis creates massive demand for generators. Gas generators are preferred for their lower operating cost vs diesel.",
    "Sudan": "Sudan faces significant power infrastructure challenges. Gas generators can serve critical power needs for industries and essential services.",
    "Ethiopia": "Ethiopia's growing industrial parks need reliable power. Gas generators play a role in ensuring stable power supply for manufacturing.",
    "Myanmar": "Myanmar's power infrastructure is underdeveloped. Gas generators are important for industrial and commercial operations that require stable power.",
    "Cambodia": "Cambodia's rapid industrial growth and grid limitations drive gas generator demand. Manufacturing and construction are key markets.",
    "Uzbekistan": "Uzbekistan has significant gas resources and is modernizing power infrastructure. There's growing interest in efficient gas power generation.",
    "Azerbaijan": "Azerbaijan is a major gas producer. Gas-to-power projects and industrial gas generators are natural fits for the local market.",
    "Turkmenistan": "Turkmenistan has vast gas reserves. Gas power generation is a priority sector with potential for gas engine applications in industry.",
}

# Top 10 electricity-importing/exporting country facts for AI context
GLOBAL_POWER_TRENDS = """
Global power trends 2025-2026:
- Gas genset market growing at ~8% CAGR driven by data center demand, grid instability, and industrial growth
- Biogas and hydrogen-ready engines are the fastest-growing segment
- CHP (Combined Heat & Power) adoption accelerating in Europe due to high energy costs
- Africa: massive off-grid and weak-grid gas generator demand, especially Nigeria, South Africa, Kenya
- Middle East: construction boom driving temporary and permanent gas power demand
- SE Asia: industrialization driving gas generator market growth in Vietnam, Indonesia, Philippines
- Latin America: mining and agribusiness sectors are major gas power consumers
"""


@lru_cache(maxsize=2048)
def get_country_from_phone(phone: str) -> dict:
    """Parse a phone number and return country info.

    Uses a built-in ITU-T E.164 country code mapping — no external dependencies.

    Returns dict with: country_name, country_code, region, is_valid
    """
    result = {
        "country_name": "",
        "country_code": "",
        "region": "",
        "is_valid": False,
    }
    if not phone:
        return result

    # Clean the phone number
    phone = str(phone).strip()

    # Remove WhatsApp suffixes
    for suffix in ("@lid", "@c.us", "@s.whatsapp.net"):
        if phone.endswith(suffix):
            phone = phone[:-len(suffix)]
            break

    # Remove group suffix (@g.us) and other @-suffixes
    if "@" in phone:
        phone = phone.split("@")[0]

    # Strip everything except digits and a leading +
    has_plus = phone.startswith("+")
    digits = re.sub(r"[^\d]", "", phone)

    if not digits:
        return result

    try:
        code = _extract_country_code(digits)
        if code and code in _COUNTRY_CODE_MAP:
            country_name, region = _COUNTRY_CODE_MAP[code]
            result["country_code"] = code
            result["country_name"] = country_name
            result["region"] = region

            # Basic validation: check that the national number part has a
            # reasonable length for the identified country (most are 5–12 digits).
            national_number = digits[len(code):]
            if 4 <= len(national_number) <= 13:
                result["is_valid"] = True
            elif 0 < len(national_number) < 4:
                # Too short — likely not a real number, but we still return the
                # country info since the prefix is recognized.
                result["is_valid"] = False

        # Handle North American Numbering Plan: many countries share code "1".
        # For USA/Canada (code "1"), we return "United States" as the default.
        # More specific Caribbean codes (1242, 1268, etc.) are matched above.
        if has_plus and not result["country_name"]:
            # Last resort: try to extract any recognizable prefix
            pass

    except Exception as e:
        logger.debug(f"Phone parse failed for '{phone}': {e}")

    return result


def get_power_context(country_name: str) -> str:
    """Get electricity sector context for a given country."""
    if not country_name:
        return ""
    # Try exact match first
    if country_name in COUNTRY_POWER_CONTEXT:
        return COUNTRY_POWER_CONTEXT[country_name]
    # Try partial match
    for key, value in COUNTRY_POWER_CONTEXT.items():
        if key.lower() in country_name.lower() or country_name.lower() in key.lower():
            return value
    return ""
