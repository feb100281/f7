"""
Товарные группы запчастей — правила разбивки артикулов по названию.

Логика детерминированная и прозрачная:
    1. Название (EN / FR / RU, как в 1С) приводится к верхнему регистру.
    2. Правила проверяются СВЕРХУ ВНИЗ, побеждает первое совпадение —
       поэтому узкие правила («OIL FILTER» → фильтры) стоят выше широких («OIL» → масла).
    3. Если по названию ничего не нашлось — смотрим на префикс артикула BRP.
    4. Остальное — «Прочее», его разбирают руками (ручная разметка важнее правил).

Править правила можно прямо здесь: добавить слово в нужную группу или поднять правило выше.
Код группы (ключ) не менять — на него будут ссылаться прогнозы и матрица.
"""

from __future__ import annotations

import re

# --------------------------------------------------------------------------
# Группы: код → (название, тип спроса)
#   consumable  — расходники ТО: покупают регулярно, сезонно, прогнозируются лучше всего
#   wear        — износ: ремни, тормоза, ходовая — спрос есть, но реже и по факту поломки
#   repair      — ремонт: детали двигателя, электрика — редко, дорого, под заказ
#   body        — кузов и пластик: после аварий, штучно
#   accessory   — аксессуары: импульсные и сезонные покупки, «витрина»
#   fastener    — крепёж и мелочь: дёшево, держать на складе, но не прогнозировать поштучно
# --------------------------------------------------------------------------
GROUPS: dict[str, tuple[str, str]] = {
    "oil":         ("Масла и техжидкости",               "consumable"),
    "chem":        ("Смазки, химия, герметики",          "consumable"),
    "filter":      ("Фильтры",                           "consumable"),
    "spark":       ("Свечи и зажигание",                 "consumable"),
    "belt":        ("Ремни вариатора",                   "wear"),
    "brake":       ("Тормозная система",                 "wear"),
    "snow_run":    ("Снегоход: склизы, лыжи, гусеница",  "wear"),
    "jet":         ("Гидроцикл: водомёт, импеллер",      "wear"),
    "tire":        ("Колёса, шины, диски",               "wear"),
    "suspension":  ("Подвеска и рулевое",                "wear"),
    "driveline":   ("Трансмиссия и вариатор",            "repair"),
    "seal":        ("Прокладки, сальники, кольца",       "repair"),
    "bearing":     ("Подшипники и втулки",               "wear"),
    "engine":      ("Двигатель",                         "repair"),
    "cooling":     ("Охлаждение",                        "repair"),
    "fuel":        ("Топливная система и впуск/выпуск",  "repair"),
    "battery":     ("Аккумуляторы",                      "consumable"),
    "electric":    ("Электрика и электроника",           "repair"),
    "light":       ("Освещение",                         "repair"),
    "controls":    ("Управление: руль, рычаги, тросы",   "repair"),
    "body":        ("Кузов и пластик",                   "body"),
    "decal":       ("Наклейки и эмблемы",                "body"),
    "protection":  ("Защита, бамперы, расширители",      "accessory"),
    "acc_cargo":   ("Аксессуары: багаж, LinQ, кофры",    "accessory"),
    "acc_comfort": ("Аксессуары: сиденья, стёкла, комфорт", "accessory"),
    "acc_winch":   ("Аксессуары: лебёдки, сцепка, буксир", "accessory"),
    "acc_tuning":  ("Аксессуары: тюнинг и комплекты",    "accessory"),
    "acc_other":   ("Аксессуары: прочие",                "accessory"),
    "gear":        ("Экипировка и одежда",               "accessory"),
    "fastener":    ("Крепёж и мелочь",                   "fastener"),
    "service":     ("Услуги и служебные позиции",        "other"),
    "other":       ("Прочее (не распознано)",            "other"),
}


def _rx(*words: str) -> re.Pattern:
    """Слова/фразы → регулярка по границам слов. '*' внутри слова — любой хвост."""
    parts = []
    for w in words:
        w = re.escape(w.upper()).replace(r"\*", r"\w*").replace(r"\ ", r"[\s_\-/]*")
        parts.append(w)
    return re.compile(r"(?<![A-ZА-ЯЁ0-9])(?:" + "|".join(parts) + r")(?![A-ZА-ЯЁ0-9])")


# Масло/жидкость как ТОВАР: есть слово-жидкость И признак упаковки/вязкости/типа.
# Иначе «OIL SEAL», «OIL LINE», «OIL DIPSTICK» уходили бы в масла.
_LIQUID = r"(?:OIL|OILS|HUILE|МАСЛ\w*|ANTIFREEZE|ANTIGEL|COOLANT|АНТИФРИЗ\w*|FLUID|ЖИДКОСТ\w*)"
_PRODUCT = (
    r"(?:\d+[.,]?\d*\s*(?:ML|L|LT|LITRE|LITER|МЛ|Л|QT|QUART|GAL|GALLON|OZ)\b"
    r"|\d+\s*\*\s*1\b|\b\d{1,2}W[\s\-]?\d{2,3}\b|\bSYNTHETIC\b|\bSEMI|\bMINERAL\b|СИНТЕТ|ПОЛУСИНТ"
    r"|\b[24]T\b|\b[24]\s?STROKE\b|\b[24]-STROKE\b|LONG LIFE|\bDOT\s?4\b|ТРАНСМИССИОН|МОТОРН"
    r"|\bGEARBOX OIL\b|\bGEAR OIL\b|\bCHAINCASE\b|\bJET PUMP OIL\b|\bBRAKE FLUID\b)"
)
OIL_PRODUCT_RX = re.compile(rf"(?:^(?=.*(?<![A-ZА-Я]){_LIQUID}(?![A-ZА-Я]))(?=.*{_PRODUCT}))|(?<![A-Z])XPS(?![A-Z])")

