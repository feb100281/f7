"""
Замены номеров: один товар под разными артикулами → семейство с актуальным номером.

Правила (только добавляют пары, решения менеджера не трогают):
    1. X → 9X     — EU-версия товара у BRP: тот же номер с девяткой спереди (779282 → 9779282).
    2. масла и химия — одинаковые характеристики в названии: тип (2T/4T/трансмиссионное…),
                    вязкость, синтетика/полусинтетика, объём. Актуальный — самый новый номер,
                    который продаётся последние полгода.
    3. номер в названии — «… (619590097)»: только предложение, подтверждает менеджер.

rebuild_families() по действующим заменам проставляет Item.family_head — куда переходят прогноз,
статистика и «год назад». Цепочки A → B → C разворачиваются до конца.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import timedelta

from django.db import transaction
from django.db.models import Max

from catalog.models import Item, ItemReplacement, ReplacementSource as Src, ReplacementStatus as St

SPEC_GROUPS = ("oil", "chem")
RECENT_DAYS = 183
NEW_DAYS = 183           # новинка: продажи пошли за последние полгода…
NEW_BEFORE_SHARE = 0.10  # …а до этого продано не больше 10% от продаж за эти полгода
SALE_KINDS = ("service", "sale", "retail")
# при нескольких действующих заменах у одного номера побеждает более надёжный источник
PRIORITY = {Src.MANUAL: 0, Src.CLIENT: 1, Src.RULE_9X: 2, Src.OIL: 3, Src.NAME: 4}


def oil_spec(name: str) -> frozenset:
    """Характеристики масла/химии из названия: тип, вязкость, синтетика, объём (л)."""
    s = (name or "").upper().replace(",", ".")
    t = set()
    if re.search(r"\b(2T|2 STROKE|2-STROKE)\b", s):
        t.add("2T")
    if re.search(r"\b(4T|4 STROKE|4-STROKE)\b", s):
        t.add("4T")
    for v in re.findall(r"\b(\d{1,2}W-?\d{2,3})\b", s):
        t.add(v.replace("-", ""))
    if re.search(r"GEAR|TRANS|SYNCHRO", s):
        t.add("GEAR")
    if "CHAINCASE" in s:
        t.add("CHAIN")
    if "E-TEC" in s:
        t.add("ETEC")
    # полусинтетика пишется по-разному: BLEND, полусинт, п/с; летнее XPS 5W-40 (Summer) — тоже полусинтетика
    if re.search(r"BLEND|ПОЛУСИНТ|SEMI|П/С|SUMMER", s):
        t.add("BLEND")
    elif re.search(r"SYNTH|СИНТЕТ", s):
        t.add("SYN")
    # моторная вязкость (0W–20W) без трансмиссии/цепи — масло 4T, даже если «4T» в названии нет
    if not t & {"GEAR", "CHAIN", "2T"} and any(re.fullmatch(r"(0|5|10|15|20)W\d+", v) for v in t):
        t.add("4T")
    vol = None
    m = re.search(r"(\d+(?:\.\d+)?)\s*(L|Л|ML|МЛ)\b", s)
    if m:
        vol = float(m.group(1)) / (1000 if m.group(2) in ("ML", "МЛ") else 1)
    elif re.search(r"\bQT\b|QUART", s):
        vol = 0.946
    elif re.search(r"\bGAL\b|GALLON", s):
        vol = 3.785
    if vol:
        # BRP пишет одну банку и «1L», и «0,946L / QT»; галлон — и 3,785, и «4L»
        vol = 1.0 if 0.9 <= vol <= 1.0 else 3.785 if 3.7 <= vol <= 4.0 else round(vol, 2)
        t.add(f"V{vol:g}")
    return frozenset(t)


def _pair_exists(pairs: set, a: int, b: int) -> bool:
    return (a, b) in pairs or (b, a) in pairs


def apply_rules(log=print) -> dict:
    """Добавить замены по правилам. Существующие пары (в любую сторону, с любым статусом) не трогаем."""
    items = list(Item.objects.select_related("group").only(
        "id", "article", "name", "first_sale", "last_sale", "group__code"))
    by_article = {i.article: i for i in items}
    pairs = set(ItemReplacement.objects.values_list("old_id", "new_id"))
    new_links: list[ItemReplacement] = []

    def add(old, new, source, status=St.ACTIVE, note=""):
        if old.pk == new.pk or _pair_exists(pairs, old.pk, new.pk):
            return
        pairs.add((old.pk, new.pk))
        new_links.append(ItemReplacement(old=old, new=new, source=source, status=status, note=note[:250]))

    # 1. X → 9X
    for it in items:
        if re.fullmatch(r"9\d{6,}", it.article) and it.article[1:] in by_article:
            add(by_article[it.article[1:]], it, Src.RULE_9X)
    n9 = len(new_links)

    # 2. масла и химия: семейства по характеристикам. Номер, уже переведённый на другой
    #    (X → 9X, решение менеджера), участвует своим актуальным номером — концом цепочки.
    active = {(link.old_id, link.new_id) for link in new_links}
    active |= set(ItemReplacement.objects.filter(status=St.ACTIVE).values_list("old_id", "new_id"))
    nxt = dict(active)
    by_id = {i.pk: i for i in items}

    def end_of(i: int) -> int:
        seen = {i}
        while i in nxt and nxt[i] not in seen:
            i = nxt[i]
            seen.add(i)
        return i

    last_any = Item.objects.aggregate(m=Max("last_sale"))["m"]
    recent = (last_any - timedelta(days=RECENT_DAYS)) if last_any else None
    families = defaultdict(set)
    for it in items:
        if it.group and it.group.code in SPEC_GROUPS and it.first_sale:
            key = oil_spec(it.name)
            if len(key) >= 3 and any(k.startswith("V") for k in key):
                families[key].add(end_of(it.pk))
    for key, ends in families.items():
        if len(ends) < 2:
            continue
        members = [by_id[e] for e in ends]
        alive = [m for m in members if recent and m.last_sale and m.last_sale >= recent] or members
        head = max(alive, key=lambda m: (m.first_sale, m.article))
        for m in members:
            if m.pk != head.pk:
                add(m, head, Src.OIL, note=" ".join(sorted(key)))
                nxt[m.pk] = head.pk
    n_oil = len(new_links) - n9

    # 3. номер другого артикула в названии — предложение (кроме уже склеенных в одно семейство).
    #    Новым считаем тот, что продавался позже.
    for it in items:
        for num in re.findall(r"\b(\d{6,10})\b", it.name or ""):
            other = by_article.get(num)
            if not other or other.pk == it.pk or not (it.last_sale and other.last_sale):
                continue
            if end_of(it.pk) == end_of(other.pk):
                continue
            a, b = sorted((it, other), key=lambda m: (m.last_sale, m.first_sale or m.last_sale))
            add(a, b, Src.NAME, St.SUGGESTED, note=f"в названии {it.article}: «{it.name[:120]}»")
    n_name = len(new_links) - n9 - n_oil

    ItemReplacement.objects.bulk_create(new_links)
    log(f"   новых замен: X→9X {n9}, масла/химия {n_oil}, предложено по названию {n_name}")
    return {"rule9x": n9, "oil": n_oil, "name": n_name}


def rebuild_families(log=print) -> dict:
    """Item.family_head по действующим заменам: каждый номер → конец своей цепочки замен."""
    best: dict[int, tuple] = {}
    for old, new, source, updated in ItemReplacement.objects.filter(status=St.ACTIVE).values_list(
            "old_id", "new_id", "source", "updated"):
        cand = (PRIORITY.get(source, 9), -updated.timestamp(), new)
        if old not in best or cand < best[old]:
            best[old] = cand
    nxt = {old: c[2] for old, c in best.items()}

    def head_of(i: int) -> int | None:
        seen, cur = {i}, i
        while cur in nxt and nxt[cur] not in seen:
            cur = nxt[cur]
            seen.add(cur)
        return cur if cur != i else None

    target = {i: head_of(i) for i in nxt}
    current = dict(Item.objects.exclude(family_head=None).values_list("id", "family_head_id"))
    changed = []
    with transaction.atomic():
        for i in set(current) | set(target):
            h = target.get(i)
            if current.get(i) != h:
                changed.append(Item(pk=i, family_head_id=h))
        Item.objects.bulk_update(changed, ["family_head"], batch_size=1000)
    mark_new(log)
    heads = len({h for h in target.values() if h})
    log(f"   семейств: {heads}, номеров переведено на актуальный: {sum(1 for h in target.values() if h)}, "
        f"изменилось: {len(changed)}")
    return {"families": heads, "members": sum(1 for h in target.values() if h), "changed": len(changed)}



def mark_new(log=print) -> int:
    """Item.is_new / new_since — новинка: продажи пошли за последние NEW_DAYS дней, а до этого
    по всему семейству номеров почти ничего (не больше NEW_BEFORE_SHARE от продаж за полгода:
    разовая тестовая продажа год назад новинку не отменяет). 9779282 с историей 779282 — не новинка,
    старые номера семьи новинками не бывают. new_since — первая продажа за эти полгода
    (или вообще первая, если раньше продаж не было)."""
    from django.db.models import Min, Q, Sum
    from django.db.models.functions import Coalesce

    from sales.models import SalesLine

    last_any = Item.objects.aggregate(m=Max("last_sale"))["m"]
    if not last_any:
        return 0
    border = last_any - timedelta(days=NEW_DAYS)
    fam = Coalesce("item__family_head_id", "item_id")
    rows = (SalesLine.objects.filter(doc__kind__in=SALE_KINDS)
            .annotate(f=fam).values("f")
            .annotate(pre=Sum("qty", filter=Q(doc__date__lt=border), default=0),
                      post=Sum("qty", filter=Q(doc__date__gte=border), default=0),
                      first_post=Min("doc__date", filter=Q(doc__date__gte=border)),
                      first_any=Min("doc__date")))
    new = {}
    for r in rows:
        pre, post = float(r["pre"] or 0), float(r["post"] or 0)
        if post > 0 and pre <= NEW_BEFORE_SHARE * post:
            new[r["f"]] = r["first_any"] if pre == 0 else r["first_post"]

    items = list(Item.objects.only("id", "is_new", "new_since", "family_head"))
    changed = []
    for it in items:
        since = None if it.family_head_id else new.get(it.pk)
        if it.is_new != bool(since) or it.new_since != since:
            it.is_new, it.new_since = bool(since), since
            changed.append(it)
    Item.objects.bulk_update(changed, ["is_new", "new_since"], batch_size=1000)
    log(f"   новинок (продажи пошли с {border:%d.%m.%Y}): {len(new)}")
    return len(new)
