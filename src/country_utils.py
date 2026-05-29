import logging
from functools import lru_cache

import phonenumbers
from phonenumbers import geocoder, PhoneNumberFormat

logger = logging.getLogger(__name__)

# Mapping from country name to electricity/power sector context for DeepSeek
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
    """
    Parse a phone number and return country info.
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
    # Remove @lid, @c.us, @s.whatsapp.net suffixes
    for suffix in ["@lid", "@c.us", "@s.whatsapp.net"]:
        if phone.endswith(suffix):
            phone = phone[: -len(suffix)]
            break

    # Try to remove @g.us (WhatsApp groups, not expected but handle it)
    if "@" in phone and not any(phone.endswith(x) for x in [".net", ".us"]):
        phone = phone.split("@")[0]

    try:
        parsed = phonenumbers.parse(phone, None)
        result["is_valid"] = phonenumbers.is_valid_number(parsed)
        result["country_code"] = str(parsed.country_code)
        result["country_name"] = geocoder.description_for_number(parsed, "en") or ""
        result["region"] = phonenumbers.region_code_for_number(parsed) or ""

        if not result["country_name"]:
            # Fallback: try to get region code
            region = phonenumbers.region_code_for_number(parsed)
            if region:
                result["country_name"] = region
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