# --------------------------------------------------------------------------
# Правила по названию: (код группы, регулярка). Порядок важен!
# --------------------------------------------------------------------------
NAME_RULES: list[tuple[str, re.Pattern]] = [
    # ======================================================================
    # УЗКИЕ ПРАВИЛА-ИСКЛЮЧЕНИЯ — фразы, которые иначе съест широкое правило ниже
    # ======================================================================
    ("gear", _rx("HELMET*", "ШЛЕМ*", "ЖИЛЕТ*", "PFD", "VEST*", "JACKET*", "КУРТК*", "GLOVE*", "ПЕРЧАТ*",
                 "GOGGLE*", "МАСКА", "ОЧКИ", "SUIT*", "КОМБИНЕЗ*", "OXYGEN", "ОДЕЖД*", "ТЕРМОБЕЛ*",
                 "HOODIE*", "T-SHIRT*", "ФУТБОЛК*", "КЕПК*", "CAP BRP", "BALACLAVA*", "БАЛАКЛАВ*")),
    ("acc_tuning", _rx("TRACK KIT", "TRACK 360", "APACHE*", "ACM KIT", "SYSTEM KIT SSP", "SSP LEVEL*",
                       "POWER UPGRADE*", "SPEED-PROG", "SPEED PROG", "PARTICLE SEPARATOR", "SCOOP*",
                       "BED WALL*", "RELOCATOR*", "PROMOUNT*", "PUSH FRAME", "PLOW*", "ОТВАЛ*",
                       "BLADE DS*", "WAKEBOARD*", "SKI PYLON", "RETRACTABLE SKI*")),
    ("acc_comfort", _rx("WIPER*", "WINDSHIELD*", "WINDSHLD*", "WINDSHEILD*", "GLASSWINDSHLD*", "ДВОРНИК*",
                        "ОМЫВАТ*")),
    ("acc_comfort", _rx("HEATED STEERING WHEEL", "STEERING WHEEL HEATED", "SUBWOOFER*", "AMPLIFIER*",
                        "WINDOW*", "ОКНА", "ОКН*", "NET", "NETS", "NET WIND*", "WIND SCREEN", "HARD TOP",
                        "SOFT TOP", "ROOF*", "ПЕЧК*", "HEATER*", "DEFROST*", "CAMERA*", "КАМЕР* ЗАДН*",
                        "MONITOR*", "ЗАДНЯЯ СЕТКА")),
    ("protection", _rx("ROCK SLIDER*", "PRE-RUNNER*", "PRE RUNNER*", "INTRUSION BAR*", "LOG BAR*",
                       "MUD FLAP*", "MUDFLAP*")),
    ("acc_cargo", _rx("SADDLEBAG*", "TOP CASE", "BASKET*", "СТЯЖН*", "TIE DOWN*", "TIE-DOWN*", "STRAP*",
                      "LINQ")),
    ("acc_cargo", _rx("GUN BOOT*", "GUN*", "KOLPIN*")),
    ("decal", _rx("LABEL*", "INSTRUCTION*", "DECAL*", "DECALQUE*", "НАКЛЕЙК*")),
    ("fastener", _rx("BRIDE SERRAGE", "CLAMP*", "CLAVETTE*", "WOODRUFF", "KEY WOODRUFF")),
    ("driveline", _rx("JOINT PLONGEANT*", "JOINT-PLUNGING", "PLUNGING*", "ROUE DENTEE*", "SPROCKET*",
                      "CUSHION DRIVE", "CUSHION-DRIVE", "COVER GEARBOX*", "GEARBOX COVER*")),
    ("driveline", _rx("BOOT KIT", "BOOT", "BOOTS", "ПЫЛЬНИК*", "FINAL DRIVE*", "JOINT CARDA*",
                      "CARDAN*", "RADIAL JOINT", "PLUNGING JOINT", "UNIT PACK", "COUNTERSHAFT*",
                      "ШАРНИР*", "ШРУС*", "CV JOINT", "JOINT CV", "FLASQUE*", "FLANGE SLID*", "FIXED FLANGE*",
                      "SLIDING FLANGE*", "SHEAVE*", "FORK*", "ВИЛК*")),
    ("seal", _rx("SEAL OIL", "SEAL-OIL", "OIL SEAL", "ANNEAU ETANCHE*", "JOINT ETANCH*", "GASKET*",
                 "O-RING*", "O RING", "САЛЬНИК*", "ПРОКЛАД*")),
    ("brake", _rx("MASTER CYLIND*", "MAITRE CYLINDRE*", "BRAKE*", "FREIN*", "ТОРМОЗ*", "PADS KIT", "PAD KIT")),
    ("tire", _rx("MAXXIS", "CARLISLE", "ITP", "KENDA", "BIGHORN*", "TIRE*", "ШИН*", "БЭДЛОК*", "BEADLOCK*",
                 "BEAD LOCK", "ДИСК", "DISQUE ROUE*")),
    ("jet", _rx("RING WEAR", "WEAR RING", "RESONAT*")),
    ("light", _rx("CLIGNOT*", "FLASHER*")),
    ("electric", _rx("CDI*", "LANDYARD*", "LANYARD*", "INDICATEUR*")),
    ("fuel", _rx("VAPOR SEP*", "VAPOUR SEP*")),
    ("body", _rx("HAND HOLD*", "FOOTSTEP*", "GRAB HANDLE*", "GRAB BAR*")),
    ("cooling", _rx("TANK COOLANT", "TANK-COOLANT", "COOLANT TANK", "RES ANTIGEL", "RES.ANTIGEL",
                    "COOLANT HOSE", "HOSE COOLANT", "RESERVOIR ANTIGEL", "РАСШИРИТЕЛЬН* БАЧ*")),
    ("oil", _rx("АНТИФРИЗ*", "ANTIFREEZE", "COOLANT EXT*", "COOLANT", "OIL STORAGE", "FOGGING*")),
    ("fastener", _rx("SCREW*", "VIS", "WASHER*", "RONDELLE*", "BOLT*", "BOULON*", "ECROU*", "NUT", "NUTS",
                     "RIVET*", "БОЛТ*", "ВИНТ*", "ГАЙК*", "ШАЙБ*", "ЗАКЛЕП*", "САМОРЕЗ*", "OETIKER*")),
    ("engine", _rx("CYLINDER BLOCK*", "LONGBLOCK", "LONG BLOCK", "SHORT BLOCK", "SHORTBLOCK")),
    ("jet", _rx("IMPELER*", "IMPELLER*")),
    ("snow_run", _rx("SLIDE SHOE*", "SLIDER SHOE*", "SLIDER", "SLIDERS", "СКЛИЗ*")),
    ("tire", _rx("КОЛПАК*", "HUB CAP", "WHEEL CAP")),
    ("battery", _rx("АКУМУЛЯТОР*", "АККУМУЛЯТОР*", "BATTERY*", "BATTERIE*")),
    ("light", _rx("TURN SIGNAL*", "ПОВОРОТНИК*", "LIGHT*", "LAMP*", "HEADLAMP*", "HEADLIGHT*")),
    ("electric", _rx("ПУЛЬТ*", "HAND CONTROL", "REMOTE*")),
    ("fuel", _rx("SECONDARY CHAMBER", "SEC CHAMBER", "CHAMBRE*")),
    ("body", _rx("ПОДНОЖК*", "STRUCTURE*")),

    # --- фильтры раньше масел и топлива («OIL FILTER», «FUEL FILTER»)
    ("filter", _rx("FILTER*", "FILTRE*", "ФИЛЬТР*", "PRE FILTER", "PREFILTER", "CARTRIDGE")),

    # --- свечи раньше «PLUG» (пробки)
    ("spark", _rx("SPARK PLUG*", "BOUGIE*", "NGK", "СВЕЧ*", "IGNITION COIL", "COIL IGNITION",
                  "COIL-IGNITION", "BOBINE*", "КАТУШК*")),

    # --- масла и жидкости
    ("oil", OIL_PRODUCT_RX),
    ("chem", _rx("LUBE", "LUBRICANT", "GREASE", "GRAISSE", "СМАЗК*", "LOCTITE", "SEALANT", "SILICONE",
                 "ГЕРМЕТИК*", "CLEANER", "ОЧИСТИТ*", "СТАБИЛИЗАТОР ТОПЛ*", "FUEL STABILIZER",
                 "STABILIZER FUEL", "SHINE", "PROTECTANT", "WAX", "ПОЛИРОЛ*", "АЭРОЗОЛ*",
                 "SPRAY", "ADHESIVE", "КЛЕЙ", "GLUE", "PRIMER", "IRIX")),

    # --- ремни (но не ремни безопасности/крепления)
    ("acc_comfort", _rx("SAFETY BELT", "SAFETY_BELT", "SEAT BELT", "BELT SAFETY", "РЕМЕНЬ БЕЗОПАСН*")),
    ("acc_cargo", _rx("TIE DOWN*", "TIE-DOWN*", "STRAP*", "СТЯЖК*")),
    ("belt", _rx("DRIVE BELT", "BELT DRIVE", "BELT_DRIVE", "BELT-DRIVE", "V BELT", "V-BELT", "BELT-V",
                 "BELT", "COURROIE*", "РЕМЕН*", "РЕМНЯ", "РЕМЕНЬ")),

    # --- тормоза
    ("brake", _rx("BRAKE*", "FREIN*", "CALIPER*", "ETRIER*", "PAD BRAKE", "PAD_BRAKE", "PAD-BRAKE",
                  "PLAQ FREIN*", "PLAQUETTE*", "ENS PLAQUES*", "PLAQUES", "КОЛОДК*", "ТОРМОЗ*", "СУППОРТ*", "MASTER CYLINDER", "BRAKE DISC", "ROTOR")),

    # --- аккумуляторы
    ("battery", _rx("BATTERY*", "BATTERIE*", "АККУМУЛЯТОР*", "АКБ", "YTX*", "YTZ*")),

    # --- защита и бамперы (до кузова)
    ("protection", _rx("BUMPER*", "PARE CHOCS", "PARE-CHOCS", "БАМПЕР*", "SKID PLATE*", "SKID", "GUARD*",
                       "PROTECTOR*", "PROTECTEUR*", "PROTECTION", "ЗАЩИТ*", "HAND GUARD*", "ROCK SLIDER*",
                       "FENDER FLARE*", "FLARE*", "РАСШИРИТЕЛ*", "MUD GUARD*", "MUDGUARD*", "MUDFLAP*",
                       "GARDE BOUE", "GARDE-BOUE", "БРЫЗГОВИК*", "BRUSH GUARD", "NERF BAR*", "БРЫЗГОВ*")),

    # --- снегоход: склизы, лыжи, гусеница
    ("snow_run", _rx("SLIDER*", "СКЛИЗ*", "SKI", "SKIS", "ЛЫЖ*", "RUNNER*", "CARBIDE*", "КОНЬК*", "ТВЕРДОСПЛАВ*",
                     "TRACK", "ГУСЕНИЦ*", "IDLER WHEEL", "IDLER", "WHEEL-141MM", "STUD*", "ШИП*",
                     "SKI LEG", "SKI-LEG", "SKI SKIN*", "PATIN*", "CHENILLE*", "SPROCKET DRIVE")),

    # --- гидроцикл: водомёт
    ("jet", _rx("IMPELLER*", "IMPULSEUR*", "ИМПЕЛЛЕР*", "WEAR RING", "WEAR-RING", "ANNEAU USURE",
                "JET PUMP", "PUMP JET", "VENTURI", "NOZZLE", "СОПЛО", "ВОДОМЕТ*", "INTAKE GRATE",
                "RIDE PLATE", "REVERSE GATE", "IBR*")),

    # --- колёса и шины (до «CAP», «VALVE»)
    ("tire", _rx("TIRE*", "TYRE*", "PNEU*", "ШИН*", "RIM*", "JANTE*", "ДИСК КОЛЕС*", "WHEEL", "WHEELS",
                 "ROUE*", "КОЛЕС*", "КОЛЁС*", "WHEEL CAP", "HUB CAP", "LUG NUT", "WHEEL NUT", "BEAD LOCK",
                 "BEADLOCK", "RIM VALVE", "ВЕНТИЛ*")),

    # --- лебёдки, сцепка, буксировка
    ("acc_winch", _rx("WINCH*", "ЛЕБЕДК*", "HITCH*", "ФАРКОП*", "TOW*", "TRAILER*", "TRAILERING", "ПРИЦЕП*",
                      "ROPE", "SYNTHETIC ROPE", "FAIRLEAD", "ROLLER FAIRLEAD", "HOOK", "КРЮК*",
                      "PLOW*", "ОТВАЛ*", "BLADE", "SNOW PLOW", "ANCHOR*", "ЯКОР*", "DOCK*", "FENDERS KIT",
                      "SNAP-IN FENDERS", "LADDER", "ЛЕСТНИЦ*", "TOWING", "BUOY*")),

    # --- багаж и LinQ
    ("acc_cargo", _rx("LINQ", "CARGO*", "BOX*", "BAG*", "SAC", "СУМК*", "КОФР*", "ЯЩИК*", "TRUNK*",
                      "КАНИСТР*", "JERRY*", "FUEL CADDY", "TANK_FUEL KIT", "CANISTER", "RACK*", "БАГАЖН*",
                      "LUGGAGE", "STORAGE", "COOLER", "ХОЛОДИЛЬН*", "PYLON", "SKI PYLON", "TUNNEL BAG",
                      "HOLDER", "SUPPORT SMARTPHONE", "SMARTPHONE*", "PHONE*", "GPS*", "MOUNT KIT",
                      "TOOL BOX", "GUN*", "BOOT RACK", "CUP HOLDER")),

    # --- комфорт: сиденья, стёкла, обогрев, тенты
    ("acc_comfort", _rx("SEAT*", "СИДЕН*", "SIEGE*", "BACKREST*", "СПИНК*", "HEATED*", "ПОДОГРЕВ*", "ОБОГРЕВ*",
                        "HEATER*", "WINDSHIELD*", "WINDSHLD*", "WIND SHIELD", "WINDSCREEN", "PARE-BRISE",
                        "ВЕТРОВ*", "СТЕКЛ*", "GLASS", "WIPER*", "ДВОРНИК*", "MIRROR*", "RETROVISEUR*",
                        "ЗЕРКАЛ*", "ROOF*", "КРЫША", "CAB", "CABIN", "ENCLOSURE", "DOOR*", "ДВЕР*",
                        "SOFT TOP", "CANVAS*", "COVER KIT", "TENT*", "ТЕНТ*", "ЧЕХ*", "WIND DEFLECTOR*",
                        "DEFLECTOR*", "DEFLECTEUR*", "ДЕФЛЕКТОР*", "AUDIO*", "АУДИО*", "SPEAKER*", "SOUND*",
                        "МУФТ* НА РУЛЬ", "MUFFS", "HANDLEBAR MUFF*", "FOOTREST*", "CUSHION*",
                        "ARMREST*", "ПОДЛОКОТН*", "SUN*", "BIMINI", "ПЕРЕДНЕЕ СТЕКЛО")),

    # --- освещение
    ("light", _rx("LIGHT*", "LAMP*", "HEADLAMP*", "HEADLIGHT*", "ФАР*", "ФОНАР*", "LED", "LEDS", "BULB*",
                  "AMPOULE*", "ЛАМП*", "ЛАМПОЧ*", "PHARE*", "FEU", "FEUX", "REFLECTOR*", "СВЕТ*",
                  "TAILLIGHT*", "TAIL LIGHT*", "STROBE")),

    # --- вариатор и трансмиссия
    ("driveline", _rx("CLUTCH*", "EMBRAYAGE*", "СЦЕПЛЕН*", "ВАРИАТОР*", "CVT", "PULLEY*", "POULIE*", "ШКИВ*",
                      "DRIVE PULLEY", "DRIVEN PULLEY", "GEAR*", "ENGRENAGE*", "ШЕСТЕР*", "GEARBOX*",
                      "КОРОБК*", "ДИФФЕРЕНЦ*", "DIFFERENTIAL*", "DIFF", "SPROCKET*", "ЗВЕЗД*", "CHAIN*",
                      "CHAINE*", "ЦЕП*", "AXLE*", "ARBRE*", "HALF SHAFT", "HALF-SHAFT", "ПОЛУОС*", "ВАЛ",
                      "SHAFT*", "PROP SHAFT", "PROPELLER SHAFT", "КАРДАН*", "CV JOINT", "CV-JOINT",
                      "JOINT CV", "ШРУС*", "BOOT KIT", "BOOT", "ПЫЛЬНИК*", "SOUFFLET*", "PINION*",
                      "TRANSMISSION*", "TRANSFER*", "RAMP*", "ROLLER*", "SLIDING", "SPIDER*", "SPRING CLUTCH",
                      "COUPLER*", "COUPLING*", "YOKE*", "SHIFT*", "SELECTOR*", "SYNCHRO*", "TEETH")),

    # --- подвеска и рулевое
    ("suspension", _rx("SHOCK*", "AMORTISSEUR*", "АМОРТИЗАТОР*", "SPRING*", "RESSORT*", "ПРУЖИН*", "ARM*",
                       "A-ARM*", "BRAS", "РЫЧАГ*", "BALL JOINT*", "ROTULE*", "ШАРОВ*", "TIE ROD*",
                       "TIE-ROD*", "ТЯГ*", "РУЛЕВ*", "STEERING*", "DIRECTION", "KNUCKLE*", "ПОВОРОТН*",
                       "КУЛАК*", "STABILIZER*", "STABILISATEUR*", "SWAY BAR", "ANTI-ROLL*", "СТАБИЛИЗ*",
                       "SUSPENSION*", "ПОДВЕСК*", "TRAILING ARM", "SWING ARM", "SWING*", "TORSION*",
                       "LINK*", "BIELLE*", "LIMITER*", "STRAP LIMITER", "ROD END", "FOX", "KYB",
                       "ECS*", "PIVOT*")),

    # --- подшипники и втулки (после подвески, но до двигателя)
    ("bearing", _rx("BEARING*", "ROULEMENT*", "ПОДШИПН*", "BUSHING*", "BAGUE*", "COUSSINET*", "ВТУЛК*",
                    "SLEEVE*", "MANCHON*", "NEEDLE*", "AIGUILLE*", "IGUS")),

    # --- уплотнения
    ("seal", _rx("GASKET*", "JOINT TORIQUE", "JOINT ETANCH*", "JOINT D ETANCH*", "JOINT CULASSE",
                 "JOINT CARTER", "JOINT", "JOINTS", "ПРОКЛАД*", "SEAL*", "ETANCHE*", "ÉTANCHE*",
                 "САЛЬНИК*", "O-RING*", "O RING", "ORING*", "TORIQUE", "КОЛЬЦ*", "UPLOTN*", "УПЛОТН*",
                 "SEAL KIT", "GROMMET*", "PASSE FIL", "ВТУЛКА РЕЗИН*")),

    # --- охлаждение
    ("cooling", _rx("RADIATOR*", "RADIATEUR*", "РАДИАТОР*", "THERMOSTAT*", "ТЕРМОСТАТ*", "WATER PUMP",
                    "POMPE A EAU", "ПОМП*", "FAN*", "VENTILAT*", "ВЕНТИЛЯТОР*", "COOLING*", "REFROID*",
                    "ОХЛАЖД*", "HEAT EXCHANGER", "INTERCOOLER", "RADIATOR RELOCATOR*")),

    # --- топливо, впуск, выпуск
    ("fuel", _rx("FUEL*", "ESSENCE", "CARBURANT", "ТОПЛИВ*", "БЕНЗ*", "INJECTOR*", "INJECTEUR*", "ФОРСУНК*",
                 "THROTTLE BODY", "ДРОССЕЛ*", "CARBURETOR*", "CARBURATEUR*", "КАРБЮРАТОР*", "INTAKE*",
                 "ADMISSION", "ВПУСК*", "AIR BOX", "AIRBOX", "SNORKEL*", "ШНОРКЕЛ*", "EXHAUST*",
                 "ECHAPPEMENT*", "ВЫХЛОП*", "ГЛУШИТЕЛ*", "MUFFLER*", "SILENCIEUX*", "SILENCER*",
                 "TUNED PIPE", "PIPE*", "REED*", "TANK*", "RESERVOIR*", "БАК*", "FUEL PUMP", "POMPE",
                 "PUMP*", "НАСОС*", "SUPERCHARGER*", "TURBO*", "КОМПРЕССОР*", "PRIMER*", "AIR",
                 "HOSE*", "BOYAU*", "ШЛАНГ*", "TUBE*", "TUYAU*", "ПАТРУБ*", "ТРУБК*", "LINE*",
                 "DRAIN*", "VIDANGE", "FUEL CAP", "GAS CAP")),

    # --- двигатель
    ("engine", _rx("ENGINE*", "MOTEUR*", "ДВИГАТЕЛ*", "ДВС", "PISTON*", "ПОРШН*", "ПОРШЕН*", "CYLINDER*",
                   "CYLINDRE*", "ЦИЛИНДР*", "CRANKSHAFT*", "VILEBREQUIN*", "КОЛЕНВАЛ*", "CAMSHAFT*",
                   "CAM", "РАСПРЕДВАЛ*", "VALVE*", "SOUPAPE*", "КЛАПАН*", "ROCKER*", "CULBUTEUR*",
                   "HEAD", "CULASSE*", "ГОЛОВК*", "CRANKCASE*", "CARTER*", "КАРТЕР*", "CONNECTING ROD",
                   "PISTON RING*", "SEGMENT*", "TIMING*", "ГРМ", "STARTER*", "DEMARREUR*", "СТАРТЕР*",
                   "BENDIX", "OIL PUMP", "PUMP OIL", "ROTAX", "MAGNETO*", "STATOR*", "FLYWHEEL*",
                   "VOLANT*", "МАХОВИК*", "RAVE*", "COMPRESSION*", "DECOMPRESSOR*", "BLOCK", "SHORT BLOCK",
                   "LONG BLOCK", "COVER ENGINE", "MOTOR")),

    # --- электрика и электроника
    ("electric", _rx("SWITCH*", "INTERRUPTEUR*", "ВЫКЛЮЧАТЕЛ*", "ПЕРЕКЛЮЧАТ*", "КНОПК*", "BUTTON*",
                     "SENSOR*", "CAPTEUR*", "ДАТЧИК*", "SONDE*", "RELAY*", "RELAIS*", "РЕЛЕ", "FUSE*",
                     "FUSIBLE*", "ПРЕДОХРАНИТ*", "HARNESS*", "FAISCEAU*", "WIRING*", "WIRE*", "CABLAGE*",
                     "ПРОВОД*", "ЖГУТ*", "КОСА", "MODULE*", "МОДУЛ*", "ECU", "ECM", "ЭБУ", "CONTROLLER*",
                     "CONTROL UNIT", "BLOC*", "GAUGE*", "CLUSTER*", "DISPLAY*", "ДИСПЛЕ*", "ПРИБОР*",
                     "SPEEDOMETER*", "INDICATOR*", "VOLTAGE*", "REGULATOR*", "РЕГУЛЯТОР*", "RECTIFIER*",
                     "ALTERNATOR*", "ГЕНЕРАТОР*", "SOLENOID*", "СОЛЕНОИД*", "ACTUATOR*", "ACTIONNEUR*",
                     "CONNECTOR*", "CONNECTEUR*", "РАЗЪЕМ*", "РАЗЪЁМ*", "SOCKET*", "PRISE*", "USB",
                     "12V", "12 V", "OUTLET*", "ANTENNA*", "KEY*", "CLE*", "КЛЮЧ*", "DESS*", "D.E.S.S.",
                     "TETHER*", "LANYARD*", "ЧЕК*", "BEEPER*", "HORN*", "КЛАКСОН*", "CABLE ELECT*",
                     "VSS*", "DPS*", "IBR MODULE", "ELECTRONIC*", "ELECTRIQUE*", "ЭЛЕКТР*", "MOTOR WIPER")),

    # --- управление
    ("controls", _rx("HANDLEBAR*", "GUIDON*", "РУЛЬ", "РУЛЯ", "GRIP*", "POIGNEE*", "РУКОЯТ*", "РУЧК*",
                     "THROTTLE*", "ACCELERATEUR*", "КУРОК*", "ГАЗ*", "LEVER*", "LEVIER*", "CABLE*",
                     "CÂBLE*", "ТРОС*", "PEDAL*", "PEDALE*", "ПЕДАЛ*", "HANDLE*", "STEERING WHEEL",
                     "SHIFTER", "KNOB*", "БОУДЕН*", "RISER*", "ПРОСТАВК* РУЛ*")),

    # --- наклейки
    ("decal", _rx("DECAL*", "DECALQUE*", "НАКЛЕЙК*", "STICKER*", "AUTOCOLLANT*", "LOGO*", "EMBLEM*",
                  "EMBLEME*", "ЭМБЛЕМ*", "IDENT*", "WARNING*", "LABEL*", "ETIQUETTE*", "ШИЛЬДИК*",
                  "GRAPHIC*", "WRAP*", "PATCH*")),

    # --- кузов и пластик
    ("body", _rx("PANEL*", "PANNEAU*", "ПАНЕЛ*", "SIDEPANEL*", "HOOD*", "CAPOT*", "КАПОТ*", "FENDER*",
                 "AILE*", "КРЫЛ*", "COVER*", "COUVERCLE*", "КРЫШК*", "КОЖУХ*", "GRILLE*", "GRILL*",
                 "РЕШЕТК*", "РЕШЁТК*", "FACIA*", "FASCIA*", "BODY*", "CARROSSERIE*", "КУЗОВ*", "TRIM*",
                 "НАКЛАДК*", "МОЛДИНГ*", "ПЛАСТИК*", "CONSOLE*", "КОНСОЛ*", "DASH*", "ТОРПЕДО*",
                 "BELLY PAN", "BELLYPAN", "PAN", "BOTTOM PAN", "FOOTBOARD*", "FLOOR*", "ПОЛ",
                 "FOOTWELL*", "TUNNEL*", "ТОННЕЛ*", "NOSE*", "НОС*", "FAIRING*", "КАРЕНАЖ*",
                 "HULL*", "КОРПУС*", "COQUE*", "DECK*", "ДЕК*", "FOAM*", "MOUSSE*", "ПЕНА*",
                 "MAT*", "КОВРИК*", "BUMPER STICKER", "FRAME*", "CADRE*", "CHASSIS*", "РАМ*",
                 "CAGE*", "КАРКАС*", "ROLL CAGE", "BEAM*", "POUTRE*", "REINFORCEMENT*", "RENFORT*",
                 "MEMBER*", "TRAVERSE*", "LINER*", "BOOT COVER", "SIDE", "LATERAL*", "ACCESS*",
                 "PLATE*", "PLAQUE*", "ПЛАСТИН*", "SUPPORT*", "КРОНШТЕЙН*", "BRACKET*", "ОПОР*",
                 "HOLDER*", "MOUNT*", "МОНТАЖ*", "LATCH*", "LOQUET*", "ЗАЩЕЛК*", "ЗАМОК*",
                 "LOCK*", "SERRURE*", "HINGE*", "ПЕТЛ*", "КРЕПЛЕН*")),

    # --- крепёж
    ("fastener", _rx("SCREW*", "VIS", "ВИНТ*", "SAMOREZ", "САМОРЕЗ*", "BOLT*", "BOULON*", "БОЛТ*",
                     "NUT", "NUTS", "ECROU*", "ГАЙК*", "WASHER*", "RONDELLE*", "ШАЙБ*", "RIVET*", "ЗАКЛЕП*",
                     "CLIP*", "CLIPS", "AGRAFE*", "КЛИПС*", "ПИСТОН*", "CLAMP*", "BRIDE*", "COLLIER*",
                     "ХОМУТ*", "OETIKER*", "PIN", "PINS", "GOUPILLE*", "ШПЛИНТ*", "ШТИФТ*", "CIRCLIP*",
                     "CIRCLIPS", "ANNEAU*", "СТОПОРН*", "STUD", "STUDS", "ГОЛЖ*", "SPACER*", "ENTRETOISE*",
                     "ПРОСТАВК*", "DISTANC*", "HEX", "TORX", "DIN", "FLANGED", "FLANGE*", "КРЕПЕЖ*",
                     "КРЕПЁЖ*", "PUSH PIN", "PUSH RIVET", "RETAINER*", "RETENUE*", "FASTENER*",
                     "INSERT*", "ВТУЛКА РЕЗЬБ*", "DOUILLE*", "COTTER", "CABLE TIE*", "TIE", "ATTACHE*",
                     "СТЯЖК*", "STOPPER*", "BOUCHON*", "ПРОБК*", "PLUG", "PLUGS", "CAP", "CAPS",
                     "CAPUCHON*", "КОЛПАЧ*", "ЗАГЛУШК*", "BUMPER RUBBER", "RUBBER*", "CAOUTCHOUC*",
                     "РЕЗИН*", "ELASTIC*", "ELASTIQUE*", "SPRING CLIP", "HOOK AND LOOP", "VELCRO",
                     "BALL", "BILLE*", "ШАРИК*", "KEY WOODRUFF", "WOODRUFF")),
]

# --------------------------------------------------------------------------
# Запасной признак: префикс артикула BRP (если название ничего не дало)
# --------------------------------------------------------------------------
ARTICLE_PREFIX_RULES: list[tuple[str, str]] = [
    ("779", "oil"),          # локальные коды масел и химии XPS
    ("2936", "oil"),
    ("6195", "oil"),
    ("4173", "belt"),
    ("4222", "belt"),
    ("860", "acc_other"),    # аксессуары BRP (Ski-Doo / Can-Am / Sea-Doo)
    ("295", "acc_other"),    # аксессуары Sea-Doo
    ("4448", "acc_other"),   # одежда / экипировка
    ("420", "engine"),       # детали двигателей Rotax
]

# --------------------------------------------------------------------------
# Техника — по названию и префиксу артикула
# --------------------------------------------------------------------------
PLATFORMS: dict[str, str] = {
    "atv_ssv": "Квадро и SSV",
    "snow": "Снегоходы",
    "pwc": "Гидроциклы",
    "engine": "Двигатели Rotax",
    "all": "Общее",
}

PLATFORM_NAME_RULES: list[tuple[str, re.Pattern]] = [
    ("pwc", _rx("SEA DOO", "SEA-DOO", "SEADOO", "RXT*", "RXP*", "GTX*", "GTI*", "GTR*", "WAKE*", "FISH PRO",
                "FISHPRO", "SPARK", "EXPLORER", "SWITCH PONTOON", "JET PUMP", "IMPELLER*", "WEAR RING",
                "IBR*", "ГИДРОЦИКЛ*", "PWC", "HULL*")),
    ("snow", _rx("SKI DOO", "SKI-DOO", "SKIDOO", "LYNX", "SUMMIT*", "MXZ*", "RENEGADE*", "EXPEDITION*",
                 "SKANDIC*", "TUNDRA*", "FREERIDE*", "BACKCOUNTRY*", "GRAND TOURING", "REV*", "XU", "XM",
                 "XS", "G4", "G5", "SLIDER*", "СКЛИЗ*", "СНЕГОХОД*", "TRACK", "ГУСЕНИЦ*", "CARBIDE*",
                 "RUNNER*", "TUNNEL*", "E-TEC", "ETEC", "TURBO R", "TURBOR", "SNOW")),
    ("atv_ssv", _rx("CAN-AM", "CAN AM", "CANAM", "OUTLANDER*", "RENEGADE ATV", "MAVERICK*", "MAV*",
                    "DEFENDER*", "COMMANDER*", "TRAXTER*", "X3", "ATV*", "SSV*", "UTV*", "КВАДРОЦИКЛ*",
                    "СНЕГОБОЛОТОХОД*", "G2*", "G3*", "SPYDER*", "RYKER*", "TIRE*", "ШИН*", "WINCH*",
                    "ЛЕБЕДК*", "APACHE*", "HALF SHAFT", "CV JOINT")),
]

PLATFORM_PREFIX_RULES: list[tuple[str, str]] = [
    # снегоходы
    *[(p, "snow") for p in ("503", "504", "505", "506", "507", "508", "509", "510", "512", "513",
                            "515", "516", "517", "518", "860200")],
    # квадроциклы / SSV / трёхколёсные
    *[(p, "atv_ssv") for p in ("705", "706", "707", "708", "709", "710", "711", "715", "219400",
                               "219800", "4222")],
    # гидроциклы
    *[(p, "pwc") for p in ("204", "267", "269", "270", "271", "272", "273", "274", "275", "277",
                           "278", "291", "292", "295")],
    ("420", "engine"),
]


# --------------------------------------------------------------------------

_LOOKALIKE = str.maketrans("АВЕКМНОРСТХУ", "ABEKMHOPCTXY")


def _fix_mixed(token: str) -> str:
    """«WINDОW» с кириллической О → WINDOW: в латинском слове заменяем похожие кириллические буквы."""
    if re.search(r"[A-Z]", token) and re.search(r"[А-Я]", token):
        return token.translate(_LOOKALIKE)
    return token


def normalize(name: str | None) -> str:
    if not name:
        return ""
    text = str(name).upper().replace("Ё", "Е")
    text = " ".join(_fix_mixed(t) for t in text.split())
    text = re.sub(r"[*_]", " ", text)
    # бренды склеиваем, чтобы «SKI-DOO» не ловилось как «SKI», а «SEA-DOO» — как «SEA»
    text = re.sub(r"\bSKI[\s\-]?DOO\b", "SKIDOO", text)
    text = re.sub(r"\bSEA[\s\-]?DOO\b", "SEADOO", text)
    text = re.sub(r"\bCAN[\s\-]?AM\b", "CANAM", text)
    # служебные слова 1С не несут смысла детали
    text = re.sub(r"ГАРАНТИЙН\w*(\s+(КОМПЛЕКТ|ЗАПЧАСТЬ))?", " ", text)
    text = re.sub(r"(?<![А-Я])ЗАПЧАСТЬ(?![А-Я])", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"\s+", " ", text).strip()


def classify(name: str | None, article: str | None = None) -> tuple[str, str]:
    """→ (код группы, чем определено: 'name:<слово>' | 'article:<префикс>' | 'none')."""
    text = normalize(name)
    for code, rx in NAME_RULES:
        m = rx.search(text)
        if m:
            return code, f"name:{m.group(0).strip() or code}"
    art = (article or "").strip()
    for prefix, code in ARTICLE_PREFIX_RULES:
        if art.startswith(prefix):
            return code, f"article:{prefix}"
    return "other", "none"


def platform(name: str | None, article: str | None = None) -> str:
    text = normalize(name)
    for code, rx in PLATFORM_NAME_RULES:
        if rx.search(text):
            return code
    art = (article or "").strip()
    for prefix, code in PLATFORM_PREFIX_RULES:
        if art.startswith(prefix):
            return code
    return "all"
